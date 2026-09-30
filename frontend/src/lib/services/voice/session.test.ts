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
    cancelTool: vi.fn(async (_callId, providerCallId) => ({ provider_call_id: providerCallId, status: 'cancelling' })),
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

describe('VoiceSession WebRTC controller', () => {
  beforeEach(() => vi.useRealTimers());
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('starts direct audio, fetches authenticated context, configures Qwen tools and stops ringback on connect', async () => {
    const s = setup();
    await s.session.start();

    expect(s.getUserMedia).toHaveBeenCalledWith({ audio: true, video: false });
    expect(s.api.start).toHaveBeenCalledWith('chat-1', expect.stringContaining('v=0'), false);
    expect(s.api.context).toHaveBeenCalledWith('call-1');
    expect(s.pc.added.map((entry) => entry.track.kind)).toEqual(['audio']);
    expect(s.api.start).toHaveBeenCalledWith('chat-1', expect.stringContaining('v=0'), false);
    expect(s.pc.senders[0].replaceTrack).toHaveBeenCalledWith(null);
    expect(s.pc.senders[0].track).toBeNull();
    s.pc.channel.emit({ type: 'session.created', session: { model: 'catalog-model-fixture' } });
    s.pc.connect();
    await s.session.whenProviderEventsIdle();

    expect(s.session.state.status).toBe('active');
    const update = s.pc.channel.sent.find((event: any) => event.type === 'session.update') as any;
    expect(update.session.tools.map((tool: any) => tool.function.name)).toEqual(['web_search', 'read_url', 'delegate_to_text_model']);
    expect(update.session.modalities).toEqual(['audio', 'text']);
    expect(update.session.voice).toBe('longanqian_v3.1');
    expect(update.session.input_audio_transcription).toEqual({ language: 'ru' });
    expect(update.session.output_audio).toEqual({ language: 'ru' });
    expect(update.session.turn_detection).toEqual({ type: 'server_vad' });
    expect(update.session).not.toHaveProperty('video');
    expect(update.session.instructions).toContain('Remember the project context');
    expect(s.tones.oscillator.stop).toHaveBeenCalled();
  });

  it('asks for camera only after explicit pre-call selection and keeps audio if permission is denied', async () => {
    const s = setup({ cameraDenied: true });
    s.session.chooseCamera(true);
    await s.session.start();

    expect(s.getUserMedia).toHaveBeenNthCalledWith(1, expect.objectContaining({ audio: true, video: expect.objectContaining({ frameRate: { ideal: 30, max: 30 } }) }));
    expect(s.getUserMedia).toHaveBeenNthCalledWith(2, { audio: true, video: false });
    expect(s.pc.added.map((entry) => entry.track.kind)).toEqual(['audio']);
    expect(s.session.state.status).toBe('connecting');
    expect(s.session.state.cameraError).toBe('camera_permission_denied');
    expect(s.localStreams).toEqual([]);
  });

  it('sends only explicitly requested video, stops video when disabled and requires reconnect to turn it on again', async () => {
    const s = setup();
    s.session.chooseCamera(true);
    await s.session.start();
    expect(s.pc.added.map((entry) => entry.track.kind)).toEqual(['audio', 'video']);
    expect(s.api.start).toHaveBeenCalledWith('chat-1', expect.stringContaining('v=0'), true);
    expect(s.localStreams).toHaveLength(1);

    const videoSender = s.pc.senders[1];
    await s.session.setCamera(false);
    expect(s.camera.stop).toHaveBeenCalledOnce();
    expect(s.outboundCamera.stop).toHaveBeenCalledOnce();
    expect(s.disposeVideoPipeline).toHaveBeenCalledOnce();
    expect(videoSender.replaceTrack).toHaveBeenCalledWith(null);
    expect(s.session.state.cameraEnabled).toBe(false);
    expect(s.pc.channel.sent.some((event: any) => event.type === 'camera.frame')).toBe(false);
    await expect(s.session.setCamera(true)).rejects.toThrow('camera_requires_reconnect');
    expect(s.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it('captures the selected camera through a two-frame-per-second canvas and stops its animation loop', async () => {
    const s = setup({ defaultVideoPipeline: true });
    const outboundCamera = track('video');
    const outboundStream = mediaStream([], [outboundCamera]);
    const drawImage = vi.fn();
    const callbacks: FrameRequestCallback[] = [];
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      callbacks.push(callback);
      return 73;
    });
    const cancelFrame = vi.fn();
    const originalCapture = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'captureStream');
    const captureStream = vi.fn((_fps: number) => outboundStream);
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage } as any);
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
    Object.defineProperty(HTMLCanvasElement.prototype, 'captureStream', {
      configurable: true, value: captureStream,
    });
    vi.stubGlobal('requestAnimationFrame', requestFrame);
    vi.stubGlobal('cancelAnimationFrame', cancelFrame);

    try {
      s.session.chooseCamera(true);
      await s.session.start();
      expect(captureStream).toHaveBeenCalledWith(2);
      expect(s.pc.added.map((entry) => entry.track.kind)).toEqual(['audio', 'video']);
      callbacks[0]?.(0);
      expect(drawImage).toHaveBeenCalledOnce();
      await s.session.setCamera(false);
      expect(cancelFrame).toHaveBeenCalledWith(73);
      expect(outboundCamera.stop).toHaveBeenCalledOnce();
    } finally {
      await s.session.end();
      if (originalCapture) Object.defineProperty(HTMLCanvasElement.prototype, 'captureStream', originalCapture);
      else delete (HTMLCanvasElement.prototype as any).captureStream;
    }
  });

  it('persists final transcript and preliminary usage events from the provider channel', async () => {
    const s = setup();
    await s.session.start();
    s.pc.channel.emit({
      type: 'conversation.item.input_audio_transcription.completed',
      event_id: 'evt-user', item_id: 'item-user', transcript: 'Найди расписание.',
    });
    s.pc.channel.emit({
      type: 'response.done', response: { id: 'r-1', usage: { total_tokens: 12, input_tokens: 8, output_tokens: 4 } },
    });
    await s.session.whenProviderEventsIdle();

    expect(s.api.event).toHaveBeenCalledWith('call-1', expect.objectContaining({ type: 'conversation.item.input_audio_transcription.completed' }));
    expect(s.api.event).toHaveBeenCalledWith('call-1', expect.objectContaining({ type: 'response.done' }));
    expect(s.transcripts).toEqual([{ role: 'user', text: 'Найди расписание.' }]);
  });

  it('executes a Qwen web tool through Quip then returns the documented function output', async () => {
    const s = setup();
    await s.session.start();
    s.pc.channel.emit({ type: 'session.created', session: {} });
    s.pc.connect();
    await s.session.whenProviderEventsIdle();
    s.pc.channel.emit({ type: 'response.created', response: { id: 'response-1' } });
    await s.session.whenProviderEventsIdle();
    s.pc.channel.emit({
      type: 'function_call_arguments.done',
      call_id: 'function-1', name: 'web_search', arguments: '{"query":"музей сегодня"}',
    });
    await vi.waitFor(() => expect(s.api.tool).toHaveBeenCalled());
    await s.session.whenProviderEventsIdle();

    expect(s.api.tool).toHaveBeenCalledWith('call-1', 'function-1', 'web_search', '{"query":"музей сегодня"}', expect.any(AbortSignal));
    expect(s.pc.channel.sent).toContainEqual({
      type: 'conversation.item.create',
      item: { type: 'function_call_output', call_id: 'function-1', output: '{"results":[]}' },
    });
    expect(s.pc.channel.sent).toContainEqual({ type: 'response.create' });
  });

  it('speech interruption cancels Qwen output and the pending web tool without resuming stale speech', async () => {
    let finishTool!: (value: any) => void;
    const s = setup();
    vi.mocked(s.api.tool).mockReturnValueOnce(new Promise((resolve) => { finishTool = resolve; }));
    await s.session.start();
    s.pc.channel.emit({ type: 'session.created', session: {} });
    s.pc.connect();
    await s.session.whenProviderEventsIdle();
    s.pc.channel.emit({ type: 'response.created', response: { id: 'response-pending' } });
    await s.session.whenProviderEventsIdle();
    s.pc.channel.emit({
      type: 'function_call_arguments.done',
      call_id: 'function-pending', name: 'web_search', arguments: '{"query":"test"}',
    });
    await vi.waitFor(() => expect(s.api.tool).toHaveBeenCalled());
    s.session.interruptSpeech();
    expect(s.pc.channel.sent).toContainEqual({ type: 'response.cancel' });
    expect(s.api.cancelTool).toHaveBeenCalledWith('call-1', 'function-pending');
    finishTool({ provider_call_id: 'function-pending', name: 'web_search', status: 'completed', result: { results: [] }, replayed: false });
    await s.session.whenProviderEventsIdle();

    expect(s.api.end).not.toHaveBeenCalled();
    expect(s.pc.channel.sent.filter((event: any) => event.type === 'conversation.item.create')).toHaveLength(0);
    expect(s.pc.channel.sent.filter((event: any) => event.type === 'response.create')).toHaveLength(0);
  });

  it('delegates one bounded task to Luna, keeps it after voice interruption, and returns its result after Qwen finishes', async () => {
    const s = setup();
    vi.mocked(s.api.task).mockResolvedValueOnce({
      task_id: 'task-1', chat_id: 'chat-1', status: 'completed', revision: 2, context_version: 1,
      task_kind: 'voice_delegation', cancel_requested: false, snapshot: { phase: 'completed' }, error: null,
      message: { id: 'message-1', content: 'Проверил источники: результат готов.', artifacts: [] },
    });
    await s.session.start();
    s.pc.channel.emit({ type: 'session.created', session: {} });
    s.pc.connect();
    await s.session.whenProviderEventsIdle();
    s.pc.channel.emit({ type: 'response.created', response: { id: 'response-1' } });
    await s.session.whenProviderEventsIdle();
    s.pc.channel.emit({
      type: 'function_call_arguments.done', call_id: 'delegate-1', name: 'delegate_to_text_model',
      arguments: '{"goal":"Найди свежие источники"}',
    });
    await vi.waitFor(() => expect(s.api.startTask).toHaveBeenCalledWith('call-1', 'delegate-1', 'Найди свежие источники'));
    await s.session.whenProviderEventsIdle();
    s.session.interruptSpeech();
    await vi.waitFor(() => expect(s.session.state.task?.status).toBe('completed'));

    expect(s.api.cancelTask).not.toHaveBeenCalled();
    expect(s.pc.channel.sent.filter((event: any) => event.type === 'session.update')).toHaveLength(1);
    s.pc.channel.emit({ type: 'response.done', response: { id: 'response-1' } });
    await s.session.whenProviderEventsIdle();

    const updates = s.pc.channel.sent.filter((event: any) => event.type === 'session.update') as any[];
    expect(updates.at(-1).session.instructions).toContain('Проверил источники: результат готов.');
    expect(s.pc.channel.sent.filter((event: any) => event.type === 'response.create')).toHaveLength(2);
    expect(s.pc.channel.sent.filter((event: any) => event.type === 'conversation.item.create'))
      .toContainEqual(expect.objectContaining({ item: expect.objectContaining({ call_id: 'delegate-1' }) }));
  });

  it('keeps only the latest bounded Luna result in Qwen session instructions', async () => {
    const s = setup();
    vi.mocked(s.api.startTask)
      .mockResolvedValueOnce({ task_id: 'task-1', status: 'queued', model: 'openrouter/luna-max', replayed: false, steered: false })
      .mockResolvedValueOnce({ task_id: 'task-2', status: 'queued', model: 'openrouter/luna-max', replayed: false, steered: false });
    vi.mocked(s.api.task)
      .mockResolvedValueOnce({
        task_id: 'task-1', chat_id: 'chat-1', status: 'completed', revision: 1, context_version: 1,
        task_kind: 'voice_delegation', cancel_requested: false, snapshot: {}, error: null,
        message: { id: 'message-1', content: 'FIRST_DELEGATION_RESULT', artifacts: [] },
      })
      .mockResolvedValueOnce({
        task_id: 'task-2', chat_id: 'chat-1', status: 'completed', revision: 1, context_version: 1,
        task_kind: 'voice_delegation', cancel_requested: false, snapshot: {}, error: null,
        message: { id: 'message-2', content: 'SECOND_DELEGATION_RESULT', artifacts: [] },
      });
    await s.session.start();
    s.pc.channel.emit({ type: 'session.created', session: {} });
    s.pc.connect();
    await s.session.whenProviderEventsIdle();

    const delegate = async (callId: string, goal: string) => {
      s.pc.channel.emit({
        type: 'function_call_arguments.done', call_id: callId, name: 'delegate_to_text_model',
        arguments: JSON.stringify({ goal }),
      });
      await vi.waitFor(() => expect(s.api.startTask).toHaveBeenCalledTimes(callId === 'delegate-1' ? 1 : 2));
      await s.session.whenProviderEventsIdle();
      await vi.waitFor(() => expect(s.session.state.task?.status).toBe('completed'));
      s.pc.channel.emit({ type: 'response.done', response: { id: `response-${callId}` } });
      await s.session.whenProviderEventsIdle();
      const updates = s.pc.channel.sent.filter((event: any) => event.type === 'session.update') as any[];
      return updates.at(-1).session.instructions as string;
    };

    const firstInstructions = await delegate('delegate-1', 'First task');
    const secondInstructions = await delegate('delegate-2', 'Second task');

    expect(firstInstructions).toContain('FIRST_DELEGATION_RESULT');
    expect(secondInstructions).toContain('SECOND_DELEGATION_RESULT');
    expect(secondInstructions).not.toContain('FIRST_DELEGATION_RESULT');
  });

  it('keeps an active delegated task reachable after ending the call panel session', async () => {
    const s = setup();
    await s.session.start();
    s.pc.channel.emit({ type: 'session.created', session: {} });
    s.pc.connect();
    await s.session.whenProviderEventsIdle();
    s.pc.channel.emit({
      type: 'function_call_arguments.done', call_id: 'delegate-after-call',
      name: 'delegate_to_text_model', arguments: '{"goal":"Сверь источники"}',
    });
    await vi.waitFor(() => expect(s.api.startTask).toHaveBeenCalled());
    await s.session.whenProviderEventsIdle();
    await s.session.end({ keepTaskVisible: true });

    expect(s.api.cancelTask).not.toHaveBeenCalled();
    await s.session.cancelTask();
    expect(s.api.cancelTask).toHaveBeenCalledWith('call-1', 'task-1');
  });

  it('mutes the audio track and stops all local tracks, channel, peer and backend call on end', async () => {
    const s = setup();
    s.session.chooseCamera(true);
    await s.session.start();
    s.session.mute(true);
    expect(s.mic.enabled).toBe(false);
    await s.session.end();

    expect(s.mic.stop).toHaveBeenCalledOnce();
    expect(s.camera.stop).toHaveBeenCalledOnce();
    expect(s.outboundCamera.stop).toHaveBeenCalledOnce();
    expect(s.disposeVideoPipeline).toHaveBeenCalledOnce();
    expect(s.pc.channel.close).toHaveBeenCalledOnce();
    expect(s.pc.close).toHaveBeenCalledOnce();
    expect(s.api.end).toHaveBeenCalledWith('call-1');
    expect(s.session.state.status).toBe('ended');
    expect(s.tones.oscillator.stop).toHaveBeenCalled();
  });

  it('surfaces a provider connection failure and releases tracks and ringback', async () => {
    const s = setup();
    await s.session.start();
    s.pc.fail();
    await Promise.resolve();

    expect(s.session.state.status).toBe('error');
    expect(s.session.state.error).toBe('connection_failed');
    expect(s.mic.stop).toHaveBeenCalledOnce();
    expect(s.tones.oscillator.stop).toHaveBeenCalled();
  });
});
