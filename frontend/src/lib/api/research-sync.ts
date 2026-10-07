import { get, type Writable } from 'svelte/store';
import { activeChat, activeChatId, messages, type MessageInfo, type ResearchRunInfo, type ResearchRunStatus } from '$lib/stores/chat';
import { cancelChatRun, ChatRunRequestError, getChatRun } from './chat-runs';
import { isActiveResearch, newResearchReportFreshness, projectResearchRun, type ResearchReportFreshness } from './research-projection';

type ResearchRunReference = {
  id: string;
  assistant_message_id: string;
  status: ResearchRunStatus;
  task_kind?: string;
};

/** Research synchronization uses the chat owner's routing without owning its streams. */
export function createResearchSync(
  messageStoreForRun: (runId: string) => Writable<MessageInfo[]>,
  activeStreamMessageId: (chatId: string | null | undefined) => string | null,
) {
  let researchPollTimer: ReturnType<typeof setInterval> | null = null;
  let researchPollChatId: string | null = null;

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
    if (get(activeChatId) !== chatId) return;
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

  function stopResearchPolling(chatId?: string): void {
    if (chatId && researchPollChatId !== chatId) return;
    if (researchPollTimer) clearInterval(researchPollTimer);
    researchPollTimer = null;
    researchPollChatId = null;
  }

  async function refreshResearchRunStates(chatId: string): Promise<void> {
    const timer = researchPollTimer;
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
    if (researchPollTimer !== timer || researchPollChatId !== chatId
        || get(activeChat)?.id !== chatId || get(activeChatId) !== chatId) return;
    syncResearchPolling(chatId);
  }

  async function stopResearchRun(chatId: string, runId: string): Promise<void> {
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

  async function hydrateResearchRuns(
    chatId: string,
    msgs: MessageInfo[],
    runs: ResearchRunReference[],
    targetMessages: Writable<MessageInfo[]>,
    streamingMessageId: () => string | null,
    isCurrent: () => boolean,
  ): Promise<void> {
    const researchRuns = runs.filter((run) =>
      run.task_kind === 'research' && msgs.some((message) => message.id === run.assistant_message_id),
    );
    const runStates = await Promise.all(researchRuns.map(async (run) => {
      const storedMessage = get(targetMessages)
        .find((message) => message.id === run.assistant_message_id);
      const localMessage = storedMessage?.chat_id === chatId ? storedMessage : undefined;
      const loadedMessage = msgs.find((message) => message.id === run.assistant_message_id);
      const freshness = newResearchReportFreshness(localMessage ?? loadedMessage, localMessage?.research?.status ?? run.status);
      return {
        runId: run.id,
        freshness,
        state: await getChatRun(chatId, run.id).catch(() => null),
      };
    }));
    if (!isCurrent()) return;
    for (const { runId, state, freshness } of runStates) {
      if (!state) continue;
      const assistantMessageId = researchRuns.find((run) => run.id === runId)?.assistant_message_id;
      const message = msgs.find((item) => item.research?.runId === runId)
        ?? msgs.find((item) => item.id === assistantMessageId);
      if (!message) continue;
      const latestLocal = get(targetMessages)
        .find((item) => item.id === assistantMessageId && item.chat_id === chatId);
      let projectionBase = message;
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
        streamingMessageId(),
        freshness,
      ));
    }
  }

  return { hydrateResearchRuns, syncPendingResearchReports, syncResearchPolling, stopResearchPolling, stopResearchRun };
}
