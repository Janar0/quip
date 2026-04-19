import { api } from '$lib/api/client';
import { chatList, activeChat, messages, isStreaming, selectedModel, abortController, isLoading, searchEnabled, modePreference, type MessageInfo, type AttachmentInfo, type ResearchStatusInfo, type SearchImageInfo, type ContentBlock } from '$lib/stores/chat';
import { extractStreamingArtifacts } from '$lib/utils/artifacts';
import { get } from 'svelte/store';
import { t } from 'svelte-i18n';
import type { UploadedFile } from '$lib/api/files';

const CHAT_PAGE_SIZE = 50;
let chatOffset = 0;
let hasMoreChats = true;

export async function loadChats(): Promise<void> {
  chatOffset = 0;
  hasMoreChats = true;
  const res = await api(`/api/chats?limit=${CHAT_PAGE_SIZE}&offset=0`);
  if (res.ok) {
    const data: unknown[] = await res.json();
    chatList.set(data as import('$lib/stores/chat').ChatInfo[]);
    hasMoreChats = data.length === CHAT_PAGE_SIZE;
  }
}

export function canLoadMoreChats(): boolean {
  return hasMoreChats;
}

export async function loadMoreChats(): Promise<void> {
  if (!hasMoreChats) return;
  chatOffset += CHAT_PAGE_SIZE;
  const res = await api(`/api/chats?limit=${CHAT_PAGE_SIZE}&offset=${chatOffset}`);
  if (res.ok) {
    const data: unknown[] = await res.json();
    chatList.update((existing) => [...existing, ...(data as import('$lib/stores/chat').ChatInfo[])]);
    hasMoreChats = data.length === CHAT_PAGE_SIZE;
  }
}

export async function loadChat(chatId: string): Promise<void> {
  isLoading.set(true);
  try {
    const res = await api(`/api/chats/${chatId}`);
    if (res.ok) {
      const data = await res.json();
      activeChat.set(data);
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
      messages.set(msgs);
    }
  } finally {
    isLoading.set(false);
  }
}

export async function deleteChat(chatId: string): Promise<void> {
  await api(`/api/chats/${chatId}`, { method: 'DELETE' });
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
  const res = await api(`/api/chats/search/messages?q=${encodeURIComponent(query)}`);
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
  return typeof err.detail === 'string' ? err.detail : (err.detail as string | undefined) ?? 'Unknown error';
}

/** Stop the current generation */
export function stopGeneration(): void {
  const ctrl = get(abortController);
  if (ctrl) {
    ctrl.abort();
    abortController.set(null);
  }
  isStreaming.set(false);
}

