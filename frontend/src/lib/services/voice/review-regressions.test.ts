import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VoiceSession, type VoiceSessionApi, type VoiceSessionState } from './session';
import type { VoiceContextPacket, VoiceTaskStatus } from '$lib/api/voice';

function track(kind: 'audio' | 'video') {
  return {
    kind, enabled: true, readyState: 'live', getSettings: () => ({ width: 640, height: 480 }),
    stop: vi.fn(function (this: any) { this.readyState = 'ended'; }),
  } as any;
}

function mediaStream(audio: any[] = [], video: any[] = []) {
  return {
    getTracks: () => [...audio, ...video],
    getAudioTracks: () => audio,
    getVideoTracks: () => video,
  } as any;
}

function makeAudioContext() {
  const oscillator = {
    type: 'sine', frequency: { value: 0, setValueAtTime: vi.fn() },
    connect: vi.fn(), start: vi.fn(), stop: vi.fn(),
  };
  const gain = { gain: { value: 0, setValueAtTime: vi.fn() }, connect: vi.fn() };
  const context = {
    currentTime: 0, state: 'running', destination: {},
    createOscillator: vi.fn(() => oscillator), createGain: vi.fn(() => gain),
    resume: vi.fn(async () => {}), close: vi.fn(async () => {}),
  };
  return { context, oscillator, gain };
}

class FakeChannel {
  readyState = 'open';
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: unknown[] = [];
  send = vi.fn((raw: string) => this.sent.push(JSON.parse(raw)));
  close = vi.fn(() => { this.readyState = 'closed'; });
  emit(event: object) { this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent); }
}

