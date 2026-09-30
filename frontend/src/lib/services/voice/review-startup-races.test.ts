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

it('configures Qwen when the peer and provider session become active before SDP setup returns', async () => {
  const s=setup();
  s.pc.setRemoteDescription.mockImplementationOnce(async () => {
    s.pc.connect();
    s.pc.channel.emit({type:'session.created',session:{}});
    await s.session.whenProviderEventsIdle();
  });
  await s.session.start();
  const updates=s.pc.channel.sent.filter((event:any)=>event.type==='session.update');
  await s.session.end();
  expect(updates.length).toBeGreaterThan(0);
});

it('a stale camera pipeline resolution cannot orphan the replacement call camera pipeline', async () => {
  const s=setup();
  const replacementPeer = new FakePeerConnection();
  (s.session as any).options.createPeerConnection = () => replacementPeer;
  s.session.chooseCamera(true);
  let resolveOld!: (value:any)=>void;
  const oldMic=track('audio'),oldCamera=track('video'),oldOutbound=track('video');
  const oldDispose=vi.fn(()=>oldOutbound.stop());
  s.getUserMedia.mockResolvedValueOnce(mediaStream([oldMic],[oldCamera]));
  vi.spyOn(s.session as any,'createVideoPipeline').mockReturnValueOnce(new Promise(resolve=>{resolveOld=resolve;}));
  const oldStarting=s.session.start();
  await vi.waitFor(()=>expect(s.localStreams).toHaveLength(1));
  await s.session.end();
  await s.session.start();
  resolveOld({stream:mediaStream([],[oldOutbound]),track:oldOutbound,dispose:oldDispose});
  await oldStarting;
  await s.session.end();
  expect(s.outboundCamera.stop).toHaveBeenCalled();
  expect(s.disposeVideoPipeline).toHaveBeenCalled();
});

it('a late rejected camera pipeline cannot replace the new active peer', async () => {
  const s=setup();
  const currentPeer = new FakePeerConnection();
  const obsoletePeer = new FakePeerConnection();
  (s.session as any).options.createPeerConnection = vi.fn()
    .mockReturnValueOnce(currentPeer).mockReturnValueOnce(obsoletePeer);
  s.session.chooseCamera(true);
  let rejectOld!: (error:any)=>void;
  const oldMic=track('audio'),oldCamera=track('video');
  s.getUserMedia.mockResolvedValueOnce(mediaStream([oldMic],[oldCamera]));
  vi.spyOn(s.session as any,'createVideoPipeline').mockReturnValueOnce(new Promise((_resolve,reject)=>{rejectOld=reject;}));
  const oldStarting=s.session.start();
  await vi.waitFor(()=>expect(s.localStreams).toHaveLength(1));
  await s.session.end();
  await s.session.start();
  currentPeer.connect();
  currentPeer.channel.emit({type:'session.created',session:{}});
  await s.session.whenProviderEventsIdle();
  rejectOld(new Error('old camera failed'));
  await oldStarting;
  await s.session.end();
  expect(currentPeer.closed).toBe(true);
});

it('a delayed old-call delegation response cannot attach an old task to a replacement call', async () => {
  const s=setup();
  const replacementPeer = new FakePeerConnection();
  (s.session as any).options.createPeerConnection = vi.fn().mockReturnValueOnce(s.pc).mockReturnValueOnce(replacementPeer);
  (s.api.start as any).mockResolvedValueOnce({call_id:'call-old',sdp:'fixture'}).mockResolvedValueOnce({call_id:'call-new',sdp:'fixture'});
  let resolveOld!: (value:any)=>void;
  (s.api.startTask as any).mockReturnValueOnce(new Promise(resolve=>{resolveOld=resolve;}));
  (s.api.task as any).mockReturnValue(new Promise(()=>{}));
  await s.session.start();
  s.pc.connect();
  s.pc.channel.emit({type:'session.created',session:{}});
  await s.session.whenProviderEventsIdle();
  s.pc.channel.emit({type:'function_call_arguments.done',call_id:'old-delegation',name:'delegate_to_text_model',arguments:JSON.stringify({goal:'old goal'})});
  await vi.waitFor(()=>expect(s.api.startTask).toHaveBeenCalled());
  await s.session.end();
  await s.session.start();
  replacementPeer.connect();
  replacementPeer.channel.emit({type:'session.created',session:{}});
  await s.session.whenProviderEventsIdle();
  resolveOld({task_id:'old-task',status:'queued',model:'openrouter/luna-max',replayed:false,steered:false});
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(s.session.state.task).toBeNull();
  expect((s.session as any).taskPollCallId).toBeNull();
  expect(s.api.cancelTask).not.toHaveBeenCalled();
  expect(replacementPeer.channel.sent).not.toContainEqual(expect.objectContaining({
    type: 'conversation.item.create',
    item: expect.objectContaining({ call_id: 'old-delegation' }),
  }));
  await s.session.end();
});
