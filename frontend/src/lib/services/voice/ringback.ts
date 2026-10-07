export class Ringback {
  private audioContext: AudioContext | null = null;
  private ringbackNodes: OscillatorNode[] = [];
  private ringbackGain: GainNode | null = null;
  private ringbackTimer: ReturnType<typeof setInterval> | null = null;
  constructor(private createAudioContext?: () => AudioContext, private intervalMs?: number) {}

  prime(): void {
    try {
      const create = this.createAudioContext ?? (() => new AudioContext());
      this.audioContext = create();
      void this.audioContext.resume().catch(() => {});
    } catch {
      this.audioContext = null;
    }
  }

  start(): void {
    const context = this.audioContext;
    if (!context || this.ringbackNodes.length) return;
    try {
      const gain = context.createGain();
      gain.gain.value = 0;
      gain.connect(context.destination);
      const oscillators = [440, 480].map((frequency) => {
        const node = context.createOscillator();
        node.type = 'sine';
        node.frequency.value = frequency;
        node.connect(gain);
        node.start();
        return node;
      });
      this.ringbackGain = gain;
      this.ringbackNodes = oscillators;
      let ringing = true;
      const setLevel = (value: number) => gain.gain.setValueAtTime(value, context.currentTime);
      setLevel(0.025);
      this.ringbackTimer = setInterval(() => {
        ringing = !ringing;
        setLevel(ringing ? 0.025 : 0);
      }, this.intervalMs ?? 2_000);
    } catch {
      this.stop();
    }
  }

  stop(): void {
    if (this.ringbackTimer) clearInterval(this.ringbackTimer);
    this.ringbackTimer = null;
    for (const node of this.ringbackNodes) {
      try { node.stop(); } catch { /* already stopped */ }
      try { node.disconnect(); } catch { /* already disconnected */ }
    }
    this.ringbackNodes = [];
    try { this.ringbackGain?.disconnect(); } catch { /* already disconnected */ }
    this.ringbackGain = null;
  }

  async close(): Promise<void> {
    this.stop();
    const context = this.audioContext;
    this.audioContext = null;
    if (context && context.state !== 'closed') {
      try { await context.close(); } catch { /* optional local ringback context */ }
    }
  }
}