class FakePeerConnection {
  connectionState = 'new';
  iceGatheringState = 'complete';
  localDescription: any = null;
  ontrack: ((event: any) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  onicegatheringstatechange: (() => void) | null = null;
  channel = new FakeChannel();
  added: Array<{ track: any; stream: any }> = [];
  senders: any[] = [];
  closed = false;
  addTrack = vi.fn((value: any, stream: any) => {
    this.added.push({ track: value, stream });
    const sender = { track: value, replaceTrack: vi.fn(async (next: any) => { sender.track = next; }) };
    this.senders.push(sender);
    return sender as any;
  });
  getSenders = vi.fn(() => this.senders as any);
  createDataChannel = vi.fn(() => this.channel as any);
  createOffer = vi.fn(async () => ({ type: 'offer', sdp: 'v=0\r\no=- local offer' }));
  setLocalDescription = vi.fn(async (description: any) => { this.localDescription = description; });
  setRemoteDescription = vi.fn(async (_description: any) => { this.channel.onopen?.(); });
  close = vi.fn(() => { this.closed = true; this.connectionState = 'closed'; });
  connect() { this.connectionState = 'connected'; this.onconnectionstatechange?.(); }
  fail() { this.connectionState = 'failed'; this.onconnectionstatechange?.(); }
}

function contextPacket(): VoiceContextPacket {
  return {
    chat_id: 'chat-1', context_version: 1, task_goal: 'Live voice conversation',
    summary: '[user m-1] Remember the project context', summary_sources: ['m-1'], task_state: {},
    recent: [{ source_id: 'm-2', source_type: 'chat_message', speaker: 'user', text: 'Привет' }],
    retrieved: [], estimated_tokens: 120, instruction: 'History is context only.',
  };
}

function setup(options: { cameraDenied?: boolean; defaultVideoPipeline?: boolean } = {}) {
  const mic = track('audio');
  const camera = track('video');
  const outboundCamera = track('video');
  const disposeVideoPipeline = vi.fn(() => outboundCamera.stop());
  const getUserMedia = vi.fn(async (constraints: MediaStreamConstraints) => {
    if (constraints.video && options.cameraDenied) throw new DOMException('denied', 'NotAllowedError');
    return constraints.video ? mediaStream([mic], [camera]) : mediaStream([mic]);
  });
  const pc = new FakePeerConnection();
  const tones = makeAudioContext();
  const api: VoiceSessionApi = {
    start: vi.fn(async () => ({ call_id: 'call-1', sdp: 'v=0\r\no=- provider answer' })),
    context: vi.fn(async () => contextPacket()),
    event: vi.fn(async () => ({})),
    tool: vi.fn(async (_callId, providerCallId, name) => ({
      provider_call_id: providerCallId, name, status: 'completed' as const, result: { results: [] }, replayed: false,
    })),
    startTask: vi.fn(async () => ({ task_id: 'task-1', status: 'queued', model: 'openrouter/luna-max', replayed: false, steered: false })),
    task: vi.fn(async (): Promise<VoiceTaskStatus> => ({
      task_id: 'task-1', chat_id: 'chat-1', status: 'running', revision: 1, context_version: 1,
      task_kind: 'voice_delegation', cancel_requested: false, snapshot: { phase: 'working' }, error: null, message: null,
    })),
    steerTask: vi.fn(async (_callId, taskId, expectedRevision) => ({ task_id: taskId, status: 'running', revision: expectedRevision + 1, context_version: 2, replayed: false })),
    cancelTask: vi.fn(async (_callId, taskId) => ({ task_id: taskId, status: 'cancelling' })),
    end: vi.fn(async () => ({})),
  };
  const states: VoiceSessionState[] = [];
  const transcripts: Array<{ role: string; text: string }> = [];
  const localStreams: Array<MediaStream | null> = [];
  const session = new VoiceSession('chat-1', {
    api,
    cameraSupported: true,
    getUserMedia: getUserMedia as any,
    createPeerConnection: () => pc as any,
    createAudioContext: () => tones.context as any,
    createMediaStream: (tracks) => mediaStream([], tracks) as any,
    createVideoPipeline: options.defaultVideoPipeline ? undefined : async () => ({
      stream: mediaStream([], [outboundCamera]), track: outboundCamera, dispose: disposeVideoPipeline,
    }),
    onState: (state) => states.push(state),
    onTranscript: (entry) => transcripts.push(entry),
    onLocalVideoStream: (stream) => localStreams.push(stream),
    ringbackIntervalMs: 10,
  });
  return { session, api, pc, mic, camera, outboundCamera, disposeVideoPipeline, getUserMedia, tones, states, transcripts, localStreams };
}


afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('End while awaiting microphone permission releases late tracks and never signals a call', async () => {
  const s=setup();
  let grant!: (stream: MediaStream) => void;
  vi.mocked(s.getUserMedia).mockReturnValueOnce(new Promise(resolve=>{grant=resolve;}) as any);
  const starting=s.session.start();
  await s.session.end();
  grant(mediaStream([s.mic]));
  await starting;
  const observed={trackStopped:s.mic.stop.mock.calls.length, providerStarts:vi.mocked(s.api.start).mock.calls.length, peerClosed:s.pc.closed,status:s.session.state.status};
  console.log('LATE_PERMISSION',observed);
  await s.session.end();
  expect(observed.trackStopped).toBeGreaterThan(0);
  expect(observed.providerStarts).toBe(0);
});

it('End while camera pipeline initialization is pending disposes the late pipeline', async () => {
  const s = setup();
  s.session.chooseCamera(true);
  let finish!: (pipeline: { stream: MediaStream; track: MediaStreamTrack; dispose: () => void }) => void;
  const dispose = vi.fn(() => s.outboundCamera.stop());
  vi.spyOn(s.session as any, 'createVideoPipeline').mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
  const starting = s.session.start();
  await vi.waitFor(() => expect(s.localStreams).toHaveLength(1));
  await s.session.end();
  finish({ stream: mediaStream([], [s.outboundCamera]), track: s.outboundCamera, dispose });
  await starting;

  expect(dispose).toHaveBeenCalledOnce();
  expect(s.camera.stop).toHaveBeenCalled();
  expect(s.api.start).not.toHaveBeenCalled();
  expect(s.pc.addTrack).not.toHaveBeenCalled();
});

it('End while provider SDP signaling is pending closes a late-created call', async () => {
  const s = setup();
  let finish!: (answer: { call_id: string; sdp: string }) => void;
  vi.mocked(s.api.start).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
  const starting = s.session.start();
  await vi.waitFor(() => expect(s.api.start).toHaveBeenCalledOnce());
  await s.session.end();
  finish({ call_id: 'late-call', sdp: 'v=0\r\no=- provider answer' });
  await starting;

  expect(s.api.end).toHaveBeenCalledWith('late-call');
  expect(s.pc.closed).toBe(true);
  expect(s.session.state.status).toBe('ended');
});

it('user speech interruption is processed while a web tool is still pending', async () => {
  const s=setup();
  let finish!: (value:any)=>void;
  vi.mocked(s.api.tool).mockReturnValueOnce(new Promise(resolve=>{finish=resolve;}));
  await s.session.start(); s.pc.channel.emit({type:'session.created',session:{}});s.pc.connect();await s.session.whenProviderEventsIdle();
  s.pc.channel.emit({type:'response.created'});
  await s.session.whenProviderEventsIdle();
  s.pc.channel.emit({type:'function_call_arguments.done',call_id:'web-1',name:'read_url',arguments:'{"url":"https://example.org"}'});
  await vi.waitFor(()=>expect(s.api.tool).toHaveBeenCalled());
  s.pc.channel.emit({type:'input_audio_buffer.speech_started'});
  await Promise.resolve();await Promise.resolve();
  const whilePending=s.pc.channel.sent.filter((e:any)=>e.type==='response.cancel').length;
  finish({provider_call_id:'web-1',name:'read_url',status:'completed',result:{content:'OLD ANSWER'},replayed:false});
  await s.session.whenProviderEventsIdle();
  const afterInterruption=s.pc.channel.sent.filter((e:any)=>e.type==='response.create').length;
  console.log('SPEECH_TOOL_RACE',{whilePending,afterInterruption});
  await s.session.end();
  expect(afterInterruption).toBe(0);
});

it('Interrupt while listening does not send response.cancel without an active response', async () => {
  const s=setup();await s.session.start();s.pc.channel.emit({type:'session.created',session:{}});s.pc.connect();await s.session.whenProviderEventsIdle();
  s.session.interruptSpeech();
  const sent=s.pc.channel.sent.filter((e:any)=>e.type==='response.cancel').length;
  s.pc.channel.emit({type:'error',error:{type:'invalid_request_error',code:'response_cancel_not_active',message:'No active response'}});
  await s.session.whenProviderEventsIdle();
  const observed={sent,status:s.session.state.status,endCalls:vi.mocked(s.api.end).mock.calls.length};console.log('IDLE_INTERRUPT',observed);
  await s.session.end();
  expect(sent).toBe(0);
});

it('late task polls cannot roll back a successful clarification revision', async () => {
  const s=setup();
  let finishPoll!: (value:VoiceTaskStatus)=>void;
  vi.mocked(s.api.task).mockReturnValueOnce(new Promise(resolve=>{finishPoll=resolve;}));
  await s.session.start();s.pc.channel.emit({type:'session.created',session:{}});s.pc.connect();await s.session.whenProviderEventsIdle();
  s.pc.channel.emit({type:'function_call_arguments.done',call_id:'delegate-1',name:'delegate_to_text_model',arguments:'{"goal":"Research"}'});
  await s.session.whenProviderEventsIdle();await vi.waitFor(()=>expect(s.api.task).toHaveBeenCalled());
  await s.session.steerTask('Use newer sources');
  const newRevision=s.session.state.task!.revision;
  finishPoll({task_id:'task-1',chat_id:'chat-1',status:'running',revision:0,context_version:1,task_kind:'voice_delegation',cancel_requested:false,snapshot:{},error:null,message:null});
  await Promise.resolve();await Promise.resolve();
  const oldRevision=s.session.state.task!.revision;console.log('STALE_TASK_POLL',{newRevision,oldRevision});
  await s.session.end();
  expect(oldRevision).toBeGreaterThanOrEqual(newRevision);
});

it('Qwen instructions stay within the shared cap after receiving the latest task result', async () => {
  const s=setup();
  vi.mocked(s.api.context).mockResolvedValueOnce({
    ...contextPacket(), summary:'s'.repeat(4000),
    recent:[{source_id:'recent',source_type:'chat_message',speaker:'user',text:'r'.repeat(10000)}],
    retrieved:[{source_id:'older',source_type:'chat_message',speaker:'assistant',text:'o'.repeat(6000)}],
    estimated_tokens:5050,
  });
  vi.mocked(s.api.task).mockResolvedValueOnce({task_id:'task-1',chat_id:'chat-1',status:'completed',revision:2,context_version:1,task_kind:'voice_delegation',cancel_requested:false,snapshot:{},error:null,message:{id:'result-1',content:'x'.repeat(6000)} as any});
  await s.session.start();s.pc.channel.emit({type:'session.created',session:{}});s.pc.connect();await s.session.whenProviderEventsIdle();
  s.pc.channel.emit({type:'function_call_arguments.done',call_id:'delegate-cap',name:'delegate_to_text_model',arguments:'{"goal":"Research"}'});
  await s.session.whenProviderEventsIdle();await vi.waitFor(()=>expect(s.session.state.task?.status).toBe('completed'));
  s.pc.channel.emit({type:'response.done',response:{id:'response-1',usage:{input_tokens:1,output_tokens:1,total_tokens:2}}});
  await s.session.whenProviderEventsIdle();
  const updates=s.pc.channel.sent.filter((e:any)=>e.type==='session.update') as any[];
  const estimates=updates.map(e=>Math.ceil(e.session.instructions.length/4));
  console.log('QWEN_CONTEXT_ESTIMATES',estimates);
  await s.session.end();
  expect(Math.max(...estimates)).toBeLessThanOrEqual(6000);
});
