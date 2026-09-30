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

it('background reload finishing after SSE cannot replace the newly streamed final report', async () => {
  vi.useFakeTimers();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({start(c) {controller=c;}});
  let resolveRun!: (response:Response)=>void;
  const pendingRun = new Promise<Response>(resolve=>{resolveRun=resolve;});
  const earlier='Earlier persisted draft';
  const final=earlier+' plus the complete final report.';
  try {
    request.mockResolvedValueOnce(Response.json({id:'chat',messages:[],runs:[]}));
    await loadChat('chat');
    request.mockImplementation(async path => {
      if(path==='/api/chat/completions') return new Response(body);
      if(path==='/api/chats/chat') return Response.json({id:'chat',messages:[{
        id:'answer',chat_id:'chat',role:'assistant',content:earlier,created_at:'2026-09-30T00:00:00Z',
      }],runs:[{id:'run',task_kind:'research',assistant_message_id:'answer',status:'running'}]});
      if(path.endsWith('/runs/run')) return pendingRun;
      return Response.json([]);
    });
    const sending=streamChat('Research this','chat',undefined,undefined,undefined,undefined,'research');
    controller.enqueue(new TextEncoder().encode([
      'event: chat\ndata: {"chat_id":"chat","user_message_id":"user","message_id":"answer","run_id":"run","task_kind":"research"}\n\n',
      `event: content\ndata: ${JSON.stringify({text:earlier})}\n\n`,
    ].join('')));
    await vi.waitFor(()=>expect(get(messages).find(m=>m.id==='answer')?.content).toBe(earlier));
    const reloading=loadChat('chat',{background:true});
    await vi.waitFor(()=>expect(request.mock.calls.some(([path])=>path.endsWith('/runs/run'))).toBe(true));
    controller.enqueue(new TextEncoder().encode([
      `event: content\ndata: ${JSON.stringify({text:' plus the complete final report.'})}\n\n`,
      'event: run_status\ndata: {"status":"completed","error":null}\n\n',
    ].join('')));
    controller.close();
    await sending;
    expect(get(messages).find(m=>m.id==='answer')?.content).toBe(final);
    resolveRun(Response.json({run_id:'run',status:'running',revision:2,context_version:1,cancel_requested:false,snapshot:{},message:{id:'answer',content:earlier,artifacts:[]}}));
    await reloading;
    const result=get(messages).find(m=>m.id==='answer');
    expect(result?.content).toBe(final);
    expect(result?.research?.status).toBe('completed');
  } finally { stopResearchPolling();vi.useRealTimers(); }
});
