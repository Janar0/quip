import { api } from '$lib/api/client';
import type { ResearchRunInfo } from '$lib/stores/chat';

interface ChatRunPayload {
  run_id: string;
  status: ResearchRunInfo['status'];
  revision: number;
  context_version: number;
  cancel_requested: boolean;
  snapshot: ResearchRunInfo['snapshot'];
  error?: string | null;
  message?: ResearchRunInfo['message'];
}

function toResearchRun(data: ChatRunPayload): ResearchRunInfo {
  return {
    runId: data.run_id,
    status: data.status,
    revision: data.revision,
    contextVersion: data.context_version,
    cancelRequested: data.cancel_requested,
    snapshot: data.snapshot ?? {},
    error: data.error,
    message: data.message ?? null,
  };
}

export class ChatRunRequestError extends Error {
  constructor(readonly status: number, detail: string) {
    super(detail);
    this.name = 'ChatRunRequestError';
  }
}

export async function getChatRun(chatId: string, runId: string): Promise<ResearchRunInfo | null> {
  const response = await api(`/api/chats/${encodeURIComponent(chatId)}/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) return null;
  return toResearchRun(await response.json() as ChatRunPayload);
}

export async function cancelChatRun(chatId: string, runId: string): Promise<ResearchRunInfo> {
  const response = await api(`/api/chats/${encodeURIComponent(chatId)}/runs/${encodeURIComponent(runId)}/cancel`, {
    method: 'POST',
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    const detail = typeof body?.detail === 'string'
      ? body.detail
      : `Stop request failed (HTTP ${response.status})`;
    throw new ChatRunRequestError(response.status, detail);
  }
  const body = await response.json() as { run?: ChatRunPayload };
  if (!body.run) throw new Error('Stop request returned no run state');
  return toResearchRun(body.run);
}

export async function steerChatRun(chatId: string, runId: string, instruction: string): Promise<boolean> {
  const response = await api(`/api/chats/${encodeURIComponent(chatId)}/runs/${encodeURIComponent(runId)}/steer`, {
    method: 'POST',
    body: JSON.stringify({ instruction }),
  });
  return response.ok;
}
