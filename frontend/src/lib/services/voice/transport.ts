import { FUNCTION_CALL_EVENT, normalizeProviderEvent, type ProviderEvent } from './provider-protocol';

type TransportEvents = {
  onEvent: (event: ProviderEvent) => Promise<void>;
  onUrgentEvent: (event: ProviderEvent) => void;
  onFunctionCall: (event: ProviderEvent) => Promise<void>;
  onError: (error: unknown) => Promise<void>;
  onFailure: (code: string) => Promise<void>;
  onClose: () => void;
  onOpen: () => void;
  onTrack: (event: RTCTrackEvent) => void;
  onConnectionChange: () => void;
};

/** One peer/channel and its event queue belong to one voice call. */
export class VoiceTransport {
  private closed = false;
  private channels = new Set<RTCDataChannel>();
  private cancelIceGathering: (() => void) | null = null;
  private channel: RTCDataChannel | null = null;
  private eventQueue: Promise<void> = Promise.resolve();
  private pendingHandlers = new Set<Promise<void>>();

  constructor(readonly peer: RTCPeerConnection, private events: TransportEvents) {}

  get isOpen(): boolean { return this.channel?.readyState === 'open'; }

  bind(): void {
    this.peer.ontrack = this.events.onTrack;
    this.peer.onconnectionstatechange = this.events.onConnectionChange;
    this.peer.ondatachannel = (event) => this.bindChannel(event.channel);
    this.bindChannel(this.peer.createDataChannel('qwen-events'));
  }

  private bindChannel(channel: RTCDataChannel): void {
    this.channel = channel;
    this.channels.add(channel);
    channel.onmessage = (event) => {
      if (this.closed) return;
      const parsed = normalizeProviderEvent(event.data);
      if (!parsed) return;
      this.events.onUrgentEvent(parsed);
      if (parsed.type === FUNCTION_CALL_EVENT) {
        let handler: Promise<void>;
        handler = this.events.onFunctionCall(parsed)
          .catch((error) => { if (!this.closed) return this.events.onError(error); })
          .finally(() => this.pendingHandlers.delete(handler));
        this.pendingHandlers.add(handler);
        return;
      }
      this.eventQueue = this.eventQueue
        .then(() => { if (!this.closed) return this.events.onEvent(parsed); })
        .catch((error) => { if (!this.closed) return this.events.onError(error); });
    };
    channel.onclose = this.events.onClose;
    if (channel.readyState === 'open') this.events.onOpen();
  }

  async whenIdle(): Promise<void> {
    while (true) {
      const queuedEvents = this.eventQueue;
      await queuedEvents;
      if (this.pendingHandlers.size) {
        await Promise.all([...this.pendingHandlers]);
        continue;
      }
      if (queuedEvents === this.eventQueue) return;
    }
  }

  async createOffer(isCurrent: () => boolean, timeoutMs = 20_000): Promise<string | null> {
    const offer = await this.peer.createOffer();
    if (!isCurrent()) return null;
    await this.peer.setLocalDescription(offer);
    if (!isCurrent()) return null;
    await this.waitForIceGathering(timeoutMs);
    if (!isCurrent()) return null;
    const sdp = this.peer.localDescription?.sdp;
    if (!sdp) throw new Error('provider_signaling_failed');
    return sdp;
  }

  acceptAnswer(sdp: string): Promise<void> {
    return this.peer.setRemoteDescription({ type: 'answer', sdp });
  }

  private async waitForIceGathering(timeoutMs: number): Promise<void> {
    if (this.peer.iceGatheringState === 'complete') return;
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => finish(new Error('ice_gathering_timeout')), timeoutMs);
      const onChange = () => {
        if (this.peer.iceGatheringState === 'complete') finish();
      };
      const finish = (error?: Error) => {
        clearTimeout(timeout);
        this.cancelIceGathering = null;
        this.peer.removeEventListener('icegatheringstatechange', onChange);
        if (error) reject(error);
        else resolve();
      };
      this.cancelIceGathering = () => finish();
      this.peer.addEventListener('icegatheringstatechange', onChange);
      onChange();
    });
  }

  send(event: Record<string, unknown>): void {
    if (!this.isOpen) return;
    try { this.channel!.send(JSON.stringify(event)); }
    catch { void this.events.onFailure('provider_channel_send_failed'); }
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.cancelIceGathering?.();
    for (const channel of this.channels) {
      channel.onmessage = null;
      channel.onclose = null;
      channel.close();
    }
    this.channels.clear();
    this.peer.ontrack = null;
    this.peer.onconnectionstatechange = null;
    this.peer.ondatachannel = null;
    this.peer.close();
    this.channel = null;
  }
}
