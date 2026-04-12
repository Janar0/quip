import { writable } from 'svelte/store';
import type { ToolExecution } from '$lib/stores/sandbox';

export interface ChatInfo {
  id: string;
  title: string;
  model: string | null;
  pinned: boolean;
  created_at: string;
  updated_at: string;
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
  file_type: 'image' | 'document';
  content_type: string;
}

export interface ResearchStatusInfo {
  phase: string;
  detail?: string;
  sub_queries?: string[];
  sources_found?: number;
  urls_reading?: string[];
  urls_read?: number;
}

export interface SearchImageInfo {
  img_src: string;
  source_url: string;
  title: string;
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
  researchStatus?: ResearchStatusInfo;
  researchHistory?: ResearchStatusInfo[];
  searchImages?: SearchImageInfo[];
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

export const searchEnabled = writable<boolean>(false);

export type ModePreference = 'auto' | 'search' | 'research';
export const modePreference = writable<ModePreference>('auto');

export function setDefaultModel(model: string): void {
  selectedModel.set(model);
  localStorage.setItem('default_model', model);
}
