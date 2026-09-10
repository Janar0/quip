import { processSSEStream, setStreamError } from './chat-stream';
import { api } from '$lib/api/client';
import { chatList, activeChat, messages, isStreaming, selectedModel, abortController, isLoading, searchEnabled, branchSelections, type AttachmentInfo, restoreBranchSelections, clearBranchSelections, persistBranchSelections } from '$lib/stores/chat';
import { buildThread } from '$lib/utils/thread';
import { get } from 'svelte/store';
import { t } from 'svelte-i18n';
import type { UploadedFile } from '$lib/api/files';
import { selectedWorkspaceId, selectWorkspace } from '$lib/stores/workspaces';

const CHAT_PAGE_SIZE = 50;
let chatOffset = 0;
let hasMoreChats = true;
let listVersion = 0;
let loadingMore = false;
let chatVersion = 0;

export async function loadChats(): Promise<void> {
  const version = ++listVersion;
  const workspaceId = get(selectedWorkspaceId);
  const scope = workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : '';
  const res = await api(`/api/chats?limit=${CHAT_PAGE_SIZE}&offset=0${scope}`);
  if (version !== listVersion || workspaceId !== get(selectedWorkspaceId)) return;
  if (res.ok) {
    const data = await res.json();
    if (version !== listVersion) return;
    chatList.set(data);
    chatOffset = data.length;
    hasMoreChats = data.length === CHAT_PAGE_SIZE;
  }
}

export function canLoadMoreChats(): boolean {
  return hasMoreChats && !loadingMore;
}

export async function loadMoreChats(): Promise<void> {
  if (!hasMoreChats || loadingMore) return;
  loadingMore = true;
  const version = listVersion;
  const workspaceId = get(selectedWorkspaceId);
  const scope = workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : '';
  try {
    const res = await api(`/api/chats?limit=${CHAT_PAGE_SIZE}&offset=${chatOffset}${scope}`);
    if (!res.ok || version !== listVersion || workspaceId !== get(selectedWorkspaceId)) return;
    const data = await res.json();
    if (version !== listVersion) return;
    chatList.update((existing) => {
      const ids = new Set(existing.map((chat) => chat.id));
      return [...existing, ...data.filter((chat: { id: string }) => !ids.has(chat.id))];
    });
    chatOffset += data.length;
    hasMoreChats = data.length === CHAT_PAGE_SIZE;
  } finally {
    loadingMore = false;
  }
}

export async function loadChat(chatId: string, options: { background?: boolean } = {}): Promise<void> {
  const version = ++chatVersion;
  if (!options.background) isLoading.set(true);
  try {
    const res = await api(`/api/chats/${chatId}`);
    if (res.ok) {
      const data = await res.json();
      if (version !== chatVersion) return;
      activeChat.set(data);
      if (data.workspace_id && data.workspace_id !== get(selectedWorkspaceId)) {
        selectWorkspace(data.workspace_id);
        await loadChats();
      }
      // Map tool_calls from DB to toolExecutions for UI, and search_images to searchImages
      const msgs = (data.messages ?? []).map((m: Record<string, unknown>) => {
        const mapped: Record<string, unknown> = { ...m };
        if (m.tool_calls && Array.isArray(m.tool_calls)) {
          mapped.toolExecutions = m.tool_calls;
          mapped.tool_calls = undefined;
        }
        if (m.search_images && Array.isArray(m.search_images)) {
          mapped.searchImages = m.search_images;
          mapped.search_images = undefined;
        }
        return mapped;
      });
      if (version !== chatVersion) return;
      for (const run of data.runs ?? []) {
        if (run.status === 'failed' && run.error) {
          const message = msgs.find((m: { id: string }) => m.id === run.assistant_message_id);
          if (message) message.error = run.error;
        }
      }
      if (JSON.stringify(get(messages)) !== JSON.stringify(msgs)) messages.set(msgs);
      if (!options.background) restoreBranchSelections(chatId);
    }
  } finally {
    if (version === chatVersion) isLoading.set(false);
  }
}

export async function deleteChat(chatId: string): Promise<void> {
  await api(`/api/chats/${chatId}`, { method: 'DELETE' });
  clearBranchSelections(chatId);
  await loadChats();
}

export async function renameChat(chatId: string, title: string): Promise<void> {
  await api(`/api/chats/${chatId}`, { method: 'PATCH', body: JSON.stringify({ title }) });
  await loadChats();
}

export async function togglePin(chatId: string, pinned: boolean): Promise<void> {
  await api(`/api/chats/${chatId}`, { method: 'PATCH', body: JSON.stringify({ pinned }) });
  await loadChats();
}

export interface SearchResult {
  id: string;
  title: string;
  snippet: string | null;
  updated_at: string | null;
}

export async function searchChats(query: string): Promise<SearchResult[]> {
  const workspaceId = get(selectedWorkspaceId);
  const scope = workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : '';
  const res = await api(`/api/chats/search/messages?q=${encodeURIComponent(query)}${scope}`);
  if (res.ok) {
    const data = await res.json();
    return data.results ?? [];
  }
  return [];
}

/** Fetch feature flags (search_enabled, etc.) */
export async function fetchFeatures(): Promise<void> {
  try {
    const res = await api('/api/models/features');
    if (res.ok) {
      const data = await res.json();
      searchEnabled.set(data.search_enabled ?? false);
    }
  } catch {
    // ignore
  }
}

