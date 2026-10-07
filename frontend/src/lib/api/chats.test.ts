import { beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { api } from './client';
import { chatList, messages, activeChat, abortController, isStreaming, searchEnabled, researchEnabled, setActiveChatId } from '$lib/stores/chat';
import { selectedWorkspaceId } from '$lib/stores/workspaces';
import { enterNewChatView, fetchFeatures, loadChats, loadMoreChats, loadChat, stopGeneration, stopResearchPolling, streamChat } from './chats';

vi.mock('./client', () => ({ api: vi.fn() }));
const request = vi.mocked(api);
const page = Array.from({ length: 50 }, (_, i) => ({ id: String(i) }));
beforeEach(() => {
  stopResearchPolling();
  request.mockReset(); chatList.set([]); messages.set([]); activeChat.set(null); setActiveChatId(null); selectedWorkspaceId.set(null);
  abortController.set(null); isStreaming.set(false);
  searchEnabled.set(false); researchEnabled.set(false);
});

it('does not skip a page after a failed request', async () => {
  request.mockResolvedValueOnce(Response.json(page));
  await loadChats();
  request.mockResolvedValueOnce(new Response(null, { status: 503 }));
  await loadMoreChats();
  request.mockResolvedValueOnce(Response.json([{ id: '50' }]));
  await loadMoreChats();
  expect(request.mock.calls[1][0]).toContain('offset=50');
  expect(request.mock.calls[2][0]).toContain('offset=50');
  expect(get(chatList)).toHaveLength(51);
});

it('ignores a previous workspace response arriving late', async () => {
  let resolve!: (response: Response) => void;
  request.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  const old = loadChats();
  selectedWorkspaceId.set('new-workspace');
  request.mockResolvedValueOnce(Response.json([{ id: 'new' }]));
  await loadChats();
  resolve(Response.json([{ id: 'old' }]));
  await old;
  expect(get(chatList).map((chat) => chat.id)).toEqual(['new']);
});

it('ignores a previous chat response arriving late', async () => {
  let resolve!: (response: Response) => void;
  request.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  const old = loadChat('old');
  request.mockResolvedValueOnce(Response.json({ id: 'new', messages: [] }));
  await loadChat('new');
  resolve(Response.json({ id: 'old', messages: [] }));
  await old;
  expect(get(activeChat)?.id).toBe('new');
});

it('preserves live optimistic messages when an existing-chat snapshot races the stream', async () => {
  const searchExecution = {
    id: 'search-1', name: 'fast_search', arguments: '{}', status: 'completed' as const,
    result: { results: [{ title: 'Mock source', url: 'https://example.test/source' }] },
  };
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
  request.mockImplementation(async (path) => {
    if (path === '/api/chat/completions') return new Response(body);
    if (path === '/api/chats/chat') return Response.json({
      id: 'chat', workspace_id: null,
      messages: [{ id: 'previous', chat_id: 'chat', role: 'assistant', content: 'Earlier answer', created_at: '' }],
      runs: [],
    });
    return Response.json([]);
  });

  const sending = streamChat('Question', 'chat');
  controller.enqueue(new TextEncoder().encode([
    'event: chat\ndata: {"chat_id":"chat","user_message_id":"user-1","message_id":"answer-1"}\n\n',
    'event: tool_executing\ndata: {"id":"search-1","name":"fast_search","arguments":"{}"}\n\n',
    `event: tool_result\ndata: ${JSON.stringify({ id: 'search-1', status: 'completed', result: searchExecution.result })}\n\n`,
    'event: content\ndata: {"text":"Partial answer"}\n\n',
  ].join('')));
  await vi.waitFor(() => expect(get(messages).find((message) => message.id === 'answer-1')?.toolExecutions)
    .toEqual([searchExecution]));

  await loadChat('chat');

  expect(get(messages).map((message) => message.id)).toEqual(['previous', 'user-1', 'answer-1']);
  expect(get(messages).find((message) => message.id === 'answer-1')?.toolExecutions).toEqual([searchExecution]);
  controller.close();
  await sending;
});

it('restores persisted run errors alongside the partial answer', async () => {
  request.mockResolvedValueOnce(Response.json({
    id: 'chat', messages: [{ id: 'answer', content: 'Partial answer' }],
    runs: [{ assistant_message_id: 'answer', status: 'failed', error: 'DNS failed' }],
  }));
  await loadChat('chat');
  expect(get(messages)[0]).toMatchObject({ content: 'Partial answer', error: 'DNS failed' });
});

it('restores a research snapshot and partial report after page reload', async () => {
  request.mockResolvedValueOnce(Response.json({
    id: 'chat',
    messages: [{ id: 'answer', chat_id: 'chat', role: 'assistant', content: 'Saved partial report' }],
    runs: [{ id: 'run-1', assistant_message_id: 'answer', status: 'partial', task_kind: 'research', error: 'One agent failed' }],
  }));
  request.mockResolvedValueOnce(Response.json({
    run_id: 'run-1', status: 'partial', revision: 7, context_version: 2, cancel_requested: false,
    snapshot: {
      progress: [{ phase: 'synthesizing', detail: 'Partial report' }],
      sources: [{ title: 'Example', url: 'https://example.org/source' }],
      errors: [{ message: 'One agent failed' }],
    },
  }));
  await loadChat('chat');
  expect(get(messages)[0]).toMatchObject({
    content: 'Saved partial report',
    research: {
      runId: 'run-1', status: 'partial', revision: 7, contextVersion: 2,
      snapshot: { sources: [{ title: 'Example', url: 'https://example.org/source' }] },
    },
  });
  stopResearchPolling('chat');
});

it('replaces the matching assistant report with the newest persisted run message', async () => {
  request.mockResolvedValueOnce(Response.json({
    id: 'chat',
    messages: [
      { id: 'user-1', chat_id: 'chat', role: 'user', content: 'Research this', created_at: '' },
      { id: 'answer', chat_id: 'chat', role: 'assistant', content: 'Older draft', created_at: '' },
    ],
    runs: [{ id: 'run-1', assistant_message_id: 'answer', status: 'completed', task_kind: 'research' }],
  }));
  request.mockResolvedValueOnce(Response.json({
    run_id: 'run-1', status: 'completed', revision: 5, context_version: 1, cancel_requested: false,
    snapshot: {},
    message: { id: 'answer', content: 'Final saved report', artifacts: [] },
  }));

  await loadChat('chat');

  expect(get(messages)).toHaveLength(2);
  expect(get(messages)[0].content).toBe('Research this');
  expect(get(messages)[1].content).toBe('Final saved report');
});

it('polls newer report text without overwriting the user message', async () => {
  vi.useFakeTimers();
  try {
    request.mockResolvedValueOnce(Response.json({
      id: 'chat',
      messages: [
        { id: 'user-1', chat_id: 'chat', role: 'user', content: 'Research this', created_at: '' },
        { id: 'answer', chat_id: 'chat', role: 'assistant', content: 'Old saved text', created_at: '' },
      ],
      runs: [{ id: 'run-1', assistant_message_id: 'answer', status: 'running', task_kind: 'research' }],
    }));
    request.mockResolvedValueOnce(Response.json({
      run_id: 'run-1', status: 'running', revision: 1, context_version: 1, cancel_requested: false,
      snapshot: {}, message: { id: 'answer', content: 'Persisted draft one', artifacts: [] },
    }));
    request.mockResolvedValueOnce(Response.json({
      run_id: 'run-1', status: 'running', revision: 2, context_version: 1, cancel_requested: false,
      snapshot: {}, message: { id: 'answer', content: 'Persisted draft two', artifacts: [] },
    }));

    await loadChat('chat');
    expect(get(messages)[1].content).toBe('Persisted draft one');
    await vi.advanceTimersByTimeAsync(2500);

    expect(get(messages)).toHaveLength(2);
    expect(get(messages)[0].content).toBe('Research this');
    expect(get(messages)[1].content).toBe('Persisted draft two');
  } finally {
    stopResearchPolling('chat');
    vi.useRealTimers();
  }
});

it('keeps a locally changed report and surfaces a failed Stop with refreshed status', async () => {
  messages.set([{
    id: 'answer', chat_id: 'chat', role: 'assistant', content: 'Locally edited report', created_at: '',
    research: {
      runId: 'run-1', status: 'running', revision: 1, contextVersion: 1, cancelRequested: false,
      snapshot: {}, message: { id: 'answer', content: 'Previously saved report', artifacts: [] },
    },
  }]);
  request.mockResolvedValueOnce(Response.json({ detail: 'Cancellation unavailable' }, { status: 503 }));
  request.mockResolvedValueOnce(Response.json({
    run_id: 'run-1', status: 'running', revision: 2, context_version: 1, cancel_requested: false,
    snapshot: {}, message: { id: 'answer', content: 'New server draft', artifacts: [] },
  }));

  await stopGeneration();

  expect(get(messages)[0].content).toBe('Locally edited report');
  expect(get(messages)[0].research?.status).toBe('running');
  expect(get(messages)[0].error).toContain('HTTP 503');
  expect(get(messages)[0].error).toContain('Cancellation unavailable');
});

it('exposes research only when backend reports the guarded feature flag', async () => {
  request.mockResolvedValueOnce(Response.json({ search_enabled: true, research_enabled: false }));
  const { researchEnabled } = await import('$lib/stores/chat');
  await fetchFeatures();
  expect(get(researchEnabled)).toBe(false);
});

it('sends explicit research mode and publishes the new chat ID on its first SSE event', async () => {
  researchEnabled.set(true);
  const stream = new Response([
    'event: chat\ndata: {"chat_id":"new-chat","user_message_id":"user","message_id":"answer","run_id":"run-1","task_kind":"research"}\n\n',
    'event: content\ndata: {"text":"Started"}\n\n',
  ].join(''));
  request.mockImplementation(async (path) => path === '/api/chat/completions' ? stream : Response.json([]));
  const ready = vi.fn();
  await streamChat('Investigate this', undefined, undefined, undefined, undefined, undefined, 'research', ready);
  const completion = request.mock.calls.find(([path]) => path === '/api/chat/completions');
  expect(JSON.parse(completion?.[1]?.body as string).mode_hint).toBe('research');
  expect(ready).toHaveBeenCalledWith({
    chatId: 'new-chat', userMessageId: 'user', messageId: 'answer', runId: 'run-1', taskKind: 'research',
  });
  stopResearchPolling('new-chat');
});

it.each(['search', 'research'] as const)(
  'does not send disabled %s mode from a stale or forged caller hint',
  async (mode) => {
  request.mockImplementation(async (path) => path === '/api/chat/completions'
    ? new Response('')
    : Response.json([]));

  await streamChat('Question', undefined, undefined, undefined, undefined, undefined, mode);

  const completion = request.mock.calls.find(([path]) => path === '/api/chat/completions');
  expect(JSON.parse(completion?.[1]?.body as string)).not.toHaveProperty('mode_hint');
  },
);

it('uses durable cancellation for an active research run', async () => {
  messages.set([{
    id: 'answer', chat_id: 'chat', role: 'assistant', content: 'Partial', created_at: '',
    research: {
      runId: 'run-1', status: 'running', revision: 2, contextVersion: 1, cancelRequested: false,
      snapshot: {},
    },
  }]);
  request.mockResolvedValueOnce(Response.json({
    accepted: true,
    run: {
      run_id: 'run-1', status: 'cancelling', revision: 3, context_version: 1, cancel_requested: true,
      snapshot: {},
    },
  }));
  await stopGeneration();
  expect(request.mock.calls[0][0]).toBe('/api/chats/chat/runs/run-1/cancel');
  expect(get(messages)[0].research?.status).toBe('cancelling');
});

it('defers Stop until the research chat event supplies a durable run ID', async () => {
  researchEnabled.set(true);
  let streamController!: ReadableStreamDefaultController<Uint8Array>;
  let completionSignal: AbortSignal | undefined;
  const body = new ReadableStream<Uint8Array>({
    start(controller) { streamController = controller; },
  });
  request.mockImplementation(async (path, init) => {
    if (path === '/api/chat/completions') {
      completionSignal = init?.signal as AbortSignal;
      return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
    }
    if (path.endsWith('/cancel')) {
      return Response.json({
        accepted: true,
        run: {
          run_id: 'run-early-stop', status: 'cancelling', revision: 1,
          context_version: 1, cancel_requested: true, snapshot: {},
        },
      });
    }
    return Response.json([]);
  });

  const requestTask = streamChat('Research this', 'chat-1', undefined, undefined, undefined, undefined, 'research');
  try {
    await Promise.resolve();
    await Promise.resolve();
    expect(completionSignal).toBeDefined();

    await stopGeneration();
    expect(completionSignal?.aborted).toBe(false);
    expect(request.mock.calls.some(([path]) => path.endsWith('/cancel'))).toBe(false);

    streamController.enqueue(new TextEncoder().encode(
      'event: chat\ndata: {"chat_id":"chat-1","user_message_id":"user-1","message_id":"answer-1","run_id":"run-early-stop","task_kind":"research"}\n\n',
    ));
    streamController.close();
    await requestTask;

    expect(request.mock.calls.find(([path]) => path.endsWith('/cancel'))?.[0])
      .toBe('/api/chats/chat-1/runs/run-early-stop/cancel');
    expect(completionSignal?.aborted).toBe(false);
  } finally {
    try { streamController.close(); } catch { /* The test may already have closed it. */ }
    await requestTask;
  }
});

it('can retry failed requests without duplicate optimistic message keys', async () => {
  const { streamChat } = await import('./chats');
  messages.set([]);
  request.mockImplementation(async (path) => path.includes('completions')
    ? Response.json({ detail: 'Provider unavailable' }, { status: 503 })
    : Response.json([]));
  await streamChat('first');
  await streamChat('second');
  const items = get(messages);
  expect(items).toHaveLength(4);
  expect(new Set(items.map((message) => message.id)).size).toBe(4);
  expect(items[3].parent_id).toBe(items[2].id);
  expect(items[3].error).toBe('Provider unavailable');
});

it('keeps the old stream running in the background when a new chat starts', async () => {
  let oldController!: ReadableStreamDefaultController<Uint8Array>;
  let newController!: ReadableStreamDefaultController<Uint8Array>;
  const oldBody = new ReadableStream<Uint8Array>({ start(value) { oldController = value; } });
  const newBody = new ReadableStream<Uint8Array>({ start(value) { newController = value; } });
  let completionCount = 0;
  request.mockImplementation(async (path) => {
    if (path === '/api/chat/completions') {
      completionCount += 1;
      return new Response(completionCount === 1 ? oldBody : newBody);
    }
    return Response.json([]);
  });

  const oldRequest = streamChat('Old question', 'old-chat');
  oldController.enqueue(new TextEncoder().encode([
    'event: chat\ndata: {"chat_id":"old-chat","user_message_id":"old-user","message_id":"old-answer"}\n\n',
    'event: content\ndata: {"text":"Old response"}\n\n',
  ].join('')));
  await vi.waitFor(() => expect(get(messages).some((message) => message.content === 'Old response')).toBe(true));

  enterNewChatView();
  expect(get(messages)).toEqual([]);
  const newRequest = streamChat('New question');
  newController.enqueue(new TextEncoder().encode([
    'event: chat\ndata: {"chat_id":"new-chat","user_message_id":"new-user","message_id":"new-answer"}\n\n',
    'event: content\ndata: {"text":"New response"}\n\n',
  ].join('')));
  await vi.waitFor(() => expect(get(messages).some((message) => message.content === 'New response')).toBe(true));
  expect(get(isStreaming)).toBe(true);

  oldController.enqueue(new TextEncoder().encode('event: content\ndata: {"text":" continues"}\n\n'));
  await Promise.resolve();
  expect(get(messages).find((message) => message.id === 'new-answer')?.content).toBe('New response');

  oldController.close();
  await oldRequest;
  expect(get(isStreaming)).toBe(true);
  newController.close();
  await newRequest;
  expect(get(isStreaming)).toBe(false);
});

it('keeps assistant text when a research snapshot names a different persisted message', async () => {
  request.mockResolvedValueOnce(Response.json({
    id: 'chat',
    messages: [{ id: 'answer', chat_id: 'chat', role: 'assistant', content: 'Correct report', created_at: '' }],
    runs: [{ id: 'run-1', assistant_message_id: 'answer', status: 'completed', task_kind: 'research' }],
  }));
  request.mockResolvedValueOnce(Response.json({
    run_id: 'run-1', status: 'completed', revision: 5, context_version: 1, cancel_requested: false,
    snapshot: {}, message: { id: 'other-answer', content: 'Unrelated report', artifacts: [] },
  }));
  await loadChat('chat');
  expect(get(messages)[0].content).toBe('Correct report');
  expect(get(messages)[0].research?.status).toBe('completed');
});

it.each(['success', 'failure'] as const)('a stale chat poll %s cannot stop the selected chat from reaching its terminal report', async (outcome) => {
  vi.useFakeTimers();
  try {
    let finishOldPoll!: (response: Response) => void;
    let aRequests = 0;
    let bRequests = 0;
    const snapshot = (chatId: string) => ({
      id: chatId,
      messages: [{ id: `answer-${chatId}`, chat_id: chatId, role: 'assistant', content: `Draft ${chatId}`, created_at: '' }],
      runs: [{ id: `run-${chatId}`, assistant_message_id: `answer-${chatId}`, status: 'running', task_kind: 'research' }],
    });
    const run = (chatId: string, terminal = false) => ({
      run_id: `run-${chatId}`, status: terminal ? 'completed' : 'running', revision: terminal ? 2 : 1,
      context_version: 1, cancel_requested: false, snapshot: {},
      message: { id: `answer-${chatId}`, content: terminal ? `Final ${chatId}` : `Draft ${chatId}`, artifacts: [] },
    });
    request.mockImplementation(async (path) => {
      if (path === '/api/chats/A') return Response.json(snapshot('A'));
      if (path === '/api/chats/B') return Response.json(snapshot('B'));
      if (path === '/api/chats/A/runs/run-A') {
        if (++aRequests === 1) return Response.json(run('A'));
        return new Promise<Response>((resolve) => { finishOldPoll = resolve; });
      }
      if (path === '/api/chats/B/runs/run-B') return Response.json(run('B', ++bRequests > 1));
      throw new Error(`Unexpected request: ${path}`);
    });
    await loadChat('A');
    await vi.advanceTimersByTimeAsync(2500);
    expect(aRequests).toBe(2);
    await loadChat('B');
    finishOldPoll(outcome === 'success' ? Response.json(run('A', true)) : new Response(null, { status: 503 }));
    await vi.advanceTimersByTimeAsync(5000);
    expect(get(activeChat)?.id).toBe('B');
    expect(get(messages)[0]).toMatchObject({ content: 'Final B', research: { status: 'completed' } });
    expect(bRequests).toBe(2);
  } finally {
    stopResearchPolling();
    vi.useRealTimers();
  }
});
