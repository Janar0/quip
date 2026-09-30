import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import ArtifactPanel from './ArtifactPanel.svelte';
import { messages, type MessageInfo } from '$lib/stores/chat';
import { selectedArtifactId } from '$lib/stores/artifacts';
import { activeDrawer } from '$lib/stores/drawer';

describe('ArtifactPanel theme states', () => {
  beforeEach(() => {
    messages.set([{
      id: 'assistant-1', chat_id: 'chat-1', role: 'assistant', content: '',
      artifacts: [{ id: 'artifact-1', identifier: 'artifact-1', type: 'code', title: 'Example', content: 'print(1)', language: 'python', version: 1 }],
    } as MessageInfo]);
    selectedArtifactId.set('artifact-1');
    activeDrawer.set('artifacts');
  });

  afterEach(() => {
    cleanup();
    messages.set([]);
    selectedArtifactId.set(null);
    activeDrawer.set(null);
  });

  it('shows a full contrast close action and closes the artifact drawer', async () => {
    const { container } = render(ArtifactPanel);
    const panel = container.querySelector('.quip-artifact-panel');
    const close = screen.getByRole('button', { name: 'artifacts.close' });
    expect(panel).toBeTruthy();
    expect(close.className).toContain('quip-theme-hover');
    expect(close.className).not.toContain('opacity-50');

    await fireEvent.click(close);
    expect(get(activeDrawer)).toBeNull();
  });
});
