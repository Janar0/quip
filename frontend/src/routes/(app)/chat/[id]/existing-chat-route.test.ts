import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { activeChat, chatList, isLoading, isStreaming, messages, searchEnabled, selectedModel } from '$lib/stores/chat';

vi.mock('$app/state', () => ({
  page: { params: { id: 'chat-42' }, url: new URL('http://localhost/chat/chat-42') },
}));

import ChatRoute from './+page.svelte';
import { loadChat } from '$lib/api/chats';

describe('existing chat route Search mode', () => {
  beforeEach(() => {
    if (!Element.prototype.animate) {
      Object.defineProperty(Element.prototype, 'animate', {
        configurable: true,
        value: () => ({ cancel() {}, finish() {}, pause() {}, play() {}, reverse() {}, finished: Promise.resolve() }),
      });
    }
    activeChat.set({
      id: 'chat-42', workspace_id: 'workspace-42', title: 'Existing chat', model: 'test/model',
      pinned: false, created_at: '', updated_at: '',
    });
    messages.set([]);
    chatList.set([]);
    searchEnabled.set(true);
    selectedModel.set('test/model');
    isLoading.set(false);
    isStreaming.set(false);
  });

  afterEach(() => {
    cleanup();
    activeChat.set(null);
    messages.set([]);
    chatList.set([]);
    searchEnabled.set(false);
    isLoading.set(false);
    isStreaming.set(false);
    vi.unstubAllGlobals();
  });

  it('sends the selected mode through the route and restores its mocked persisted search result', async () => {
    const searchResult = {
      status: 'partial',
      results: [{ title: 'Mock source', url: 'https://example.test/source', snippet: 'Mock evidence' }],
      errors: [{ query: 'current source', error: 'one source timed out' }],
    };
    const savedChat = {
      id: 'chat-42',
      workspace_id: 'workspace-42',
      title: 'Existing chat',
      model: 'test/model',
      pinned: false,
      created_at: '2026-09-30T00:00:00Z',
      updated_at: '2026-09-30T00:00:00Z',
      messages: [
        {
          id: 'user-42', chat_id: 'chat-42', role: 'user', content: 'Find current sources',
          created_at: '2026-09-30T00:00:00Z',
        },
        {
          id: 'assistant-42', chat_id: 'chat-42', role: 'assistant',
          content: 'A source-grounded answer with a partial retrieval note.',
          tool_calls: [{
            id: 'search-42', name: 'fast_search', arguments: JSON.stringify({ query: 'current source' }),
            status: 'completed', result: searchResult,
          }],
          created_at: '2026-09-30T00:00:01Z',
        },
      ],
      runs: [{ status: 'completed', assistant_message_id: 'assistant-42', error: null }],
    };
    const event = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
    const stream = [
      event('chat', { chat_id: 'chat-42', user_message_id: 'user-42', message_id: 'assistant-42' }),
      event('tool_executing', {
        id: 'search-42', name: 'fast_search', arguments: JSON.stringify({ query: 'current source' }),
      }),
      event('tool_result', { id: 'search-42', status: 'completed', result: searchResult }),
      event('content', { text: 'A source-grounded answer with a partial retrieval note.' }),
    ].join('');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/chat/completions') return new Response(stream);
      if (path.startsWith('/api/chats?')) return new Response('[]');
      if (path === '/api/chats/chat-42') return new Response(JSON.stringify(savedChat));
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(ChatRoute);
    await fireEvent.click(screen.getByRole('button', { name: 'chat.mode_search' }));
    await fireEvent.input(screen.getByRole('textbox'), { target: { value: 'Find current sources' } });
    await fireEvent.click(screen.getByRole('button', { name: 'chat.sendMessage' }));

    await waitFor(() => {
      const completionCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/chat/completions');
      expect(completionCall).toBeDefined();
      expect(JSON.parse(String((completionCall?.[1] as RequestInit).body))).toMatchObject({
        chat_id: 'chat-42',
        workspace_id: 'workspace-42',
        message: 'Find current sources',
        mode_hint: 'search',
      });
      expect(get(messages).find((message) => message.id === 'assistant-42')?.toolExecutions?.[0]).toMatchObject({
        status: 'completed',
        result: { status: 'partial' },
      });
    });

    await loadChat('chat-42');
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/chats/chat-42')).toBe(true);
    expect(get(messages).find((message) => message.id === 'assistant-42')).toMatchObject({
      content: 'A source-grounded answer with a partial retrieval note.',
      toolExecutions: [{ status: 'completed', result: { status: 'partial' } }],
    });
  });
});
