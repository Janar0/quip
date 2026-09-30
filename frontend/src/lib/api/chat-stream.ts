/** Translate completion events into chat state; transport framing lives in sse.ts. */
import { messages, chatList, activeChat, type ContentBlock, type SearchImageInfo, type ResearchRunInfo } from '$lib/stores/chat';
import { extractStreamingArtifacts } from '$lib/utils/artifacts';
import { readSSE } from './sse';

/** Parse SSE stream, update the streaming message, return real message IDs */
type ChatReadyIds = {
  chatId?: string;
  userMessageId?: string;
  messageId?: string;
  runId?: string;
  taskKind?: string;
};

export async function processSSEStream(
  response: Response,
  onChatReady?: (ids: ChatReadyIds) => void | Promise<void>,
): Promise<{ chatId?: string; userMessageId?: string; messageId?: string }> {
  let fullContent = '';
  let fullReasoning = '';
  let contentBlocks: ContentBlock[] = [];
  let chatId: string | undefined;
  let userMessageId: string | undefined;
  let messageId: string | undefined;

  try {
    for await (const { event: currentEvent, data: raw } of readSSE(response)) {
      const data = JSON.parse(raw);
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
                ...(data.task_kind === 'research' && data.run_id ? { research: {
                  runId: data.run_id,
                  status: 'running' as const,
                  revision: 0,
                  contextVersion: 1,
                  cancelRequested: false,
                  snapshot: {},
                } } : {}),
              };
            }
            if (m.id === 'temp-user') {
              return { ...m, id: userMessageId!, parent_id: userParentId };
            }
            return m;
          })
        );
        await onChatReady?.({
          chatId,
          userMessageId,
          messageId,
          runId: data.run_id,
          ...(data.task_kind ? { taskKind: data.task_kind } : {}),
        });
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
      } else if (currentEvent === 'usage') {
        const targetId = messageId || 'streaming';
        messages.update((msgs) =>
          msgs.map((m) =>
            m.id === targetId
              ? { ...m, cost: data.cost ?? m.cost, provider: data.provider ?? m.provider }
              : m,
          ),
        );
        updateResearchSnapshot(targetId, { usage: data });
      } else if (currentEvent === 'status') {
        const targetId = messageId || 'streaming';
        messages.update((msgs) => msgs.map((m) => {
          if (m.id !== targetId || !m.research) return m;
          const progress = [...(m.research.snapshot.progress ?? []), data].slice(-40);
          return { ...m, research: { ...m.research, snapshot: { ...m.research.snapshot, progress } } };
        }));
      } else if (currentEvent === 'subagent_spawned' || currentEvent === 'subagent_result' || currentEvent === 'subagent_error') {
        const targetId = messageId || 'streaming';
        messages.update((msgs) => msgs.map((m) => {
          if (m.id !== targetId || !m.research) return m;
          const subagents = { ...(m.research.snapshot.subagents ?? {}) };
          const taskId = String(data.task_id ?? '');
          if (!taskId) return m;
          const previous = subagents[taskId];
          subagents[taskId] = {
            task_id: taskId,
            kind: String(data.kind ?? previous?.kind ?? 'agent'),
            goal: String(data.goal ?? previous?.goal ?? ''),
            status: currentEvent === 'subagent_spawned' ? 'running' : currentEvent === 'subagent_error' ? 'error' : 'done',
          };
          return { ...m, research: { ...m.research, snapshot: { ...m.research.snapshot, subagents } } };
        }));
      } else if (currentEvent === 'sources') {
        const targetId = messageId || 'streaming';
        updateResearchSnapshot(targetId, { sources: data.sources ?? [] });
      } else if (currentEvent === 'research_snapshot') {
        const targetId = messageId || 'streaming';
        messages.update((msgs) => msgs.map((m) => m.id === targetId && m.research
          ? { ...m, research: { ...m.research, snapshot: data.snapshot ?? {} } }
          : m));
      } else if (currentEvent === 'run_status') {
        const targetId = messageId || 'streaming';
        messages.update((msgs) => msgs.map((m) => m.id === targetId && m.research
          ? { ...m, research: { ...m.research, status: data.status ?? m.research.status, error: data.error ?? null } }
          : m));
      } else if (currentEvent === 'error') {
        setStreamError(messageId, data.message ?? data.error ?? 'Generation failed');
        updateResearchSnapshot(messageId || 'streaming', {
          errors: [{ message: String(data.message ?? data.error ?? 'Research encountered an error') }],
        });
      } else if (currentEvent === 'title') {
        const realId = chatId;
        if (realId && data.title) {
          chatList.update((list) =>
            list.map((c) => (c.id === realId ? { ...c, title: data.title, emoji: data.emoji ?? c.emoji } : c)),
          );
          activeChat.update((c) => (c?.id === realId ? { ...c, title: data.title, emoji: data.emoji ?? c.emoji } : c));
        }
      }
    }
  } catch (e) {
    if (!(e instanceof DOMException && e.name === 'AbortError')) {
      setStreamError(messageId, e instanceof Error ? e.message : String(e));
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

function updateResearchSnapshot(messageId: string, patch: Partial<ResearchRunInfo['snapshot']>) {
  messages.update((msgs) => msgs.map((m) => {
    if (m.id !== messageId || !m.research) return m;
    const snapshot = { ...m.research.snapshot, ...patch };
    if (patch.errors) snapshot.errors = [...(m.research.snapshot.errors ?? []), ...patch.errors].slice(-20);
    if (patch.sources) {
      const existing = m.research.snapshot.sources ?? [];
      const seen = new Set(existing.map((source) => source.url));
      snapshot.sources = [...existing, ...patch.sources.filter((source) => !seen.has(source.url))].slice(0, 30);
    }
    return { ...m, research: { ...m.research, snapshot } };
  }));
}

export function updateStreamingContent(
  messageId: string | undefined,
  content: string,
  reasoning?: string,
  contentBlocks?: ContentBlock[],
) {
  const targetId = messageId || 'streaming';
  messages.update((msgs) =>
    msgs.map((m) => {
      if (m.id !== targetId) return m;
      const updated = contentBlocks !== undefined
        ? { ...m, content, reasoning, contentBlocks }
        : { ...m, content, reasoning };
      return m.research ? {
        ...updated,
        research: { ...m.research, streamedContent: content },
      } : updated;
    }),
  );
}


export function setStreamError(messageId: string | undefined, error: string): void {
  const targetId = messageId || 'streaming';
  messages.update((msgs) => msgs.map((m) => m.id === targetId ? { ...m, error } : m));
}
