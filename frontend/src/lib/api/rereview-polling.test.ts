import { beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { api } from './client';
import { updateStreamingContent } from './chat-stream';
import { abortController, activeChat, chatList, isStreaming, messages } from '$lib/stores/chat';
import { loadChat, stopResearchPolling, streamChat } from './chats';

vi.mock('./client', () => ({ api: vi.fn() }));
const request = vi.mocked(api);
beforeEach(() => {
  stopResearchPolling(); request.mockReset(); messages.set([]); activeChat.set(null); chatList.set([]);
  isStreaming.set(false); abortController.set(null);
});

async function loadRunningReport() {
  request.mockResolvedValueOnce(Response.json({
    id: 'chat', messages: [{ id: 'answer', chat_id: 'chat', role: 'assistant', content: 'Saved draft', created_at: '' }],
    runs: [{ id: 'run', assistant_message_id: 'answer', status: 'running', task_kind: 'research' }],
  }));
  request.mockResolvedValueOnce(Response.json({
    run_id: 'run', status: 'running', revision: 1, context_version: 1, cancel_requested: false,
    snapshot: {}, message: { id: 'answer', content: 'Saved draft', artifacts: [] },
  }));
  await loadChat('chat');
}

it('polling advances known streamed text after disconnect while Research continues running', async () => {
  vi.useFakeTimers();
  try {
    await loadRunningReport();
    isStreaming.set(true); updateStreamingContent('answer', 'Saved draft plus SSE delta'); isStreaming.set(false);
    request.mockResolvedValueOnce(Response.json({
      run_id: 'run', status: 'running', revision: 2, context_version: 1, cancel_requested: false,
      snapshot: {}, message: { id: 'answer', content: 'New saved text after disconnect', artifacts: [] },
    }));
    await vi.advanceTimersByTimeAsync(2500);
    expect(get(messages)[0].content).toBe('New saved text after disconnect');
  } finally { stopResearchPolling(); vi.useRealTimers(); }
});

it('terminal Research result eventually appears when an unrelated ordinary stream finishes', async () => {
  vi.useFakeTimers();
  let streamController!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(controller) { streamController = controller; },
  });
  try {
    await loadRunningReport();
    request.mockImplementation(async (path) => {
      if (path === '/api/chat/completions') {
        return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
      }
      if (path.endsWith('/runs/run')) {
        return Response.json({
          run_id: 'run', status: 'completed', revision: 2, context_version: 1, cancel_requested: false,
          snapshot: {}, message: { id: 'answer', content: 'Final durable report', artifacts: [] },
        });
      }
      return Response.json([]);
    });
    const ordinaryStream = streamChat('A normal chat message', 'chat');
    streamController.enqueue(new TextEncoder().encode(
      'event: chat\ndata: {"chat_id":"chat","user_message_id":"ordinary-user","message_id":"ordinary-answer","task_kind":"chat"}\n\n',
    ));
    await vi.waitFor(() => expect(get(messages).some((message) => message.id === 'ordinary-answer')).toBe(true));
    expect(get(isStreaming)).toBe(true);

    await vi.advanceTimersByTimeAsync(2500);
    expect(get(messages)[0].content).toBe('Final durable report');
    expect(get(isStreaming)).toBe(true);

    streamController.close();
    await ordinaryStream;
  } finally { stopResearchPolling(); vi.useRealTimers(); }
});

it('applies the latest persisted report after its own Research stream disconnects', async () => {
  vi.useFakeTimers();
  let streamController!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(controller) { streamController = controller; },
  });
  try {
    request.mockResolvedValueOnce(Response.json({ id: 'chat', messages: [], runs: [] }));
    await loadChat('chat');
    request.mockImplementation(async (path) => {
      if (path === '/api/chat/completions') {
        return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
      }
      if (path.endsWith('/runs/run')) {
        return Response.json({
          run_id: 'run', status: 'running', revision: 2, context_version: 1, cancel_requested: false,
          snapshot: {}, message: { id: 'answer', content: 'Latest persisted Research draft', artifacts: [] },
        });
      }
      return Response.json([]);
    });

    const researchStream = streamChat('Research this', 'chat', undefined, undefined, undefined, undefined, 'research');
    streamController.enqueue(new TextEncoder().encode([
      'event: chat\ndata: {"chat_id":"chat","user_message_id":"user","message_id":"answer","run_id":"run","task_kind":"research"}\n\n',
      'event: content\ndata: {"text":"Current live Research text"}\n\n',
    ].join('')));
    await vi.waitFor(() => expect(get(messages).find((message) => message.id === 'answer')?.content)
      .toBe('Current live Research text'));

    await vi.advanceTimersByTimeAsync(2500);
    expect(get(messages).find((message) => message.id === 'answer')?.content).toBe('Current live Research text');
    expect(get(messages).find((message) => message.id === 'answer')?.research?.message?.content)
      .toBe('Latest persisted Research draft');

    streamController.close();
    await researchStream;
    expect(get(messages).find((message) => message.id === 'answer')?.content)
      .toBe('Latest persisted Research draft');
  } finally {
    stopResearchPolling();
    vi.useRealTimers();
  }
});
