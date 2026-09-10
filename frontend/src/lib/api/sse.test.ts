import { describe, expect, it } from 'vitest';
import { readSSE } from './sse';

export function responseFrom(text: string, size = 1): Response {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({
    start(controller) {
      for (let i = 0; i < bytes.length; i += size) controller.enqueue(bytes.slice(i, i + size));
      controller.close();
    },
  }));
}

describe('SSE framing', () => {
  it('preserves UTF-8, CRLF and multiline data across byte boundaries', async () => {
    const response = responseFrom(': heartbeat\r\nevent:content\r\ndata:Привет\r\ndata:мир\r\n\r\ndata:next\n\n');
    expect(await Array.fromAsync(readSSE(response))).toEqual([
      { event: 'content', data: 'Привет\nмир' }, { event: 'message', data: 'next' },
    ]);
    expect(response.body?.locked).toBe(false);
  });
  it('keeps a final event without trailing newline', async () => {
    expect(await Array.fromAsync(readSSE(responseFrom('event: error\ndata:failed')))).toEqual([
      { event: 'error', data: 'failed' },
    ]);
  });
  it('reports a missing body', async () => {
    await expect(Array.fromAsync(readSSE(new Response(null)))).rejects.toThrow('empty response');
  });
});
