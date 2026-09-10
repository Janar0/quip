import { beforeEach, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { messages } from '$lib/stores/chat';
import { processSSEStream } from './chat-stream';

beforeEach(() => messages.set([{
  id: 'streaming', chat_id: '', role: 'assistant', content: '', created_at: '',
}]));

function events(items: [string, unknown][]) {
  return new Response(items.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''));
}

it('keeps partial output and exposes errors even with content blocks and real IDs', async () => {
  const ids = await processSSEStream(events([
    ['chat', { chat_id: 'chat', message_id: 'real-id' }],
    ['content', { text: 'Useful partial answer' }],
    ['error', { message: 'DNS failed' }],
  ]));
  expect(ids.messageId).toBe('real-id');
  expect(get(messages)[0]).toMatchObject({
    content: 'Useful partial answer', error: 'DNS failed',
    contentBlocks: [{ type: 'text', content: 'Useful partial answer' }],
  });
});

it('supports backend error payloads using the error field', async () => {
  await processSSEStream(events([['error', { error: 'Generation failed' }]]));
  expect(get(messages)[0].error).toBe('Generation failed');
});

it('makes malformed events visible instead of silently discarding them', async () => {
  await processSSEStream(new Response('event: content\ndata: {invalid}\n\n'));
  expect(get(messages)[0].error).toBeTruthy();
});