/** Parse SSE stream, update the streaming message, return real message IDs */
async function processSSEStream(
  response: Response,
): Promise<{ chatId?: string; userMessageId?: string; messageId?: string }> {
  const reader = response.body?.getReader();
  if (!reader) return {};

  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = '';
  let fullContent = '';
  let fullReasoning = '';
  let contentBlocks: ContentBlock[] = [];
  let chatId: string | undefined;
  let userMessageId: string | undefined;
  let messageId: string | undefined;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      while (buffer.includes('\n')) {
        const idx = buffer.indexOf('\n');
        const line = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 1);

        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));

            if (currentEvent === 'chat') {
              chatId = data.chat_id;
              messageId = data.message_id;
              userMessageId = data.user_message_id;
              const userParentId: string | null = data.user_parent_id ?? null;
              // Set real IDs and parent_ids in one pass — prevents temp messages from
              // appearing as false roots in the branch tree builder.
              // For regenerate flow, userMessageId is undefined and the streaming
              // placeholder already has its parent_id set — preserve it.
              messages.update((msgs) =>
                msgs.map((m) => {
                  if (m.id === 'streaming') {
                    return {
                      ...m,
                      id: messageId!,
                      chat_id: chatId!,
                      parent_id: userMessageId ?? m.parent_id,
                    };
                  }
                  if (m.id === 'temp-user') {
                    return { ...m, id: userMessageId!, parent_id: userParentId };
                  }
                  return m;
                })
              );
            } else if (currentEvent === 'reasoning') {
              fullReasoning += data.text;
              updateStreamingContent(messageId, fullContent, fullReasoning);
            } else if (currentEvent === 'content') {
              fullContent += data.text;
              // Track text in content blocks
              const lastBlock = contentBlocks[contentBlocks.length - 1];
              if (lastBlock?.type === 'text') {
                contentBlocks[contentBlocks.length - 1] = { type: 'text', content: lastBlock.content + data.text };
              } else {
                contentBlocks = [...contentBlocks, { type: 'text', content: data.text }];
              }
              updateStreamingContent(messageId, fullContent, fullReasoning, contentBlocks);
              // Detect completed artifact tags during streaming
              const streamArtifacts = extractStreamingArtifacts(fullContent);
              const completed = streamArtifacts.filter((a) => a.isComplete);
              if (completed.length > 0) {
                const artifacts = completed.map((a, i) => ({
                  id: `stream-${i}-${a.identifier}`,
                  identifier: a.identifier,
                  type: a.type,
                  title: a.title,
                  content: a.content,
                  language: a.language,
                  version: 1,
                }));
                const targetId = messageId || 'streaming';
                messages.update((msgs) =>
                  msgs.map((m) => (m.id === targetId ? { ...m, artifacts } : m)),
                );
              }
            } else if (currentEvent === 'tool_executing') {
              // Add tool block to content blocks (before any subsequent text)
              contentBlocks = [...contentBlocks, { type: 'tool', executionId: data.id }];
              const targetId = messageId || 'streaming';
              messages.update((msgs) =>
                msgs.map((m) => {
                  if (m.id !== targetId) return m;
                  const execs = [...(m.toolExecutions ?? [])];
                  execs.push({
                    id: data.id,
                    name: data.name,
                    arguments: data.arguments,
                    status: 'running' as const,
                  });
                  return { ...m, toolExecutions: execs, contentBlocks };
                }),
              );
            } else if (currentEvent === 'tool_result') {
              const targetId = messageId || 'streaming';
              let parsedResult;
              try {
                parsedResult = typeof data.result === 'string' ? JSON.parse(data.result) : data.result;
              } catch {
                parsedResult = { stdout: String(data.result), stderr: '', exit_code: 0, files_created: [] };
              }
              const toolStatus = data.status === 'error' ? 'error' as const : 'completed' as const;
              messages.update((msgs) =>
                msgs.map((m) => {
                  if (m.id !== targetId) return m;
                  const execs = (m.toolExecutions ?? []).map((e) =>
                    e.id === data.id ? { ...e, status: toolStatus, result: parsedResult } : e,
                  );
                  return { ...m, toolExecutions: execs };
                }),
              );
            } else if (currentEvent === 'search_images') {
              const targetId = messageId || 'streaming';
              const imgs = (data.images ?? []) as SearchImageInfo[];
              const append = data.append === true;
              messages.update((msgs) =>
                msgs.map((m) => {
                  if (m.id !== targetId) return m;
                  if (append && m.searchImages?.length) {
                    const seen = new Set(m.searchImages.map((i) => i.img_src));
                    const merged = [
                      ...m.searchImages,
                      ...imgs.filter((i) => !seen.has(i.img_src)),
                    ].slice(0, 10);
                    return { ...m, searchImages: merged };
                  }
                  return { ...m, searchImages: imgs };
                }),
              );
            } else if (currentEvent === 'research_status') {
              const targetId = messageId || 'streaming';
              const status = data as ResearchStatusInfo;
              messages.update((msgs) =>
                msgs.map((m) => {
                  if (m.id !== targetId) return m;
                  const history = [...(m.researchHistory ?? [])];
                  // Append to history if it's a new phase
                  if (!history.length || history[history.length - 1].phase !== status.phase) {
                    history.push(status);
                  } else {
                    history[history.length - 1] = status;
                  }
                  return { ...m, researchStatus: status, researchHistory: history };
                }),
              );
            } else if (currentEvent === 'usage') {
              const targetId = messageId || 'streaming';
              messages.update((msgs) =>
                msgs.map((m) =>
                  m.id === targetId
                    ? { ...m, cost: data.cost ?? m.cost, provider: data.provider ?? m.provider }
                    : m,
                ),
              );
            } else if (currentEvent === 'error') {
              updateStreamingContent(messageId, `Error: ${data.message}`);
            } else if (currentEvent === 'title') {
              const realId = chatId;
              if (realId && data.title) {
                chatList.update((list) =>
                  list.map((c) => (c.id === realId ? { ...c, title: data.title } : c)),
                );
                activeChat.update((c) => (c?.id === realId ? { ...c, title: data.title } : c));
              }
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    }
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) {
      throw e;
    }
  }

  // If model sent only reasoning with no content, promote reasoning to content
  if (!fullContent && fullReasoning) {
    fullContent = fullReasoning;
    fullReasoning = '';
    updateStreamingContent(messageId, fullContent, undefined);
  }

  return { chatId, userMessageId, messageId };
}

