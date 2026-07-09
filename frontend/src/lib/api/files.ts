import { api } from '$lib/api/client';

export interface UploadedFile {
  id: string;
  filename: string;
  file_type: 'image' | 'document' | 'video';
  content_type: string;
  size: number;
}

export async function uploadFiles(files: File[], chatId?: string, workspaceId?: string): Promise<UploadedFile[]> {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  if (chatId) {
    formData.append('chat_id', chatId);
  }
  if (workspaceId) {
    formData.append('workspace_id', workspaceId);
  }
  const res = await api('/api/files/upload', {
    method: 'POST',
    body: formData,
  });
  if (res.ok) {
    const data = await res.json();
    return data.files ?? [];
  }
  throw new Error('Upload failed');
}

export function getFileUrl(fileId: string): string {
  return `/api/files/${fileId}`;
}

export function getGeneratedImageUrl(path: string): string {
  return path;
}

export function getGeneratedAudioUrl(path: string): string {
  return path;
}

export async function deleteFile(fileId: string): Promise<boolean> {
  const res = await api(`/api/files/${fileId}`, { method: 'DELETE' });
  return res.ok;
}
