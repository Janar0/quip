import { api } from './client';

export interface VoiceSessionAnswer {
  call_id: string;
  sdp: string;
  type: 'answer';
}

export interface VoicePublicConfig {
  enabled: boolean;
  model: string;
  camera_supported: boolean;
}

export interface VoiceContextItem {
  source_id: string;
  source_type: 'chat_message' | 'document_chunk';
  speaker: string;
  text: string;
  title?: string | null;
}

export interface VoiceContextPacket {
  chat_id: string;
  context_version: number;
  task_goal: string;
  summary: string;
  summary_sources: string[];
  task_state: Record<string, unknown>;
  recent: VoiceContextItem[];
  retrieved: VoiceContextItem[];
  estimated_tokens: number;
  instruction: string;
}

export interface VoiceToolResult {
  provider_call_id: string;
  name: string;
  status: 'completed' | 'failed' | 'cancelled';
  result: Record<string, unknown>;
  replayed: boolean;
}

export interface VoiceTaskStart {
  task_id: string;
  status: string;
  model: string;
  replayed: boolean;
  steered: boolean;
}

export interface VoiceTaskStatus {
  task_id: string;
  chat_id: string;
  status: string;
  revision: number;
  context_version: number;
  task_kind: string;
  cancel_requested: boolean;
  snapshot: Record<string, unknown>;
  error: string | null;
  message: { id: string; content: string; artifacts: unknown[] } | null;
}

export interface VoiceTaskSteerResult {
  task_id: string;
  status: string;
  revision: number;
  context_version: number;
  replayed: boolean;
}

async function jsonRequest<T>(path: string, method: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await api(path, {
      method,
      ...(signal ? { signal } : {}),
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new Error('voice_network_unavailable');
  }
  if (!response.ok) {
    let detail = 'voice_request_failed';
    try {
      const payload = await response.json();
      if (typeof payload.detail === 'string') detail = payload.detail;
      else if (typeof payload.detail?.message === 'string') detail = payload.detail.message;
    } catch { /* keep a generic visible error */ }
    throw new Error(detail.slice(0, 240));
  }
  if (response.status === 204) return {} as T;
  try {
    return await response.json() as T;
  } catch {
    throw new Error('voice_invalid_server_response');
  }
}

/** Authenticated Quip endpoints; the Qwen credential never enters this module. */
export const voiceApi = {
  config(): Promise<VoicePublicConfig> {
    return jsonRequest('/api/voice/config', 'GET');
  },
  start(chatId: string, sdp: string, cameraEnabled: boolean): Promise<VoiceSessionAnswer> {
    return jsonRequest('/api/voice/calls', 'POST', {
      chat_id: chatId, sdp, type: 'offer', camera_enabled: cameraEnabled,
    });
  },
  context(callId: string): Promise<VoiceContextPacket> {
    return jsonRequest(`/api/voice/calls/${encodeURIComponent(callId)}/context`, 'GET');
  },
  event(callId: string, event: Record<string, unknown>): Promise<Record<string, unknown>> {
    return jsonRequest(`/api/voice/calls/${encodeURIComponent(callId)}/events`, 'POST', { event });
  },
  tool(callId: string, providerCallId: string, name: string, argumentsJson: string, signal?: AbortSignal): Promise<VoiceToolResult> {
    return jsonRequest(`/api/voice/calls/${encodeURIComponent(callId)}/tools`, 'POST', {
      provider_call_id: providerCallId,
      name,
      arguments: argumentsJson,
    }, signal);
  },
  cancelTool(callId: string, providerCallId: string): Promise<{ provider_call_id: string; status: string }> {
    return jsonRequest(`/api/voice/calls/${encodeURIComponent(callId)}/tools/${encodeURIComponent(providerCallId)}/cancel`, 'POST');
  },
  startTask(callId: string, providerCallId: string, goal: string): Promise<VoiceTaskStart> {
    return jsonRequest(`/api/voice/calls/${encodeURIComponent(callId)}/tasks`, 'POST', {
      provider_call_id: providerCallId,
      goal,
    });
  },
  task(callId: string, taskId: string): Promise<VoiceTaskStatus> {
    return jsonRequest(`/api/voice/calls/${encodeURIComponent(callId)}/tasks/${encodeURIComponent(taskId)}`, 'GET');
  },
  steerTask(callId: string, taskId: string, expectedRevision: number, idempotencyKey: string, instruction: string): Promise<VoiceTaskSteerResult> {
    return jsonRequest(`/api/voice/calls/${encodeURIComponent(callId)}/tasks/${encodeURIComponent(taskId)}/steer`, 'POST', {
      expected_revision: expectedRevision,
      idempotency_key: idempotencyKey,
      instruction,
    });
  },
  cancelTask(callId: string, taskId: string): Promise<{ task_id: string; status: string }> {
    return jsonRequest(`/api/voice/calls/${encodeURIComponent(callId)}/tasks/${encodeURIComponent(taskId)}/cancel`, 'POST');
  },
  end(callId: string): Promise<{ call_id: string; status: string }> {
    return jsonRequest(`/api/voice/calls/${encodeURIComponent(callId)}/end`, 'POST');
  },
};
