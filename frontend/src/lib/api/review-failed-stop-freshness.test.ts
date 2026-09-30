import { beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { api } from './client';
import { abortController, activeChat, chatList, isStreaming, messages } from '$lib/stores/chat';
import { loadChat, stopResearchPolling, stopResearchRun, streamChat } from './chats';

vi.mock('./client', () => ({ api: vi.fn() }));
const request = vi.mocked(api);
beforeEach(() => {
  stopResearchPolling();
  request.mockReset();
  messages.set([]);
  activeChat.set(null);
  chatList.set([]);
  isStreaming.set(false); abortController.set(null);
});

it('a failed Stop fallback received after SSE completion cannot overwrite the final report', async () => {
  vi.useFakeTimers();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
  let resolveRun!: (response: Response) => void;
  const pendingRun = new Promise<Response>((resolve) => { resolveRun = resolve; });
  const earlier = 'Earlier persisted draft';
  const final = `${earlier} plus the complete final report.`;
  try {
    request.mockResolvedValueOnce(Response.json({ id: 'chat', messages: [], runs: [] }));
    await loadChat('chat');
    request.mockImplementation(async (path) => {
      if (path === '/api/chat/completions') return new Response(body);
      if (path.endsWith('/runs/run/cancel')) {
        return Response.json({ detail: 'temporary Stop failure' }, { status: 503 });
      }
      if (path.endsWith('/runs/run')) return pendingRun;
      return Response.json([]);
    });
    const sending = streamChat('Research this', 'chat', undefined, undefined, undefined, undefined, 'research');
    controller.enqueue(new TextEncoder().encode([
      'event: chat\ndata: {"chat_id":"chat","user_message_id":"user","message_id":"answer","run_id":"run","task_kind":"research"}\n\n',
      `event: content\ndata: ${JSON.stringify({ text: earlier })}\n\n`,
    ].join('')));
    await vi.waitFor(() => expect(get(messages).find((message) => message.id === 'answer')?.content).toBe(earlier));
    const stopping = stopResearchRun('chat', 'run');
    await vi.waitFor(() => expect(request.mock.calls.some(([path]) => path.endsWith('/runs/run'))).toBe(true));
    controller.enqueue(new TextEncoder().encode([
      `event: content\ndata: ${JSON.stringify({ text: ' plus the complete final report.' })}\n\n`,
      'event: run_status\ndata: {"status":"completed","error":null}\n\n',
    ].join('')));
    controller.close();
    await sending;
    expect(get(messages).find((message) => message.id === 'answer')?.content).toBe(final);
    resolveRun(Response.json({
      run_id: 'run', status: 'running', revision: 2, context_version: 1,
      cancel_requested: false, snapshot: {},
      message: { id: 'answer', content: earlier, artifacts: [] },
    }));
    await stopping;
    const result = get(messages).find((message) => message.id === 'answer');
    expect(result?.content).toBe(final);
    expect(result?.research?.status).toBe('completed');
  } finally {
    stopResearchPolling();
    vi.useRealTimers();
  }
});
