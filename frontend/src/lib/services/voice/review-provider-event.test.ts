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
  autoAcknowledgeSessionUpdates = true;
  send = vi.fn((raw: string) => {
    const event = JSON.parse(raw);
    this.sent.push(event);
    if (event.type === 'session.update' && this.autoAcknowledgeSessionUpdates) {
      queueMicrotask(() => this.emit({ type: 'session.updated', session: {} }));
    }
  });
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

it('keeps outbound audio gated while initial provider configuration awaits context', async () => {
  const s = setup();
  let finishContext!: (packet: VoiceContextPacket) => void;
  vi.mocked(s.api.context).mockReturnValueOnce(new Promise(resolve => { finishContext = resolve; }));
  const starting = s.session.start();
  await vi.waitFor(() => expect(s.pc.setRemoteDescription).toHaveBeenCalled());
  s.pc.connect();
  s.pc.channel.emit({ type: 'session.created', session: { id: 'provider-session' } });
  await s.session.whenProviderEventsIdle();
  const observed = {
    audioEnabled: s.mic.enabled,
    senderHasAudio: s.pc.senders.some(sender => sender.track === s.mic),
    configurationSent: s.pc.channel.sent.some((event: any) => event.type === 'session.update'),
    status: s.session.state.status,
  };
  finishContext(contextPacket());
  await starting;
  await s.session.end();
  expect(observed.configurationSent).toBe(false);
  expect(observed.audioEnabled).toBe(false);
  expect(observed.senderHasAudio).toBe(false);
});

it('opens microphone media only after the initial session.update acknowledgement', async () => {
  const s = setup();
  s.pc.channel.autoAcknowledgeSessionUpdates = false;
  await s.session.start();
  s.pc.connect();
  s.pc.channel.emit({ type: 'session.created', session: {} });
  await s.session.whenProviderEventsIdle();

  expect(s.pc.channel.sent.some((event: any) => event.type === 'session.update')).toBe(true);
  expect(s.pc.senders[0].track).toBeNull();
  expect(s.mic.enabled).toBe(false);
  expect(s.session.state.status).toBe('connecting');

  s.pc.channel.emit({ type: 'session.updated', session: {} });
  await s.session.whenProviderEventsIdle();
  expect(s.pc.senders[0].track).toBe(s.mic);
  expect(s.mic.enabled).toBe(true);
  expect(s.session.state.status).toBe('active');
  await s.session.end();
});

it('executes a web tool from the documented Qwen Audio 3.1 function-call event', async () => {
  const s=setup();
  await s.session.start();
  s.pc.connect();
  s.pc.channel.emit({type:'session.created',session:{}});
  await s.session.whenProviderEventsIdle();
  s.pc.channel.emit({type:'response.function_call_arguments.done',call_id:'documented-web',name:'read_url',arguments:'{"url":"https://example.org"}'});
  await s.session.whenProviderEventsIdle();
  const observed=vi.mocked(s.api.tool).mock.calls.length;
  await s.session.end();
  expect(observed).toBe(1);
});

it('starts Luna from the documented Qwen Audio 3.1 function-call event', async () => {
  const s=setup();
  await s.session.start();
  s.pc.connect();
  s.pc.channel.emit({type:'session.created',session:{}});
  await s.session.whenProviderEventsIdle();
  s.pc.channel.emit({type:'response.function_call_arguments.done',call_id:'documented-task',name:'delegate_to_text_model',arguments:'{"goal":"Research this"}'});
  await s.session.whenProviderEventsIdle();
  const observed=vi.mocked(s.api.startTask).mock.calls.length;
  await s.session.end();
  expect(observed).toBe(1);
});
