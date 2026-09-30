import { beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { api } from './client';
import { chatList, messages, activeChat, abortController, isStreaming, searchEnabled, researchEnabled } from '$lib/stores/chat';
import { selectedWorkspaceId } from '$lib/stores/workspaces';
import { fetchFeatures, loadChats, loadMoreChats, loadChat, stopGeneration, stopResearchPolling, streamChat } from './chats';

vi.mock('./client', () => ({ api: vi.fn() }));
const request = vi.mocked(api);
const page = Array.from({ length: 50 }, (_, i) => ({ id: String(i) }));
beforeEach(() => {
  stopResearchPolling();
  request.mockReset(); chatList.set([]); messages.set([]); activeChat.set(null); selectedWorkspaceId.set(null);
  abortController.set(null); isStreaming.set(false);
  searchEnabled.set(false); researchEnabled.set(false);
});

it('a disabled Research hint degrades to ordinary Chat with working Stop', async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
  let signal: AbortSignal | null | undefined;
  request.mockImplementation(async (path, options) => {
    if (path === '/api/chat/completions') {
      signal = options?.signal;
      return new Response(body);
    }
    return Response.json([]);
  });
  const sending = streamChat('Question', 'chat', undefined, undefined, undefined, undefined, 'research');
  await vi.waitFor(() => expect(signal).toBeDefined());
  const completion = request.mock.calls.find(([path]) => path === '/api/chat/completions');
  const transmittedMode = JSON.parse(completion?.[1]?.body as string).mode_hint;
  await stopGeneration();
  const aborted = signal?.aborted;
  controller.close();
  await sending;
  expect(transmittedMode).toBeUndefined();
  expect(aborted).toBe(true);
});
