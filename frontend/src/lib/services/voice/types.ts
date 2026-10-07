import type { VoiceContextPacket, VoiceTaskStatus, VoiceToolResult } from '$lib/api/voice';

export type VoiceStatus = 'idle' | 'connecting' | 'active' | 'ending' | 'ended' | 'error';

export interface VoiceTranscriptEntry {
  role: 'user' | 'assistant';
  text: string;
}

export interface VoiceTaskView {
  taskId: string;
  status: string;
  revision: number;
  contextVersion: number;
  content: string;
  progress: string;
  error: string | null;
}

export interface VoiceSessionState {
  status: VoiceStatus;
  muted: boolean;
  cameraSelected: boolean;
  cameraEnabled: boolean;
  cameraError: string | null;
  error: string | null;
  usage: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  task: VoiceTaskView | null;
}

export interface VoiceSessionApi {
  start(chatId: string, sdp: string, cameraEnabled: boolean): Promise<{ call_id: string; sdp: string; type?: 'answer' }>;
  context(callId: string): Promise<VoiceContextPacket>;
  event(callId: string, event: Record<string, unknown>): Promise<Record<string, unknown>>;
  tool(callId: string, providerCallId: string, name: string, argumentsJson: string, signal?: AbortSignal): Promise<VoiceToolResult>;
  startTask(callId: string, providerCallId: string, goal: string): Promise<{ task_id: string; status: string; model: string; replayed: boolean; steered: boolean }>;
  task(callId: string, taskId: string): Promise<VoiceTaskStatus>;
  steerTask(callId: string, taskId: string, expectedRevision: number, idempotencyKey: string, instruction: string): Promise<{ task_id: string; status: string; revision: number; context_version: number; replayed: boolean }>;
  cancelTask(callId: string, taskId: string): Promise<{ task_id: string; status: string }>;
  cancelTool?(callId: string, providerCallId: string): Promise<unknown>;
  end(callId: string): Promise<unknown>;
}

export type VoiceSessionOptions = {
  api?: VoiceSessionApi;
  getUserMedia?: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  createPeerConnection?: () => RTCPeerConnection;
  createAudioContext?: () => AudioContext;
  createMediaStream?: (tracks: MediaStreamTrack[]) => MediaStream;
  createVideoPipeline?: (source: MediaStream) => Promise<{ stream: MediaStream; track: MediaStreamTrack; dispose: () => void }>;
  onState?: (state: VoiceSessionState) => void;
  onTranscript?: (entry: VoiceTranscriptEntry) => void;
  onTask?: (task: VoiceTaskView | null) => void;
  onLocalVideoStream?: (stream: MediaStream | null) => void;
  ringbackIntervalMs?: number;
  iceGatheringTimeoutMs?: number;
  sessionTimeoutMs?: number;
  cameraSupported?: boolean;
};
