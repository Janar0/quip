import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ModelSelector from './ModelSelector.svelte';
import { get } from 'svelte/store';
import { messages, selectedModel } from '$lib/stores/chat';
import { adminDefaultModel, modelList, modelsLoaded, type ModelItem } from '$lib/stores/models';
import { streamChat } from '$lib/api/chats';

const models: ModelItem[] = [
  {
    id: 'openai/gpt-4o',
    name: 'GPT-4o',
    display_name: 'OpenAI: GPT-4o',
    provider: 'OpenAI',
    context_length: 128_000,
    pricing: { prompt: '0', completion: '0' },
  },
  {
    id: 'anthropic/claude-3-7-sonnet',
    name: 'Claude 3.7 Sonnet',
    display_name: 'Anthropic: Claude 3.7 Sonnet',
    provider: 'Anthropic',
    context_length: 200_000,
    pricing: { prompt: '0', completion: '0' },
  },
];

describe('ModelSelector', () => {
  beforeEach(() => {
    if (!Element.prototype.animate) {
      Object.defineProperty(Element.prototype, 'animate', {
        configurable: true,
        value: () => ({
          cancel() {},
          finish() {},
          pause() {},
          play() {},
          reverse() {},
          finished: Promise.resolve(),
        }),
      });
    }
    modelList.set(models);
    modelsLoaded.set(true);
    adminDefaultModel.set(null);
    selectedModel.set('openai/gpt-4o');
  });

  afterEach(() => {
    cleanup();
    messages.set([]);
    vi.unstubAllGlobals();
  });

  it('filters available models and states the selected model applies to the next response', async () => {
    render(ModelSelector, { variant: 'picker' });

    await fireEvent.click(screen.getByRole('button', { name: /GPT-4o/i }));
    const search = screen.getByRole('searchbox', { name: 'models.search' });
    await fireEvent.input(search, { target: { value: 'claude' } });

    expect(screen.getByRole('option', { name: /Claude 3.7 Sonnet/i })).toBeTruthy();
    expect(screen.queryByRole('option', { name: /GPT-4o/i })).toBeNull();
    expect(screen.getByText('models.nextResponse')).toBeTruthy();
    expect(screen.getByRole('option', { name: /Claude 3.7 Sonnet/i }).getAttribute('aria-selected')).toBe('false');
  });

  it('shows a localized empty state when no model matches the search', async () => {
    render(ModelSelector, { variant: 'picker' });

    await fireEvent.click(screen.getByRole('button', { name: /GPT-4o/i }));
    await fireEvent.input(screen.getByRole('searchbox', { name: 'models.search' }), { target: { value: 'missing-model' } });

    expect(screen.getByText('models.noSearchResults')).toBeTruthy();
  });

  it('fits the menu within a narrow viewport and opens toward the available space', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 320 });
    render(ModelSelector, { variant: 'picker' });
    const trigger = screen.getByRole('button', { name: /GPT-4o/i });
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
      x: 260, y: 270, width: 50, height: 30, top: 270, right: 310, bottom: 300, left: 260,
      toJSON: () => ({}),
    } as DOMRect);
    await fireEvent.click(trigger);

    const menu = screen.getByRole('dialog', { name: 'models.search' });
    expect(menu.getAttribute('style')).toContain('left: 8px');
    expect(menu.getAttribute('style')).toContain('width: 304px');
    expect(menu.getAttribute('style')).toContain('max-height: 254px');
  });

  it('sends the model selected in the UI and stores the streamed response', async () => {
    render(ModelSelector, { variant: 'picker' });
    await fireEvent.click(screen.getByRole('button', { name: /GPT-4o/i }));
    await fireEvent.click(screen.getByRole('option', { name: /Claude 3.7 Sonnet/i }));

    const stream = [
      'event: chat\ndata: {"chat_id":"chat-1","user_message_id":"user-1","message_id":"assistant-1"}\n\n',
      'event: content\ndata: {"text":"Mock answer"}\n\n',
    ].join('');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      if (String(input) === '/api/chat/completions') return new Response(stream);
      if (String(input).startsWith('/api/chats?')) return new Response('[]');
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    await streamChat('Explain the result');

    const completionCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/chat/completions');
    expect(completionCall).toBeDefined();
    expect(JSON.parse(String((completionCall?.[1] as RequestInit).body))).toMatchObject({
      model: 'anthropic/claude-3-7-sonnet',
      message: 'Explain the result',
    });
    expect(get(messages).find((message) => message.id === 'assistant-1')).toMatchObject({
      model: 'anthropic/claude-3-7-sonnet',
      content: 'Mock answer',
    });
  });
});
