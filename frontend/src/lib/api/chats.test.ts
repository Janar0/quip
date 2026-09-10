import { beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { api } from './client';
import { chatList, messages, activeChat } from '$lib/stores/chat';
import { selectedWorkspaceId } from '$lib/stores/workspaces';
import { loadChats, loadMoreChats, loadChat } from './chats';

vi.mock('./client', () => ({ api: vi.fn() }));
const request = vi.mocked(api);
const page = Array.from({ length: 50 }, (_, i) => ({ id: String(i) }));
beforeEach(() => { request.mockReset(); chatList.set([]); selectedWorkspaceId.set(null); });

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

it('restores persisted run errors alongside the partial answer', async () => {
  request.mockResolvedValueOnce(Response.json({
    id: 'chat', messages: [{ id: 'answer', content: 'Partial answer' }],
    runs: [{ assistant_message_id: 'answer', status: 'failed', error: 'DNS failed' }],
  }));
  await loadChat('chat');
  expect(get(messages)[0]).toMatchObject({ content: 'Partial answer', error: 'DNS failed' });
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
