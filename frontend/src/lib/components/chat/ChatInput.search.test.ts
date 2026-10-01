import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import ChatInput from './ChatInput.svelte';
import { activeChat, chatList, messages, researchEnabled, searchEnabled, selectedModel, setActiveChatId } from '$lib/stores/chat';
import { fetchFeatures, loadChat, streamChat } from '$lib/api/chats';
import type { UploadedFile } from '$lib/api/files';

describe('ChatInput search mode', () => {
  beforeEach(() => {
    searchEnabled.set(false);
    researchEnabled.set(false);
    selectedModel.set('test/model');
    messages.set([]);
    activeChat.set(null);
    setActiveChatId(null);
    chatList.set([]);
  });

  afterEach(() => {
    cleanup();
    searchEnabled.set(false);
    researchEnabled.set(false);
    messages.set([]);
    activeChat.set(null);
    setActiveChatId(null);
    chatList.set([]);
    vi.unstubAllGlobals();
  });

  it('keeps ordinary chat as the default when search is disabled', async () => {
    const stream = 'event: chat\ndata: {"chat_id":"chat-ordinary","user_message_id":"user-ordinary","message_id":"assistant-ordinary"}\n\nevent: content\ndata: {"text":"Ordinary answer"}\n\n';
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/models/features') return new Response(JSON.stringify({ search_enabled: false }));
      if (path === '/api/chat/completions') return new Response(stream);
      if (path.startsWith('/api/chats?')) return new Response('[]');
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    await fetchFeatures();
    let request: Promise<string | undefined> = Promise.resolve(undefined);
    const onSend = (text: string, fileIds: string[], uploaded: UploadedFile[], modeHint?: 'search' | 'research') => {
      request = streamChat(text, undefined, fileIds, uploaded, undefined, undefined, modeHint);
    };
    render(ChatInput, { props: { onSend } });

    expect(screen.queryByRole('button', { name: 'chat.mode_search' })).toBeNull();
    await fireEvent.input(screen.getByRole('textbox'), { target: { value: 'Hello' } });
    await fireEvent.click(screen.getByRole('button', { name: 'chat.sendMessage' }));
    await request;

    const completionCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/chat/completions');
    expect(JSON.parse(String((completionCall?.[1] as RequestInit).body))).not.toHaveProperty('mode_hint');
  });

  it('sends the selected search mode through the mocked request, execution, status, and saved result', async () => {
    searchEnabled.set(true);
    const searchResult = {
      status: 'partial',
      results: [{ title: 'Mock source', url: 'https://example.test/source', snippet: 'Mock evidence' }],
      errors: [{ query: 'latest report', error: 'one source timed out' }],
    };
    const persisted = {
      id: 'chat-1',
      workspace_id: null,
      title: 'Find current sources',
      model: 'test/model',
      pinned: false,
      created_at: '2026-09-30T00:00:00Z',
      updated_at: '2026-09-30T00:00:00Z',
      messages: [
        {
          id: 'user-1', chat_id: 'chat-1', role: 'user', content: 'Find current sources',
          created_at: '2026-09-30T00:00:00Z',
        },
        {
          id: 'assistant-1', chat_id: 'chat-1', role: 'assistant',
          content: 'A source-grounded answer with a partial retrieval note.',
          tool_calls: [{
            id: 'search-1', name: 'fast_search', arguments: '{"query":"latest report"}',
            status: 'completed', result: searchResult,
          }],
          created_at: '2026-09-30T00:00:01Z',
        },
      ],
      runs: [{ status: 'completed', assistant_message_id: 'assistant-1', error: null }],
    };
    const stream = [
      'event: chat\ndata: {"chat_id":"chat-1","user_message_id":"user-1","message_id":"assistant-1"}\n\n',
      'event: tool_executing\ndata: {"id":"search-1","name":"fast_search","arguments":"{\\"query\\":\\"latest report\\"}"}\n\n',
      `event: tool_result\ndata: ${JSON.stringify({ id: 'search-1', status: 'completed', result: searchResult })}\n\n`,
      'event: content\ndata: {"text":"A source-grounded answer with a partial retrieval note."}\n\n',
    ].join('');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/models/features') return new Response(JSON.stringify({ search_enabled: true }));
      if (path === '/api/chat/completions') return new Response(stream);
      if (path.startsWith('/api/chats?')) return new Response('[]');
      if (path === '/api/chats/chat-1') return new Response(JSON.stringify(persisted));
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    await fetchFeatures();

    let request: Promise<string | undefined> = Promise.resolve(undefined);
    const onSend = (text: string, fileIds: string[], uploaded: UploadedFile[], modeHint?: 'search' | 'research') => {
      request = streamChat(text, undefined, fileIds, uploaded, undefined, undefined, modeHint);
    };
    render(ChatInput, { props: { onSend } });

    expect(screen.getByRole('button', { name: 'chat.mode_auto' }).getAttribute('aria-pressed')).toBe('true');
    await fireEvent.click(screen.getByRole('button', { name: 'chat.mode_search' }));
    await fireEvent.input(screen.getByRole('textbox'), { target: { value: 'Find current sources' } });
    await fireEvent.click(screen.getByRole('button', { name: 'chat.sendMessage' }));
    await request;
    expect(screen.getByRole('button', { name: 'chat.mode_auto' }).getAttribute('aria-pressed')).toBe('true');

    const completionCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/chat/completions');
    expect(completionCall).toBeDefined();
    expect(JSON.parse(String((completionCall?.[1] as RequestInit).body))).toMatchObject({
      message: 'Find current sources',
      mode_hint: 'search',
    });
    expect(get(messages).find((message) => message.id === 'assistant-1')?.toolExecutions?.[0]).toMatchObject({
      id: 'search-1',
      status: 'completed',
      result: searchResult,
    });

    await loadChat('chat-1');
    const savedAssistant = get(messages).find((message) => message.id === 'assistant-1');
    expect(savedAssistant).toMatchObject({
      content: 'A source-grounded answer with a partial retrieval note.',
      toolExecutions: [{ status: 'completed', result: { status: 'partial' } }],
    });
  });

  it('keeps Research and Search mutually exclusive and forwards Research from the composer', async () => {
    searchEnabled.set(true);
    researchEnabled.set(true);
    const onSend = vi.fn();
    render(ChatInput, { props: { onSend } });

    const researchButton = screen.getByRole('button', { name: 'research.mode' });
    const searchButton = screen.getByRole('button', { name: 'chat.mode_search' });
    await fireEvent.click(researchButton);
    expect(researchButton.getAttribute('aria-pressed')).toBe('true');
    expect(searchButton.getAttribute('aria-pressed')).toBe('false');

    await fireEvent.click(searchButton);
    expect(researchButton.getAttribute('aria-pressed')).toBe('false');
    expect(searchButton.getAttribute('aria-pressed')).toBe('true');

    await fireEvent.click(researchButton);
    await fireEvent.input(screen.getByRole('textbox'), { target: { value: 'Investigate this' } });
    await fireEvent.click(screen.getByRole('button', { name: 'chat.sendMessage' }));
    expect(onSend).toHaveBeenCalledWith('Investigate this', [], [], 'research');
    expect(researchButton.getAttribute('aria-pressed')).toBe('false');
  });
});
