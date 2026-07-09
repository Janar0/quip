import { derived, get, writable } from 'svelte/store';
import {
  createWorkspace as createWorkspaceRequest,
  fetchWorkspaces,
  type WorkspaceInfo,
  type WorkspaceInput,
} from '$lib/api/workspaces';

const STORAGE_KEY = 'quip_workspace';
const storedId = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;

export const workspaces = writable<WorkspaceInfo[]>([]);
export const selectedWorkspaceId = writable<string | null>(storedId);
export const workspacesLoading = writable(true);
export const selectedWorkspace = derived(
  [workspaces, selectedWorkspaceId],
  ([$workspaces, $selectedId]) => $workspaces.find((workspace) => workspace.id === $selectedId) ?? null,
);

selectedWorkspaceId.subscribe((id) => {
  if (typeof localStorage === 'undefined') return;
  if (id) localStorage.setItem(STORAGE_KEY, id);
  else localStorage.removeItem(STORAGE_KEY);
});

export function selectWorkspace(id: string): void {
  selectedWorkspaceId.set(id);
}

export async function loadWorkspaces(): Promise<WorkspaceInfo[]> {
  workspacesLoading.set(true);
  try {
    const items = await fetchWorkspaces();
    workspaces.set(items);
    const selectedId = get(selectedWorkspaceId);
    if (!selectedId || !items.some((workspace) => workspace.id === selectedId)) {
      const fallback = items.find((workspace) => workspace.is_personal) ?? items[0] ?? null;
      selectedWorkspaceId.set(fallback?.id ?? null);
    }
    return items;
  } finally {
    workspacesLoading.set(false);
  }
}

export async function addWorkspace(data: WorkspaceInput): Promise<WorkspaceInfo> {
  const created = await createWorkspaceRequest(data);
  workspaces.update((items) => [...items, created]);
  selectWorkspace(created.id);
  return created;
}
