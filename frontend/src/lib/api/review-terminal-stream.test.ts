import { beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { api } from './client';
import { abortController, activeChat, chatList, isStreaming, messages } from '$lib/stores/chat';
import { loadChat, stopResearchPolling, streamChat } from './chats';

vi.mock('./client', () => ({ api: vi.fn() }));
const request = vi.mocked(api);
beforeEach(() => {
  stopResearchPolling(); request.mockReset(); messages.set([]); activeChat.set(null); chatList.set([]);
  isStreaming.set(false); abortController.set(null);
});

it('a successful Research SSE completion does not replace the final report with an older polled draft', async () => {
  vi.useFakeTimers();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({start(c) {controller=c;}});
  const earlier = 'Earlier persisted draft';
  const final = earlier + ' plus the complete final report.';
  let terminal = false;
  try {
    request.mockResolvedValueOnce(Response.json({id:'chat',messages:[],runs:[]}));
    await loadChat('chat');
    request.mockImplementation(async path => {
      if (path === '/api/chat/completions') return new Response(body);
      if (path.endsWith('/runs/run')) return Response.json({
        run_id:'run',status:terminal?'completed':'running',revision:terminal?3:2,context_version:1,cancel_requested:false,
        snapshot:{},message:{id:'answer',content:terminal?final:earlier,artifacts:[]},
      });
      return Response.json([]);
    });
    const sending=streamChat('Research this','chat',undefined,undefined,undefined,undefined,'research');
    controller.enqueue(new TextEncoder().encode([
      'event: chat\ndata: {"chat_id":"chat","user_message_id":"user","message_id":"answer","run_id":"run","task_kind":"research"}\n\n',
      `event: content\ndata: ${JSON.stringify({text:earlier})}\n\n`,
    ].join('')));
    await vi.waitFor(()=>expect(get(messages).find(m=>m.id==='answer')?.content).toBe(earlier));
    await vi.advanceTimersByTimeAsync(2500);
    expect(get(messages).find(m=>m.id==='answer')?.research?.message?.content).toBe(earlier);
    terminal=true;
    controller.enqueue(new TextEncoder().encode([
      `event: content\ndata: ${JSON.stringify({text:' plus the complete final report.'})}\n\n`,
      'event: run_status\ndata: {"status":"completed","error":null}\n\n',
    ].join('')));
    await vi.waitFor(()=>expect(get(messages).find(m=>m.id==='answer')?.content).toBe(final));
    controller.close();
    await sending;
    const result=get(messages).find(m=>m.id==='answer');
    expect(result?.content).toBe(final);
  } finally { stopResearchPolling(); vi.useRealTimers(); }
});

it('an older running poll response cannot replace newer text streamed while the request was in flight', async () => {
  vi.useFakeTimers();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(c) { controller = c; } });
  let resolveRun!: (response: Response) => void;
  const pendingRun = new Promise<Response>((resolve) => { resolveRun = resolve; });
  const earlier = 'Earlier persisted draft';
  const final = earlier + ' plus the complete final report.';
  try {
    request.mockResolvedValueOnce(Response.json({ id: 'chat', messages: [], runs: [] }));
    await loadChat('chat');
    request.mockImplementation((path) => {
      if (path === '/api/chat/completions') return Promise.resolve(new Response(body));
      if (path.endsWith('/runs/run')) return pendingRun;
      return Promise.resolve(Response.json([]));
    });
    const sending = streamChat('Research this', 'chat', undefined, undefined, undefined, undefined, 'research');
    controller.enqueue(new TextEncoder().encode([
      'event: chat\ndata: {"chat_id":"chat","user_message_id":"user","message_id":"answer","run_id":"run","task_kind":"research"}\n\n',
      `event: content\ndata: ${JSON.stringify({ text: earlier })}\n\n`,
    ].join('')));
    await vi.waitFor(() => expect(get(messages).find((message) => message.id === 'answer')?.content).toBe(earlier));

    const pollTick = vi.advanceTimersByTimeAsync(2500);
    await vi.waitFor(() => expect(request.mock.calls.some(([path]) => path.endsWith('/runs/run'))).toBe(true));
    controller.enqueue(new TextEncoder().encode([
      `event: content\ndata: ${JSON.stringify({ text: ' plus the complete final report.' })}\n\n`,
      'event: run_status\ndata: {"status":"completed","error":null}\n\n',
    ].join('')));
    controller.close();
    await sending;

    resolveRun(Response.json({
      run_id: 'run', status: 'running', revision: 2, context_version: 1, cancel_requested: false,
      snapshot: {}, message: { id: 'answer', content: earlier, artifacts: [] },
    }));
    await pollTick;
    await vi.waitFor(() => expect(get(messages).find((message) => message.id === 'answer')?.research?.revision).toBe(2));
    expect(get(messages).find((message) => message.id === 'answer')?.content).toBe(final);
  } finally {
    resolveRun?.(Response.json({
      run_id: 'run', status: 'running', revision: 2, context_version: 1, cancel_requested: false,
      snapshot: {}, message: { id: 'answer', content: earlier, artifacts: [] },
    }));
    stopResearchPolling();
    vi.useRealTimers();
  }
});
