import { api } from '$lib/api/client';

export interface SandboxFile {
  name: string;
  path: string;
  size: number;
  is_dir: boolean;
}

export async function listFiles(chatId: string, path = '.'): Promise<SandboxFile[]> {
  const res = await api(`/api/sandbox/${chatId}/files?path=${encodeURIComponent(path)}`);
  if (res.ok) {
    const data = await res.json();
    return data.files ?? [];
  }
  return [];
}

export async function uploadFile(chatId: string, file: File): Promise<boolean> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api(`/api/sandbox/${chatId}/upload`, {
    method: 'POST',
    body: formData,
  });
  return res.ok;
}

export function getFileUrl(chatId: string, path: string): string {
  const token = localStorage.getItem('access_token');
  return `/api/sandbox/${chatId}/file/${encodeURIComponent(path)}?token=${token}`;
}
