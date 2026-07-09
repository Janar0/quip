import { api } from '$lib/api/client';
import type { ChatInfo } from '$lib/stores/chat';

export interface WorkspaceInfo {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  instructions: string | null;
  default_model: string | null;
  is_personal: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceFile {
  id: string;
  filename: string;
  content_type: string | null;
  size: number | null;
  file_type: string | null;
  embedding_status: string | null;
  created_at: string;
}

export interface WorkspaceOverview {
  workspace: WorkspaceInfo;
  chats: ChatInfo[];
  files: WorkspaceFile[];
}

export interface WorkspaceInput {
  name: string;
  description?: string | null;
  instructions?: string | null;
  default_model?: string | null;
}

export async function fetchWorkspaces(): Promise<WorkspaceInfo[]> {
  const response = await api('/api/workspaces');
  if (!response.ok) throw new Error('Unable to load workspaces');
  return response.json();
}

export async function createWorkspace(data: WorkspaceInput): Promise<WorkspaceInfo> {
  const response = await api('/api/workspaces', {
    method: 'POST',
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Unable to create workspace');
  return response.json();
}

export async function updateWorkspace(id: string, data: Partial<WorkspaceInput>): Promise<WorkspaceInfo> {
  const response = await api(`/api/workspaces/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Unable to update workspace');
  return response.json();
}

export async function deleteWorkspace(id: string): Promise<boolean> {
  const response = await api(`/api/workspaces/${id}`, { method: 'DELETE' });
  return response.ok;
}

export async function fetchWorkspaceOverview(id: string): Promise<WorkspaceOverview> {
  const response = await api(`/api/workspaces/${id}/overview`);
  if (!response.ok) throw new Error('Unable to load workspace');
  return response.json();
}
