import { writable } from 'svelte/store';

/**
 * Rakazo is an unmodified upstream install on its own origin, embedded in Quip and
 * signed in through Quip's OpenID Connect provider. An empty address keeps it hidden.
 */
export const rakazoUrl = writable('');

/** The embedded page signs in and then opens Rakazo. A fragment never reaches a server. */
export function rakazoEntry(url: string, email: string, theme: string): string {
  return `${url}/quip/entry#${new URLSearchParams({ email, theme })}`;
}

/** Only an address on this site may follow a login; browsers normalize the rest. */
export function safeNext(next: string | null | undefined, origin: string): string | null {
  if (!next) return null;
  try {
    const url = new URL(next, origin);
    return url.origin === origin ? `${url.pathname}${url.search}${url.hash}` : null;
  } catch {
    return null;
  }
}

/** Signing out of Quip must not leave the Rakazo session behind on a shared device. */
export function endRakazoSession(url: string, timeoutMs = 3000): Promise<void> {
  return new Promise((resolve) => {
    const frame = document.createElement('iframe');
    frame.hidden = true;
    frame.src = `${url}/quip/signout`;
    const finish = () => {
      clearTimeout(timer);
      window.removeEventListener('message', onMessage);
      frame.remove();
      resolve();
    };
    const onMessage = (event: MessageEvent) => {
      if (event.origin === url && event.data === 'rakazo-signed-out') finish();
    };
    const timer = setTimeout(finish, timeoutMs);
    window.addEventListener('message', onMessage);
    document.body.append(frame);
  });
}

export type RakazoAnswer = { reply: string } | { status: 'working' | 'no_task' };

/** What a voice call needs from the person's Rakazo bot. */
export interface RakazoVoice {
  ask(task: string): Promise<RakazoAnswer>;
  latest(): Promise<RakazoAnswer>;
  dispose(): void;
}

type BridgeOptions = { waitMs?: number; pollMs?: number; requestTimeoutMs?: number };
type Target = { botId: string; space: string; after: number };

/**
 * Talks to the person's Rakazo bot through a hidden page on Rakazo's own origin, which uses their
 * Rakazo session there; Quip never sees it. That page answers only Quip, its only allowed parent.
 */
export class RakazoBridge implements RakazoVoice {
  private readonly frame: HTMLIFrameElement;
  private readonly ready: Promise<void>;
  private markReady!: () => void;
  private readonly pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }>();
  private nextId = 1;
  private target: Target | null = null;
  private readonly waitMs: number;
  private readonly pollMs: number;
  private readonly requestTimeoutMs: number;

  constructor(private readonly url: string, options: BridgeOptions = {}) {
    this.waitMs = options.waitMs ?? 45_000;
    this.pollMs = options.pollMs ?? 2_000;
    this.requestTimeoutMs = options.requestTimeoutMs ?? 20_000;
    this.ready = new Promise((resolve) => (this.markReady = resolve));
    this.frame = document.createElement('iframe');
    this.frame.hidden = true;
    this.frame.src = `${url}/quip/bridge`;
    window.addEventListener('message', this.onMessage);
    document.body.append(this.frame);
  }

  private onMessage = (event: MessageEvent) => {
    if (event.origin !== this.url || event.source !== this.frame.contentWindow) return;
    const data = event.data;
    if (data?.type === 'rakazo-bridge-ready') return this.markReady();
    const waiting = this.pending.get(data?.id);
    if (!waiting) return;
    this.pending.delete(data.id);
    if (data.ok) waiting.resolve(data.result);
    else waiting.reject(new Error(String(data.error ?? 'rakazo_failed')));
  };

  private async request<T>(op: 'ask' | 'replies', input: Record<string, unknown>): Promise<T> {
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('rakazo_unavailable'));
      }, this.requestTimeoutMs);
      const settle = <V>(done: (value: V) => void) => (value: V) => {
        clearTimeout(timer);
        done(value);
      };
      this.pending.set(id, { resolve: settle(resolve), reject: settle(reject) });
      void this.ready.then(() => this.frame.contentWindow?.postMessage({ id, op, input }, this.url));
    });
  }

  private async waitForReply(deadline: number): Promise<RakazoAnswer> {
    for (;;) {
      const target = this.target!;
      const page = await this.request<{ texts: string[]; seq: number }>('replies', { ...target });
      target.after = Math.max(target.after, page.seq);
      if (page.texts.length) return { reply: page.texts.join('\n\n') };
      if (Date.now() + this.pollMs > deadline) return { status: 'working' };
      await new Promise((resolve) => setTimeout(resolve, this.pollMs));
    }
  }

  async ask(task: string): Promise<RakazoAnswer> {
    const sent = await this.request<{ botId: string; space: string; seq: number }>('ask', { text: task });
    this.target = { botId: sent.botId, space: sent.space, after: sent.seq };
    return this.waitForReply(Date.now() + this.waitMs);
  }

  async latest(): Promise<RakazoAnswer> {
    if (!this.target) return { status: 'no_task' };
    return this.waitForReply(Date.now() + this.pollMs);
  }

  dispose(): void {
    window.removeEventListener('message', this.onMessage);
    for (const waiting of this.pending.values()) waiting.reject(new Error('rakazo_unavailable'));
    this.pending.clear();
    this.frame.remove();
  }
}
