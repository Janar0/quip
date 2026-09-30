import { beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { api } from './client';
import { updateStreamingContent } from './chat-stream';
import { abortController, activeChat, chatList, isStreaming, messages } from '$lib/stores/chat';
import { loadChat, stopGeneration, stopResearchPolling, streamChat } from './chats';

vi.mock('./client', () => ({ api: vi.fn() }));
const request = vi.mocked(api);

beforeEach(() => {
  stopResearchPolling();
  request.mockReset();
  messages.set([]);
  activeChat.set(null);
  chatList.set([]);
  isStreaming.set(false);
  abortController.set(null);
});

it('ordinary chat Stop aborts its stream even when an older Research run is active', async () => {
  messages.set([{
    id: 'older-research',
    chat_id: 'chat',
    role: 'assistant',
    content: 'Background report',
    created_at: '',
    research: {
      runId: 'background-run',
      status: 'running',
      revision: 1,
      contextVersion: 1,
      cancelRequested: false,
      snapshot: {},
    },
  }]);
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  let signal: AbortSignal | undefined;
  const body = new ReadableStream<Uint8Array>({
    start(streamController) { controller = streamController; },
  });
  request.mockImplementation(async (path, init) => {
    if (path === '/api/chat/completions') {
      signal = init?.signal as AbortSignal;
      return new Response(body);
    }
    if (path.endsWith('/cancel')) {
      return Response.json({
        accepted: true,
        run: {
          run_id: 'ordinary-run', status: 'cancelling', revision: 1,
          context_version: 1, cancel_requested: true, snapshot: {},
        },
      });
    }
    return Response.json([]);
  });

  const sending = streamChat('Hello', 'chat');
  controller.enqueue(new TextEncoder().encode(
    'event: chat\ndata: {"chat_id":"chat","user_message_id":"user","message_id":"answer","run_id":"ordinary-run","task_kind":"chat"}\n\n',
  ));
  await vi.waitFor(() => expect(get(messages).some((message) => message.id === 'answer')).toBe(true));

  await stopGeneration();
  const calls = request.mock.calls.map(([path]) => path);
  controller.close();
  await sending;
  stopResearchPolling();

  expect(signal?.aborted).toBe(true);
  expect(calls.some((path) => path.endsWith('/cancel'))).toBe(false);
});

it('polling replaces streamed partial text with the terminal saved report after disconnect', async () => {
  vi.useFakeTimers();
  try {
    request.mockResolvedValueOnce(Response.json({
      id: 'chat',
      messages: [{ id: 'answer', chat_id: 'chat', role: 'assistant', content: 'Saved draft', created_at: '' }],
      runs: [{ id: 'run', assistant_message_id: 'answer', status: 'running', task_kind: 'research' }],
    }));
    request.mockResolvedValueOnce(Response.json({
      run_id: 'run', status: 'running', revision: 1, context_version: 1, cancel_requested: false,
      snapshot: {}, message: { id: 'answer', content: 'Saved draft', artifacts: [] },
    }));
    await loadChat('chat');
    isStreaming.set(true);
    updateStreamingContent('answer', 'Saved draft plus SSE delta');
    isStreaming.set(false);
    request.mockResolvedValueOnce(Response.json({
      run_id: 'run', status: 'completed', revision: 2, context_version: 1, cancel_requested: false,
      snapshot: {}, message: { id: 'answer', content: 'Complete saved report after disconnect', artifacts: [] },
    }));

    await vi.advanceTimersByTimeAsync(2500);

    expect(get(messages)[0].content).toBe('Complete saved report after disconnect');
  } finally {
    stopResearchPolling();
    vi.useRealTimers();
  }
});

it('polling preserves a local text edit when the run reaches a terminal state', async () => {
  vi.useFakeTimers();
  try {
    request.mockResolvedValueOnce(Response.json({
      id: 'chat',
      messages: [{ id: 'answer', chat_id: 'chat', role: 'assistant', content: 'Saved draft', created_at: '' }],
      runs: [{ id: 'run', assistant_message_id: 'answer', status: 'running', task_kind: 'research' }],
    }));
    request.mockResolvedValueOnce(Response.json({
      run_id: 'run', status: 'running', revision: 1, context_version: 1, cancel_requested: false,
      snapshot: {}, message: { id: 'answer', content: 'Saved draft', artifacts: [] },
    }));
    await loadChat('chat');
    messages.update((items) => items.map((message) => message.id === 'answer'
      ? { ...message, content: 'Locally edited report' }
      : message));
    request.mockResolvedValueOnce(Response.json({
      run_id: 'run', status: 'completed', revision: 2, context_version: 1, cancel_requested: false,
      snapshot: {}, message: { id: 'answer', content: 'Final saved report', artifacts: [] },
    }));

    await vi.advanceTimersByTimeAsync(2500);

    expect(get(messages)[0].content).toBe('Locally edited report');
    expect(get(messages)[0].research?.status).toBe('completed');
  } finally {
    stopResearchPolling();
    vi.useRealTimers();
  }
});
