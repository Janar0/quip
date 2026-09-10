/** Translate completion events into chat state; transport framing lives in sse.ts. */
import { messages, chatList, activeChat, type ContentBlock, type SearchImageInfo } from '$lib/stores/chat';
import { extractStreamingArtifacts } from '$lib/utils/artifacts';
import { readSSE } from './sse';

/** Parse SSE stream, update the streaming message, return real message IDs */
export async function processSSEStream(
  response: Response,
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
        setStreamError(messageId, data.message ?? data.error ?? 'Generation failed');
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
      return contentBlocks !== undefined
        ? { ...m, content, reasoning, contentBlocks }
        : { ...m, content, reasoning };
    }),
  );
}


export function setStreamError(messageId: string | undefined, error: string): void {
  const targetId = messageId || 'streaming';
  messages.update((msgs) => msgs.map((m) => m.id === targetId ? { ...m, error } : m));
}
