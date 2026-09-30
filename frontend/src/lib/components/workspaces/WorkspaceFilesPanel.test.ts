import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import WorkspaceFilesPanel from './WorkspaceFilesPanel.svelte';
import { activeDrawer } from '$lib/stores/drawer';

const { fetchWorkspaceOverview } = vi.hoisted(() => ({ fetchWorkspaceOverview: vi.fn() }));
vi.mock('$lib/api/workspaces', () => ({ fetchWorkspaceOverview }));
vi.mock('$lib/api/files', () => ({ getFileUrl: (id: string) => `/api/files/${id}` }));

describe('WorkspaceFilesPanel', () => {
  beforeEach(() => {
    fetchWorkspaceOverview.mockReset().mockResolvedValue({
      files: [{ id: 'file-1', filename: 'analysis.pdf', size: 1_024, embedding_status: 'completed' }],
    });
    activeDrawer.set('files');
  });

  afterEach(() => {
    cleanup();
    activeDrawer.set(null);
  });

  it('shows saved workspace files and closes through its visible control', async () => {
    render(WorkspaceFilesPanel, { workspaceId: 'workspace-1' });
    const file = await screen.findByRole('link', { name: /analysis\.pdf/i });

    expect(fetchWorkspaceOverview).toHaveBeenCalledWith('workspace-1');
    expect(file.getAttribute('href')).toBe('/api/files/file-1');
    expect(file.className).toContain('quip-theme-hover');
    expect(screen.getByText(/workspace.embeddingCompleted/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(get(activeDrawer)).toBeNull();
  });

  it('shows an error state when workspace files cannot be loaded', async () => {
    fetchWorkspaceOverview.mockRejectedValueOnce(new Error('offline'));
    render(WorkspaceFilesPanel, { workspaceId: 'workspace-1' });

    await waitFor(() => expect(screen.getByText('workspace.filesLoadError')).toBeTruthy());
    expect(screen.queryByText('workspace.noFiles')).toBeNull();
  });
});
