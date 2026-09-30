import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import ChatPane from './ChatPane.svelte';
import { activeDrawer } from '$lib/stores/drawer';
import { selectedArtifactId } from '$lib/stores/artifacts';
import { messages } from '$lib/stores/chat';
import { get } from 'svelte/store';

describe('ChatPane drawer', () => {
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
    messages.set([{
      id: 'assistant-1',
      chat_id: 'chat-1',
      role: 'assistant',
      content: '',
      created_at: '2026-09-30T00:00:00.000Z',
      artifacts: [{ id: 'artifact-1', identifier: 'artifact-1', type: 'code', title: 'Draft', content: 'print(1)', version: 1 }],
    }]);
    selectedArtifactId.set('artifact-1');
    activeDrawer.set('artifacts');
  });

  afterEach(() => {
    cleanup();
    activeDrawer.set(null);
    messages.set([]);
  });

  it('lays the artifact panel over chat and closes from its control', async () => {
    render(ChatPane, { chatId: 'chat-1', workspaceId: 'workspace-1', onSend: () => {} });

    const drawer = screen.getByRole('complementary', { name: 'artifacts.panelLabel' });
    expect(drawer.className).toContain('absolute');
    expect(drawer.className).toContain('w-full');
    expect(screen.getByRole('button', { name: 'artifacts.close' })).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'artifacts.close' }));
    expect(get(activeDrawer)).toBeNull();
  });

  it('closes an open artifact panel with Escape', async () => {
    render(ChatPane, { chatId: 'chat-1', workspaceId: 'workspace-1', onSend: () => {} });
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(get(activeDrawer)).toBeNull();
  });
});
