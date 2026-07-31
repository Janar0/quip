import { writable, get } from 'svelte/store';
import type { ToolExecution } from '$lib/stores/sandbox';

export interface ChatInfo {
  id: string;
  workspace_id: string | null;
  title: string;
  emoji?: string | null;
  model: string | null;
  source?: 'web' | 'telegram';
  external_chat_id?: string | null;
  external_thread_id?: string | null;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  runs?: ChatRunInfo[];
}

export interface ChatRunInfo {
  id: string;
  assistant_message_id: string | null;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  model: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface Artifact {
  id: string;
  identifier: string;
  type: string;
  title: string;
  content: string;
  language?: string;
  version: number;
}

export interface AttachmentInfo {
  file_id: string;
  filename: string;
  file_type: 'image' | 'document' | 'video' | 'audio' | string;
  content_type: string;
}

export interface SearchImageInfo {
  img_src: string;
  source_url: string;
  title: string;
}

export interface ResearchStatusInfo {
  phase: string;
  detail?: string;
  sub_queries?: string[];
  sources_found?: number;
  urls_reading?: string[];
  urls_read?: number;
}

export type ContentBlock =
  | { type: 'text'; content: string }
  | { type: 'tool'; executionId: string };

export interface SubAgentHandle {
  task_id: string;
  type: 'search' | 'sandbox' | 'artifact';
  status: 'running' | 'done' | 'error';
  goal: string;
  detail?: string;
  result?: string;
  error?: string;
}

export interface MessageInfo {
  id: string;
  chat_id: string;
  parent_id?: string | null;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  reasoning?: string;
  model?: string;
  provider?: string;
  token_count?: number;
  cost?: number;
  artifacts?: Artifact[];
  toolExecutions?: ToolExecution[];
  attachments?: AttachmentInfo[];
  searchImages?: SearchImageInfo[];
  contentBlocks?: ContentBlock[];
  created_at: string;
}

const _storedModel = typeof localStorage !== 'undefined' ? localStorage.getItem('default_model') : null;

export const chatList = writable<ChatInfo[]>([]);
export const activeChat = writable<ChatInfo | null>(null);
export const messages = writable<MessageInfo[]>([]);
export const isStreaming = writable<boolean>(false);
export const isLoading = writable<boolean>(false);
export const selectedModel = writable<string>(_storedModel ?? '');
export const abortController = writable<AbortController | null>(null);

// Branch selections: parent_id → selected child id. Lifted to store so non-component
// code (streamChat) can compute the current thread tail when adding optimistic messages.
export const branchSelections = writable<Record<string, string>>({});

export const searchEnabled = writable<boolean>(false);
export const subAgents = writable<Record<string, SubAgentHandle>>({});

export function setDefaultModel(model: string): void {
  selectedModel.set(model);
  localStorage.setItem('default_model', model);
}

// ── Branch selection persistence ──
// Saves branch navigator choices to localStorage so they survive page refreshes.
// Key format: quip_branches_{chatId}

const BRANCH_STORAGE_PREFIX = 'quip_branches_';

export function persistBranchSelections(chatId: string): void {
  if (typeof localStorage === 'undefined') return;
  const selections = get(branchSelections);
  if (Object.keys(selections).length === 0) {
    localStorage.removeItem(`${BRANCH_STORAGE_PREFIX}${chatId}`);
  } else {
    localStorage.setItem(`${BRANCH_STORAGE_PREFIX}${chatId}`, JSON.stringify(selections));
  }
}

export function restoreBranchSelections(chatId: string): void {
  if (typeof localStorage === 'undefined') {
    branchSelections.set({});
    return;
  }
  const stored = localStorage.getItem(`${BRANCH_STORAGE_PREFIX}${chatId}`);
  if (stored) {
    try {
      branchSelections.set(JSON.parse(stored));
    } catch {
      branchSelections.set({});
    }
  } else {
    branchSelections.set({});
  }
}

export function clearBranchSelections(chatId: string): void {
  if (typeof localStorage === 'undefined') return;
  localStorage.removeItem(`${BRANCH_STORAGE_PREFIX}${chatId}`);
}
