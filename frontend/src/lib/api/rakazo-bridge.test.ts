import { afterEach, describe, expect, it, vi } from 'vitest';
import { RakazoBridge } from './rakazo';

const RAKAZO = 'https://rakazo.example.test';

function setup(options = {}) {
  const bridge = new RakazoBridge(RAKAZO, { waitMs: 10_000, pollMs: 1_000, requestTimeoutMs: 5_000, ...options });
  const frame = document.querySelector('iframe')!;
  const target = frame.contentWindow!;
  const sent: Array<{ id: number; op: string; input: Record<string, unknown> }> = [];
  vi.spyOn(target, 'postMessage').mockImplementation((data: any) => sent.push(data));
  const reply = (data: unknown, origin = RAKAZO, source: MessageEventSource | null = target) =>
    window.dispatchEvent(new MessageEvent('message', { origin, source, data }));
  reply({ type: 'rakazo-bridge-ready' });
  return { bridge, frame, sent, reply };
}

const answer = async (sent: any[], reply: (d: unknown) => void, result: unknown) => {
  await vi.waitFor(() => expect(sent.length).toBeGreaterThan(0));
  const request = sent.shift();
  reply({ id: request.id, ok: true, result });
  return request;
};

afterEach(() => {
  vi.useRealTimers();
  document.querySelectorAll('iframe').forEach((frame) => frame.remove());
});

describe('RakazoBridge', () => {
  it('opens the bridge page of the configured Rakazo hidden', () => {
    setup();
    const frame = document.querySelector('iframe')!;
    expect(frame.getAttribute('src')).toBe(`${RAKAZO}/quip/bridge`);
    expect(frame.hidden).toBe(true);
  });

  it('gives the task to the bot and returns its reply', async () => {
    const { bridge, sent, reply } = setup({ pollMs: 1 });
    const result = bridge.ask('посчитай в Mathcad');
    const ask = await answer(sent, reply, { botId: 'b1', space: 's1', seq: 3 });
    expect(ask).toMatchObject({ op: 'ask', input: { text: 'посчитай в Mathcad' } });
    const first = await answer(sent, reply, { texts: [], seq: 3 });
    expect(first).toMatchObject({ op: 'replies', input: { botId: 'b1', space: 's1', after: 3 } });
    await answer(sent, reply, { texts: ['Готово: 25'], seq: 5 });
    await expect(result).resolves.toEqual({ reply: 'Готово: 25' });
  });

  it('says the bot is still working when no reply comes in time', async () => {
    vi.useFakeTimers();
    const { bridge, sent, reply } = setup({ waitMs: 3_000, pollMs: 1_000 });
    const result = bridge.ask('долгая задача');
    await answer(sent, reply, { botId: 'b1', space: 's1', seq: 0 });
    for (let i = 0; i < 4; i++) {
      await vi.advanceTimersByTimeAsync(0);
      if (sent.length) await answer(sent, reply, { texts: [], seq: 0 });
      await vi.advanceTimersByTimeAsync(1_000);
    }
    await expect(result).resolves.toEqual({ status: 'working' });
  });

  it('latest returns only what came after the reply already delivered', async () => {
    const { bridge, sent, reply } = setup({ pollMs: 1 });
    const first = bridge.ask('задача');
    await answer(sent, reply, { botId: 'b1', space: 's1', seq: 1 });
    await answer(sent, reply, { texts: ['первый ответ'], seq: 2 });
    await first;
    const later = bridge.latest();
    const request = await answer(sent, reply, { texts: ['итог'], seq: 4 });
    expect(request.input).toMatchObject({ after: 2 });
    await expect(later).resolves.toEqual({ reply: 'итог' });
  });

  it('has nothing to report before any task', async () => {
    const { bridge } = setup();
    await expect(bridge.latest()).resolves.toEqual({ status: 'no_task' });
  });

  it('ignores answers from another site or another window', async () => {
    vi.useFakeTimers();
    const { bridge, sent, reply } = setup({ requestTimeoutMs: 2_000 });
    const result = bridge.ask('задача').catch((error: Error) => error.message);
    await vi.advanceTimersByTimeAsync(0);
    const request = sent.shift()!;
    reply({ id: request.id, ok: true, result: { botId: 'x', space: 'x', seq: 0 } }, 'https://evil.example.test');
    reply({ id: request.id, ok: true, result: { botId: 'x', space: 'x', seq: 0 } }, RAKAZO, window);
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(result).resolves.toBe('rakazo_unavailable');
  });

  it('passes on the error Rakazo reported', async () => {
    const { bridge, sent, reply } = setup();
    const result = bridge.ask('задача');
    await vi.waitFor(() => expect(sent.length).toBe(1));
    reply({ id: sent[0].id, ok: false, error: 'Unauthorized' });
    await expect(result).rejects.toThrow('Unauthorized');
  });

  it('removes its frame when the call ends', () => {
    const { bridge } = setup();
    bridge.dispose();
    expect(document.querySelector('iframe')).toBeNull();
  });
});
