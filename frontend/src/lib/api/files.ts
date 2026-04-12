import { api } from '$lib/api/client';
import { get } from 'svelte/store';
import { authToken } from '$lib/stores/auth';

export interface UploadedFile {
  id: string;
  filename: string;
  file_type: 'image' | 'document';
  content_type: string;
  size: number;
}

export async function uploadFiles(files: File[], chatId?: string): Promise<UploadedFile[]> {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  if (chatId) {
    formData.append('chat_id', chatId);
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
  const token = localStorage.getItem('access_token') || get(authToken) || '';
  return `/api/files/${fileId}?token=${encodeURIComponent(token)}`;
}

export async function deleteFile(fileId: string): Promise<boolean> {
  const res = await api(`/api/files/${fileId}`, { method: 'DELETE' });
  return res.ok;
}
