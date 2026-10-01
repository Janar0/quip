import { processSSEStream, setStreamError } from './chat-stream';
import { api } from '$lib/api/client';
import { chatList, activeChat, activeChatId, messages, selectedModel, isLoading, searchEnabled, researchEnabled, branchSelections, chatStreamKey, setActiveChatId, setChatStreamState, remapChatStreamState, type AttachmentInfo, type MessageInfo, type ResearchRunInfo, type ResearchRunStatus, restoreBranchSelections, clearBranchSelections, persistBranchSelections } from '$lib/stores/chat';
import { buildThread } from '$lib/utils/thread';
import { get, writable, type Writable } from 'svelte/store';
import { t } from 'svelte-i18n';
import type { UploadedFile } from '$lib/api/files';
import { selectedWorkspaceId, selectWorkspace } from '$lib/stores/workspaces';
import { cancelChatRun, ChatRunRequestError, getChatRun } from '$lib/api/chat-runs';

let researchPollTimer: ReturnType<typeof setInterval> | null = null;
let researchPollChatId: string | null = null;
let researchReportRequestSequence = 0;
type PendingResearchRequest = {
  chatId?: string;
  runId?: string;
  stopRequested: boolean;
  cancelSent: boolean;
};

type ChatStreamContext = {
  key: string;
  chatId?: string;
  messages: Writable<MessageInfo[]>;
  controller: AbortController;
  messageId: string | null;
  userMessageId: string | null;
  pendingResearchRequest: PendingResearchRequest | null;
  unsubscribe?: () => void;
};

const chatStreams = new Map<string, ChatStreamContext>();

function streamContextForChat(chatId: string | null | undefined): ChatStreamContext | undefined {
  return chatStreams.get(chatStreamKey(chatId));
}

function currentStreamContext(): ChatStreamContext | undefined {
  return streamContextForChat(get(activeChatId));
}

function createStreamContext(
  chatId: string | undefined,
  initialMessages: MessageInfo[],
): ChatStreamContext | null {
  const key = chatStreamKey(chatId);
  if (chatStreams.has(key)) return null;

  const context: ChatStreamContext = {
    key,
    chatId,
    messages: writable([...initialMessages]),
    controller: new AbortController(),
    messageId: null,
    userMessageId: null,
    pendingResearchRequest: null,
  };
  context.unsubscribe = context.messages.subscribe((items) => {
    if (chatStreamKey(get(activeChatId)) === context.key) messages.set(items);
  });
  chatStreams.set(key, context);
  setChatStreamState(key, true, context.controller);
  return context;
}

function remapStreamContext(context: ChatStreamContext, chatId: string): void {
  const nextKey = chatStreamKey(chatId);
  if (context.key === nextKey) return;
  if (chatStreams.has(nextKey)) return;
  const previousKey = context.key;
  chatStreams.delete(previousKey);
  context.key = nextKey;
  context.chatId = chatId;
  chatStreams.set(nextKey, context);
  remapChatStreamState(previousKey, nextKey);
}

function releaseStreamContext(context: ChatStreamContext): void {
  if (chatStreams.get(context.key) === context) chatStreams.delete(context.key);
  context.unsubscribe?.();
  setChatStreamState(context.key, false, null);
}

function activeStreamMessageId(chatId: string | null | undefined): string | null {
  return streamContextForChat(chatId)?.messageId ?? null;
}

export function enterNewChatView(): void {
  const previousDraft = chatStreams.get(chatStreamKey(null));
  if (previousDraft) remapStreamContext(previousDraft, `__background_draft__${crypto.randomUUID()}`);
  chatVersion += 1;
  setActiveChatId(null);
  activeChat.set(null);
  messages.set([]);
  branchSelections.set({});
  isLoading.set(false);
  stopResearchPolling();
}

function isActiveResearch(status: ResearchRunStatus): boolean {
  return status === 'queued' || status === 'running' || status === 'cancelling';
}

type ResearchReportFreshness = {
  requestId: number;
  streamedContentAtRequest: string | null;
  statusAtRequest: ResearchRunStatus | null;
  contentAtRequest: string | null;
};

