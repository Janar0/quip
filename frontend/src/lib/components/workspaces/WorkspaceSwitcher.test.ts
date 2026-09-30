import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WorkspaceSwitcher from './WorkspaceSwitcher.svelte';
import { get } from 'svelte/store';
import { selectedWorkspaceId, workspaces } from '$lib/stores/workspaces';

vi.mock('$app/navigation', () => ({ goto: vi.fn().mockResolvedValue(undefined) }));
import { goto } from '$app/navigation';

describe('WorkspaceSwitcher', () => {
  beforeEach(() => {
    workspaces.set([
      { id: 'personal', owner_id: 'user-1', name: 'Personal', description: null, instructions: null, default_model: null, is_personal: true, created_at: '', updated_at: '' },
      { id: 'team', owner_id: 'user-1', name: 'Research team', description: null, instructions: null, default_model: null, is_personal: false, created_at: '', updated_at: '' },
    ]);
    selectedWorkspaceId.set('personal');
  });

  afterEach(() => {
    cleanup();
    vi.mocked(goto).mockClear();
  });

  it('renders its open workspace menu above the clipped sidebar layer', async () => {
    const { container } = render(WorkspaceSwitcher);
    await fireEvent.click(screen.getByRole('button', { name: /Workspace.*Personal/i }));

    const menu = screen.getByRole('dialog', { name: 'workspace.label' });
    expect(menu.parentElement).toBe(document.body);
    expect(container.contains(menu)).toBe(false);
    expect(screen.getByRole('button', { name: /Research team/i })).toBeTruthy();
    const personalItem = [...menu.querySelectorAll('button')].find((button) => button.textContent?.includes('Personal'));
    expect(personalItem?.className).toContain('quip-theme-hover');
    expect(personalItem?.className).toContain('quip-theme-selected');

    await fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'workspace.label' })).toBeNull();
  });

  it('selects a workspace and follows the navigation handler', async () => {
    const onchange = vi.fn().mockResolvedValue(undefined);
    render(WorkspaceSwitcher, { onchange });
    await fireEvent.click(screen.getByRole('button', { name: /Workspace.*Personal/i }));
    await fireEvent.click(screen.getByRole('button', { name: /Research team/i }));

    expect(get(selectedWorkspaceId)).toBe('team');
    expect(onchange).toHaveBeenCalledOnce();
    expect(goto).toHaveBeenCalledWith('/workspace/team');
  });

  it('keeps the workspace popover inside a narrow viewport', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 300 });
    render(WorkspaceSwitcher);
    const trigger = screen.getByRole('button', { name: /Workspace.*Personal/i });
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
      x: 12, y: 20, width: 232, height: 52, top: 20, right: 244, bottom: 72, left: 12,
      toJSON: () => ({}),
    } as DOMRect);
    await fireEvent.click(trigger);

    const menu = screen.getByRole('dialog', { name: 'workspace.label' });
    expect(menu.getAttribute('style')).toContain('left: 8px');
    expect(menu.getAttribute('style')).toContain('width: 280px');
    expect(menu.getAttribute('style')).toContain('max-height: 212px');
  });
});