/** Format a HTTP error detail, translating known codes */
function formatError(err: { detail: unknown }, status: number): string {
  if (status === 429 && err.detail && typeof err.detail === 'object') {
    const d = err.detail as { code?: string; current?: number; limit?: number; period?: string };
    if (d.code === 'budget_exceeded') {
      const periodKey = d.period === 'daily' ? 'admin.budgetDaily' : 'admin.budgetMonthly';
      return get(t)('error.budgetExceeded', {
        values: {
          current: (d.current ?? 0).toFixed(4),
          limit: (d.limit ?? 0).toFixed(4),
          period: get(t)(periodKey),
        },
      });
    }
  }
  return typeof err.detail === 'string' ? err.detail : `Request failed (HTTP ${status})`;
}

/** Stop the current generation */
export function stopGeneration(): void {
  const ctrl = get(abortController);
  if (ctrl) {
    ctrl.abort();
  }
}

/** Failed/aborted requests still need unique keys before the next send. */
function finalizeOptimisticMessages(): void {
  const ids = new Map([
    ['temp-user', `local-${crypto.randomUUID()}`],
    ['streaming', `local-${crypto.randomUUID()}`],
  ]);
  messages.update((items) => items.map((message) => ({
    ...message,
    id: ids.get(message.id) ?? message.id,
    parent_id: message.parent_id ? ids.get(message.parent_id) ?? message.parent_id : message.parent_id,
  })));
}

export async function streamChat(
  text: string,
  chatId?: string,
  fileIds?: string[],
  uploadedFiles?: UploadedFile[],
  branchFromMessageId?: string,
  workspaceId?: string,
): Promise<string | undefined> {
  if (get(isStreaming)) return;
  const model = get(selectedModel);
  const ctrl = new AbortController();
  abortController.set(ctrl);
  isStreaming.set(true);

  // Build attachment info for the temp user message
  const attachments: AttachmentInfo[] | undefined = uploadedFiles?.length
    ? uploadedFiles.map((f) => ({ file_id: f.id, filename: f.filename, file_type: f.file_type, content_type: f.content_type }))
    : undefined;

  // Compute current thread tail so optimistic temps attach as a continuation
  // rather than appearing as new root branches in the tree builder.
  const currentMsgs = get(messages);
  const currentThread = buildThread(currentMsgs, get(branchSelections));
  const tailId = currentThread.length ? currentThread[currentThread.length - 1].id : null;

  // Add user message with temp ID
  messages.update((msgs) => [
    ...msgs,
    {
      id: 'temp-user',
      chat_id: chatId ?? '',
      role: 'user' as const,
      content: text,
      parent_id: tailId,
      created_at: new Date().toISOString(),
      ...(attachments ? { attachments } : {}),
    },
  ]);

  // Add streaming assistant placeholder, chained to the temp user message
  messages.update((msgs) => [
    ...msgs,
    {
      id: 'streaming',
      chat_id: chatId ?? '',
      role: 'assistant' as const,
      content: '',
      model,
      parent_id: 'temp-user',
      created_at: new Date().toISOString(),
    },
  ]);

  try {
    const body: Record<string, unknown> = {
      chat_id: chatId || null, model, message: text,
      max_tokens: 4096,
    };
    if (fileIds?.length) body.file_ids = fileIds;
    if (workspaceId) body.workspace_id = workspaceId;
    if (branchFromMessageId) body.branch_from_message_id = branchFromMessageId;

    const res = await api('/api/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Request failed' }));
      setStreamError(undefined, formatError(err, res.status));
      return;
    }

    const ids = await processSSEStream(res);
    return ids.chatId;
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) {
      setStreamError(undefined, e instanceof Error ? e.message : String(e));
    }
  } finally {
    finalizeOptimisticMessages();
    isStreaming.set(false);
    abortController.set(null);
    await loadChats().catch(() => {});
  }
}

export async function regenerateMessage(chatId: string, messageId: string, model?: string): Promise<void> {
  if (get(isStreaming)) return;
  const selectedMdl = model || get(selectedModel);
  const ctrl = new AbortController();
  abortController.set(ctrl);
  isStreaming.set(true);

  // Find the old message to inherit its parent_id — the new regenerated response
  // must be a sibling of it (same parent = the user message that triggered both).
  const allMsgs = get(messages);
  const oldMsg = allMsgs.find((m) => m.id === messageId);
  const parentId = oldMsg?.parent_id;

  // Add a new streaming placeholder as a sibling. The old message stays in the
  // store, so the user can still navigate back to it via the branch navigator.
  messages.update((msgs) => [
    ...msgs,
    {
      id: 'streaming',
      chat_id: chatId,
      role: 'assistant' as const,
      content: '',
      model: selectedMdl,
      parent_id: parentId,
      created_at: new Date().toISOString(),
    },
  ]);

  try {
    const res = await api('/api/chat/regenerate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ chat_id: chatId, message_id: messageId, model: selectedMdl }),
      signal: ctrl.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Regenerate failed' }));
      setStreamError(undefined, formatError(err, res.status));
      return;
    }

    await processSSEStream(res);
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) {
      setStreamError(undefined, e instanceof Error ? e.message : String(e));
    }
  } finally {
    finalizeOptimisticMessages();
    isStreaming.set(false);
    abortController.set(null);
  }
}

/**
 * Edit a user message by branching: creates a sibling message with the new text
 * and streams a fresh AI response for it — the original message is preserved in
 * its own branch and can be navigated to via the < prev / next > controls.
 */
export async function editMessage(chatId: string, messageId: string, newContent: string): Promise<void> {
  // Pass the edited message's ID as branch_from_message_id — the backend looks up
  // its parent_id (which can be null for root messages) and uses that as the new
  // message's parent, making it a true sibling of the original.
  await streamChat(newContent, chatId, undefined, undefined, messageId);
  // Persist branch selections so the user's chosen fork survives page refresh.
  persistBranchSelections(chatId);
}