function updateStreamingContent(
  messageId: string | undefined,
  content: string,
  reasoning?: string,
  contentBlocks?: ContentBlock[],
) {
  const targetId = messageId || 'streaming';
  messages.update((msgs) =>
    msgs.map((m) => {
      if (m.id !== targetId) return m;
      return contentBlocks !== undefined
        ? { ...m, content, reasoning, contentBlocks }
        : { ...m, content, reasoning };
    }),
  );
}

export async function streamChat(text: string, chatId?: string, fileIds?: string[], uploadedFiles?: UploadedFile[], branchFromMessageId?: string): Promise<string | undefined> {
  const model = get(selectedModel);
  const mode = get(modePreference);
  const ctrl = new AbortController();
  abortController.set(ctrl);
  isStreaming.set(true);

  // Build attachment info for the temp user message
  const attachments: AttachmentInfo[] | undefined = uploadedFiles?.length
    ? uploadedFiles.map((f) => ({ file_id: f.id, filename: f.filename, file_type: f.file_type, content_type: f.content_type }))
    : undefined;

  // Add user message with temp ID
  messages.update((msgs) => [
    ...msgs,
    {
      id: 'temp-user',
      chat_id: chatId ?? '',
      role: 'user' as const,
      content: text,
      created_at: new Date().toISOString(),
      ...(attachments ? { attachments } : {}),
    },
  ]);

  // Add streaming assistant placeholder
  messages.update((msgs) => [
    ...msgs,
    {
      id: 'streaming',
      chat_id: chatId ?? '',
      role: 'assistant' as const,
      content: '',
      model,
      created_at: new Date().toISOString(),
    },
  ]);

  try {
    const body: Record<string, unknown> = { chat_id: chatId || null, model, message: text };
    if (fileIds?.length) body.file_ids = fileIds;
    if (mode !== 'auto') body.mode_hint = mode;
    if (branchFromMessageId) body.branch_from_message_id = branchFromMessageId;

    const res = await fetch('/api/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Request failed' }));
      updateStreamingContent(undefined, `Error: ${formatError(err, res.status)}`);
      return;
    }

    const ids = await processSSEStream(res);
    return ids.chatId;
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) {
      updateStreamingContent(undefined, `Error: ${e}`);
    }
  } finally {
    isStreaming.set(false);
    abortController.set(null);
    await loadChats();
  }
}

export async function regenerateMessage(chatId: string, messageId: string, model?: string): Promise<void> {
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
    const res = await fetch('/api/chat/regenerate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ chat_id: chatId, message_id: messageId, model: selectedMdl }),
      signal: ctrl.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Regenerate failed' }));
      updateStreamingContent(undefined, `Error: ${formatError(err, res.status)}`);
      return;
    }

    await processSSEStream(res);
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) {
      updateStreamingContent(undefined, `Error: ${e}`);
    }
  } finally {
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
}
