import { beforeEach, expect, it, vi } from 'vitest';
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

it('keeps research progress, sources, terminal status, and early chat identity', async () => {
  const onChatReady = vi.fn();
  await processSSEStream(events([
    ['chat', { chat_id: 'research-chat', user_message_id: 'user', message_id: 'answer', run_id: 'run-1' }],
    ['status', { phase: 'searching', detail: 'Mock retrieval', sub_queries: ['topic'] }],
    ['sources', { sources: [{ title: 'Example', url: 'https://example.org/source' }] }],
    ['content', { text: 'Report text with [1] citation.' }],
    ['run_status', { status: 'partial', error: 'One agent failed' }],
  ]), onChatReady);

  expect(onChatReady).toHaveBeenCalledWith({
    chatId: 'research-chat', userMessageId: 'user', messageId: 'answer', runId: 'run-1',
  });
  expect(get(messages).find((message) => message.id === 'answer')).toMatchObject({
    content: 'Report text with [1] citation.',
    research: {
      runId: 'run-1', status: 'partial', error: 'One agent failed',
      snapshot: {
        progress: [{ phase: 'searching', detail: 'Mock retrieval', sub_queries: ['topic'] }],
        sources: [{ title: 'Example', url: 'https://example.org/source' }],
      },
    },
  });
});

it('replaces optimistic research progress with the authoritative persisted snapshot', async () => {
  await processSSEStream(events([
    ['chat', { chat_id: 'research-chat', message_id: 'answer', run_id: 'run-1' }],
    ['status', { phase: 'searching', detail: 'Live status' }],
    ['research_snapshot', {
      snapshot: {
        progress: [{ phase: 'synthesizing', detail: 'Saved status' }],
        sources: [{ title: 'Kept URL', url: 'https://example.org/full-path' }],
        truncated: true,
      },
    }],
  ]));

  expect(get(messages).find((message) => message.id === 'answer')?.research?.snapshot).toEqual({
    progress: [{ phase: 'synthesizing', detail: 'Saved status' }],
    sources: [{ title: 'Kept URL', url: 'https://example.org/full-path' }],
    truncated: true,
  });
});