function newResearchReportFreshness(
  message: Pick<MessageInfo, 'content' | 'research'> | undefined,
  fallbackStatus: ResearchRunStatus | null = null,
): ResearchReportFreshness {
  return {
    requestId: ++researchReportRequestSequence,
    streamedContentAtRequest: message?.research?.streamedContent ?? null,
    statusAtRequest: message?.research?.status ?? fallbackStatus,
    contentAtRequest: message?.content ?? null,
  };
}

function messageStoreForRun(runId: string): Writable<MessageInfo[]> {
  for (const context of chatStreams.values()) {
    if (get(context.messages).some((message) => message.research?.runId === runId)) return context.messages;
  }
  return messages;
}

function applyResearchRun(runId: string, run: ResearchRunInfo, freshness: ResearchReportFreshness): void {
  messageStoreForRun(runId).update((items) => items.map((message) => {
    if (
      message.research?.runId !== runId
      || message.research.revision > run.revision
      || (message.research.reportSyncRequestId ?? 0) > freshness.requestId
    ) return message;
    return projectResearchRun(message, run, activeStreamMessageId(message.chat_id), freshness);
  }));
}

function projectResearchRun(
  message: MessageInfo,
  run: ResearchRunInfo,
  streamingMessageId: string | null,
  freshness: ResearchReportFreshness,
): MessageInfo {
  if (
    message.research?.runId === run.runId
    && (
      message.research.revision > run.revision
      || (message.research.reportSyncRequestId ?? 0) > freshness.requestId
    )
  ) return message;
  const saved = run.message;
  const previousSaved = message.research?.message;
  const localTextCameFromStream = message.research?.streamedContent === message.content;
  const sameMessageStreaming = streamingMessageId === message.id;
  const currentStatus = message.research?.status ?? freshness.statusAtRequest;
  const streamUnchangedSinceRequest = freshness.streamedContentAtRequest === (message.research?.streamedContent ?? null);
  const statusUnchangedSinceRequest = freshness.statusAtRequest === currentStatus;
  const responseIsCurrent = freshness.requestId >= (message.research?.reportSyncRequestId ?? 0);
  const canSyncReport = streamUnchangedSinceRequest
    && statusUnchangedSinceRequest
    && responseIsCurrent
    && (!sameMessageStreaming || !isActiveResearch(run.status))
    && message.role === 'assistant'
    && saved?.id === message.id
    && (!previousSaved || message.content === previousSaved.content || localTextCameFromStream);
  const projectedResearch: ResearchRunInfo = {
    ...run,
    status: statusUnchangedSinceRequest ? run.status : currentStatus ?? run.status,
    reportSyncStreamedContent: freshness.streamedContentAtRequest,
    reportSyncStatusAtRequest: freshness.statusAtRequest,
    reportSyncRequestId: freshness.requestId,
    ...(message.research?.streamedContent !== undefined
      ? { streamedContent: message.research.streamedContent }
      : {}),
  };
  return canSyncReport
    ? { ...message, content: saved.content, artifacts: saved.artifacts ?? message.artifacts, research: projectedResearch }
    : { ...message, research: projectedResearch };
}

function syncPendingResearchReports(
  targetMessages: Writable<MessageInfo[]> = messages,
  streamingMessageIdOverride?: string | null,
): void {
  targetMessages.update((items) => items.map((message) => {
    if (!message.research) return message;
    const freshness = {
      requestId: message.research.reportSyncRequestId ?? 0,
      streamedContentAtRequest: Object.prototype.hasOwnProperty.call(message.research, 'reportSyncStreamedContent')
        ? message.research.reportSyncStreamedContent ?? null
        : message.research.streamedContent ?? null,
      statusAtRequest: Object.prototype.hasOwnProperty.call(message.research, 'reportSyncStatusAtRequest')
        ? message.research.reportSyncStatusAtRequest ?? null
        : message.research.status,
      contentAtRequest: message.content,
    };
    return projectResearchRun(
      message,
      message.research,
      streamingMessageIdOverride === undefined
        ? activeStreamMessageId(message.chat_id)
        : streamingMessageIdOverride,
      freshness,
    );
  }));
}

