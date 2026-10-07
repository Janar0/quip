import type { MessageInfo, ResearchRunInfo, ResearchRunStatus } from '$lib/stores/chat';

let researchReportRequestSequence = 0;

export function isActiveResearch(status: ResearchRunStatus): boolean {
  return status === 'queued' || status === 'running' || status === 'cancelling';
}

export type ResearchReportFreshness = {
  requestId: number;
  streamedContentAtRequest: string | null;
  statusAtRequest: ResearchRunStatus | null;
  contentAtRequest: string | null;
};

export function newResearchReportFreshness(
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

export function projectResearchRun(
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
