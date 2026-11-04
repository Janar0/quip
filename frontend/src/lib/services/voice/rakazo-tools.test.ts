import { describe, expect, it, vi } from 'vitest';
import { providerSessionConfiguration } from './provider-protocol';
import { VoiceToolExecutor } from './provider-tools';
import type { VoiceSessionApi } from './types';

const api = { tool: vi.fn(), startTask: vi.fn() } as unknown as VoiceSessionApi;
const run = (executor: VoiceToolExecutor, name: string, args: string) =>
  executor.invoke('k', 'call-1', 'p1', name, args, () => true, () => {}).then((output) => JSON.parse(output!));

describe('Rakazo voice tools', () => {
  it('are offered to the voice model only when Rakazo is configured', () => {
    const names = (rakazo: boolean) =>
      (providerSessionConfiguration('x', false, rakazo).tools as Array<{ function: { name: string } }>).map(
        (tool) => tool.function.name,
      );
    expect(names(true)).toEqual(expect.arrayContaining(['ask_rakazo', 'rakazo_reply']));
    expect(names(false)).not.toContain('ask_rakazo');
    expect(names(false)).not.toContain('rakazo_reply');
  });

  it('hand the task to the Rakazo bot and return its answer', async () => {
    const rakazo = { ask: vi.fn().mockResolvedValue({ reply: 'Готово' }), latest: vi.fn(), dispose: vi.fn() };
    const executor = new VoiceToolExecutor(api, rakazo);
    await expect(run(executor, 'ask_rakazo', JSON.stringify({ task: '  построй график  ' }))).resolves.toEqual({
      reply: 'Готово',
    });
    expect(rakazo.ask).toHaveBeenCalledWith('построй график');
  });

  it('check the latest reply', async () => {
    const rakazo = { ask: vi.fn(), latest: vi.fn().mockResolvedValue({ status: 'working' }), dispose: vi.fn() };
    const executor = new VoiceToolExecutor(api, rakazo);
    const output = await run(executor, 'rakazo_reply', '{}');
    expect(output.status).toBe('working');
  });

  it.each(['{}', '{"task":""}', JSON.stringify({ task: 'x'.repeat(2001) }), 'not json', '{"task":"a","other":1}'])(
    'refuse a malformed task %s',
    async (args) => {
      const rakazo = { ask: vi.fn(), latest: vi.fn(), dispose: vi.fn() };
      const executor = new VoiceToolExecutor(api, rakazo);
      await expect(run(executor, 'ask_rakazo', args)).resolves.toEqual({ error: 'invalid_task' });
      expect(rakazo.ask).not.toHaveBeenCalled();
    },
  );

  it('report a Rakazo failure without throwing', async () => {
    const rakazo = { ask: vi.fn().mockRejectedValue(new Error('down')), latest: vi.fn(), dispose: vi.fn() };
    const executor = new VoiceToolExecutor(api, rakazo);
    await expect(run(executor, 'ask_rakazo', '{"task":"x"}')).resolves.toEqual({ error: 'rakazo_failed' });
  });

  it('are unsupported without Rakazo', async () => {
    const executor = new VoiceToolExecutor(api);
    await expect(run(executor, 'ask_rakazo', '{"task":"x"}')).resolves.toEqual({ error: 'unsupported_tool' });
  });
});