function syncResearchPolling(chatId: string): void {
  const hasActive = get(messages).some((message) => message.research && isActiveResearch(message.research.status));
  if (!hasActive) {
    stopResearchPolling();
    return;
  }
  if (researchPollTimer && researchPollChatId === chatId) return;
  stopResearchPolling();
  researchPollChatId = chatId;
  researchPollTimer = setInterval(() => { void refreshResearchRunStates(chatId); }, 2500);
}

export function stopResearchPolling(chatId?: string): void {
  if (chatId && researchPollChatId !== chatId) return;
  if (researchPollTimer) clearInterval(researchPollTimer);
  researchPollTimer = null;
  researchPollChatId = null;
}

async function refreshResearchRunStates(chatId: string): Promise<void> {
  if (get(activeChat)?.id !== chatId) {
    stopResearchPolling(chatId);
    return;
  }
  const running = get(messages).filter((message) => message.research && isActiveResearch(message.research.status));
  if (!running.length) {
    stopResearchPolling(chatId);
    return;
  }
  await Promise.all(running.map(async (message) => {
    const run = message.research;
    if (!run) return;
    const freshness = newResearchReportFreshness(message);
    const fresh = await getChatRun(chatId, run.runId).catch(() => null);
    if (fresh && get(activeChat)?.id === chatId) applyResearchRun(run.runId, fresh, freshness);
  }));
  syncResearchPolling(chatId);
}

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
  if (!options.background) setActiveChatId(chatId);
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
        if (['failed', 'partial', 'interrupted'].includes(run.status) && run.error) {
          const message = msgs.find((m: { id: string }) => m.id === run.assistant_message_id);
          if (message) message.error = run.error;
        }
      }
      const streamContext = streamContextForChat(chatId);
      if (streamContext) {
        const localMessages = get(streamContext.messages);
        const localById = new Map(localMessages.map((message) => [message.id, message]));
        const liveMessageIds = new Set(
          ['temp-user', 'streaming', streamContext.userMessageId, streamContext.messageId]
            .filter((id): id is string => typeof id === 'string'),
        );
        for (let i = 0; i < msgs.length; i++) {
          const local = localById.get((msgs[i] as { id: string }).id);
          if (local && liveMessageIds.has(local.id)) {
            const toolExecutions = local.toolExecutions
              ? [...new Map(local.toolExecutions.map((execution) => [execution.id, execution])).values()]
              : undefined;
            msgs[i] = {
              ...msgs[i],
              ...local,
              ...(toolExecutions ? { toolExecutions } : {}),
            };
          }
        }
        const persistedIds = new Set(msgs.map((message: { id: string }) => message.id));
        for (const local of localMessages) {
          if (liveMessageIds.has(local.id) && !persistedIds.has(local.id)) {
            msgs.push(local);
          }
        }
      }
      const researchRuns = (data.runs ?? []).filter((run: { task_kind?: string; assistant_message_id?: string; status?: ResearchRunStatus }) =>
        run.task_kind === 'research' && msgs.some((message: { id: string }) => message.id === run.assistant_message_id),
      );
      const runStates = await Promise.all(researchRuns.map(async (run: { id: string; assistant_message_id: string; status: ResearchRunStatus }) => {
        const storedMessage = (streamContext ? get(streamContext.messages) : get(messages))
          .find((message) => message.id === run.assistant_message_id);
        const localMessage = storedMessage?.chat_id === chatId ? storedMessage : undefined;
        const loadedMessage = msgs.find((message: { id: string }) => message.id === run.assistant_message_id) as MessageInfo | undefined;
        const freshness = newResearchReportFreshness(localMessage ?? loadedMessage, localMessage?.research?.status ?? run.status);
        return {
          runId: run.id,
          freshness,
          state: await getChatRun(chatId, run.id).catch(() => null),
        };
      }));
      if (version !== chatVersion) return;
      for (const { runId, state, freshness } of runStates) {
        if (!state) continue;
        const assistantMessageId = researchRuns.find((run: { id: string; assistant_message_id: string }) => run.id === runId)?.assistant_message_id;
        const message = msgs.find((item: { research?: ResearchRunInfo }) => item.research?.runId === runId)
          ?? msgs.find((item: { id: string }) => item.id === assistantMessageId);
        if (!message) continue;
        const latestLocal = (streamContext ? get(streamContext.messages) : get(messages))
          .find((item) => item.id === assistantMessageId && item.chat_id === chatId);
        let projectionBase = message as MessageInfo;
        if (latestLocal && latestLocal.research && latestLocal.research.runId === runId) {
          const latestResearch = latestLocal.research;
          const localChangedWhileLoading = (
            latestLocal.content !== freshness.contentAtRequest
            || (latestResearch.streamedContent ?? null) !== freshness.streamedContentAtRequest
            || latestResearch.status !== freshness.statusAtRequest
          );
          if (localChangedWhileLoading) projectionBase = latestLocal;
        }
        Object.assign(message, projectResearchRun(
          projectionBase,
          state,
          streamContext?.messageId ?? null,
          freshness,
        ));
      }
      if (streamContext) streamContext.messages.set(msgs);
      else if (JSON.stringify(get(messages)) !== JSON.stringify(msgs)) messages.set(msgs);
      syncResearchPolling(chatId);
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
      researchEnabled.set(data.research_enabled ?? false);
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
export async function stopResearchRun(chatId: string, runId: string): Promise<void> {
  const targetMessages = messageStoreForRun(runId);
  const initialMessage = get(targetMessages).find((message) => message.research?.runId === runId);
  const freshness = newResearchReportFreshness(initialMessage);
  try {
    const state = await cancelChatRun(chatId, runId);
    applyResearchRun(runId, state, freshness);
  } catch (error) {
    const actualState = await getChatRun(chatId, runId).catch(() => null);
    if (actualState) {
      applyResearchRun(runId, actualState, freshness);
    }
    const status = error instanceof ChatRunRequestError ? ` (HTTP ${error.status})` : '';
    const detail = error instanceof Error ? error.message : String(error);
    targetMessages.update((items) => items.map((message) => message.research?.runId === runId
      ? { ...message, error: `Stop request failed${status}: ${detail}` }
      : message));
  }
}

/** Stop active research durably; ordinary streams keep their abort behavior. */
export async function stopGeneration(): Promise<void> {
  const context = currentStreamContext();
  const pendingResearchRequest = context?.pendingResearchRequest;
  if (pendingResearchRequest) {
    // Keep the SSE handshake alive. The first `chat` event identifies the
    // durable run, after which this pending Stop is sent through the API.
    pendingResearchRequest.stopRequested = true;
    if (
      pendingResearchRequest.chatId
      && pendingResearchRequest.runId
      && !pendingResearchRequest.cancelSent
    ) {
      pendingResearchRequest.cancelSent = true;
      await stopResearchRun(pendingResearchRequest.chatId, pendingResearchRequest.runId);
    }
    return;
  }
  if (context) {
    context.controller.abort();
    return;
  }
  const activeResearch = [...get(messages)].reverse().find((message) =>
    message.research && isActiveResearch(message.research.status),
  );
  if (activeResearch?.research) {
    await stopResearchRun(activeResearch.chat_id, activeResearch.research.runId);
  }
}

/** Failed/aborted requests still need unique keys before the next send. */
function finalizeOptimisticMessages(targetMessages: Writable<MessageInfo[]>): void {
  const ids = new Map([
    ['temp-user', `local-${crypto.randomUUID()}`],
    ['streaming', `local-${crypto.randomUUID()}`],
  ]);
  targetMessages.update((items) => items.map((message) => ({
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
  modeHint?: 'search' | 'research',
  onChatReady?: (ids: { chatId?: string; userMessageId?: string; messageId?: string; runId?: string; taskKind?: string }) => void,
): Promise<string | undefined> {
  setActiveChatId(chatId ?? null);
  const streamMessages = get(messages);
  const context = createStreamContext(chatId, streamMessages);
  if (!context) return;
  const model = get(selectedModel);
  const ctrl = context.controller;
  const effectiveModeHint = modeHint === 'search' && get(searchEnabled)
    ? 'search'
    : modeHint === 'research' && get(researchEnabled)
      ? 'research'
      : undefined;
  const researchRequest: PendingResearchRequest | null = effectiveModeHint === 'research'
    ? { stopRequested: false, cancelSent: false }
    : null;
  context.pendingResearchRequest = researchRequest;

  // Build attachment info for the temp user message
  const attachments: AttachmentInfo[] | undefined = uploadedFiles?.length
    ? uploadedFiles.map((f) => ({ file_id: f.id, filename: f.filename, file_type: f.file_type, content_type: f.content_type }))
    : undefined;

  // Compute current thread tail so optimistic temps attach as a continuation
  // rather than appearing as new root branches in the tree builder.
  const currentMsgs = get(context.messages);
  const currentThread = buildThread(currentMsgs, get(branchSelections));
  const tailId = currentThread.length ? currentThread[currentThread.length - 1].id : null;

  // Add user message with temp ID
  context.messages.update((msgs) => [
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
  context.messages.update((msgs) => [
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
    if (effectiveModeHint) body.mode_hint = effectiveModeHint;

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
      setStreamError(undefined, formatError(err, res.status), context.messages);
      return;
    }

    const ids = await processSSEStream(res, async (readyIds) => {
      const wasForegroundStream = chatStreamKey(get(activeChatId)) === context.key;
      if (readyIds.messageId) context.messageId = readyIds.messageId;
      if (readyIds.userMessageId) context.userMessageId = readyIds.userMessageId;
      if (readyIds.chatId) {
        if (wasForegroundStream) setActiveChatId(readyIds.chatId);
        remapStreamContext(context, readyIds.chatId);
        if (get(activeChatId) === readyIds.chatId) syncResearchPolling(readyIds.chatId);
      }
      if (wasForegroundStream) onChatReady?.(readyIds);
      if (researchRequest && readyIds.taskKind === 'research' && readyIds.chatId && readyIds.runId) {
        researchRequest.chatId = readyIds.chatId;
        researchRequest.runId = readyIds.runId;
        if (researchRequest.stopRequested && !researchRequest.cancelSent) {
          researchRequest.cancelSent = true;
          await stopResearchRun(readyIds.chatId, readyIds.runId);
        }
      }
    }, context.messages);
    if (ids.chatId && get(activeChatId) === ids.chatId) syncResearchPolling(ids.chatId);
    return ids.chatId;
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) {
      setStreamError(undefined, e instanceof Error ? e.message : String(e), context.messages);
    }
  } finally {
    context.pendingResearchRequest = null;
    finalizeOptimisticMessages(context.messages);
    syncPendingResearchReports(context.messages, null);
    const completedChatId = context.chatId;
    releaseStreamContext(context);
    if (completedChatId && get(activeChatId) === completedChatId) syncResearchPolling(completedChatId);
    await loadChats().catch(() => {});
  }
}

export async function regenerateMessage(chatId: string, messageId: string, model?: string): Promise<void> {
  setActiveChatId(chatId);
  const context = createStreamContext(chatId, get(messages));
  if (!context) return;
  const selectedMdl = model || get(selectedModel);
  const ctrl = context.controller;

  // Find the old message to inherit its parent_id — the new regenerated response
  // must be a sibling of it (same parent = the user message that triggered both).
  const allMsgs = get(context.messages);
  const oldMsg = allMsgs.find((m) => m.id === messageId);
  const parentId = oldMsg?.parent_id;

  // Add a new streaming placeholder as a sibling. The old message stays in the
  // store, so the user can still navigate back to it via the branch navigator.
  context.messages.update((msgs) => [
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
      setStreamError(undefined, formatError(err, res.status), context.messages);
      return;
    }

    await processSSEStream(res, (readyIds) => {
      if (readyIds.messageId) context.messageId = readyIds.messageId;
    }, context.messages);
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) {
      setStreamError(undefined, e instanceof Error ? e.message : String(e), context.messages);
    }
  } finally {
    finalizeOptimisticMessages(context.messages);
    syncPendingResearchReports(context.messages, null);
    const completedChatId = context.chatId;
    releaseStreamContext(context);
    if (completedChatId && get(activeChatId) === completedChatId) syncResearchPolling(completedChatId);
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
