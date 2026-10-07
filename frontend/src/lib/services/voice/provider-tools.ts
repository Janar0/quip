import { ALLOWED_TOOLS } from './provider-protocol';
import type { VoiceSessionApi } from './types';

type StartedTask = Awaited<ReturnType<VoiceSessionApi['startTask']>>;

/** Executes provider tool requests, retaining each web request's original call for cancellation. */
export class VoiceToolExecutor {
  private pending = new Map<string, { controller: AbortController; callId: string; providerCallId: string }>();

  constructor(private api: VoiceSessionApi) {}

  reset(): void { this.pending.clear(); }

  cancel(): void {
    for (const { controller, callId, providerCallId } of this.pending.values()) {
      controller.abort();
      if (this.api.cancelTool) void this.api.cancelTool(callId, providerCallId).catch(() => {});
    }
  }

  async invoke(
    invocationKey: string,
    originCallId: string | null,
    providerCallId: string,
    name: string,
    args: string,
    isCurrent: () => boolean,
    onTaskStarted: (task: StartedTask) => void,
  ): Promise<string | undefined> {
    if (name === 'delegate_to_text_model') {
      if (!originCallId) return JSON.stringify({ error: 'voice_call_unavailable' });
      try {
        const parsed = JSON.parse(args);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)
            || Object.keys(parsed).length !== 1 || typeof parsed.goal !== 'string'
            || !parsed.goal.trim() || parsed.goal.length > 2_000) {
          throw new Error('invalid_task_goal');
        }
        const started = await this.api.startTask(originCallId, providerCallId, parsed.goal.trim());
        if (!isCurrent()) return;
        onTaskStarted(started);
        return JSON.stringify({
          task_id: started.task_id,
          status: started.status,
          model: started.model,
          steered: started.steered,
          message: started.steered
            ? 'Luna is continuing the same task with this clarification. Keep talking to the user.'
            : 'Luna is working in the background. Keep talking to the user; the result will be returned when ready.',
        });
      } catch {
        if (!isCurrent()) return;
        return JSON.stringify({ error: 'quip_task_failed' });
      }
    }
    if (!ALLOWED_TOOLS.has(name)) return JSON.stringify({ error: 'unsupported_tool' });
    if (!originCallId) return JSON.stringify({ error: 'voice_call_unavailable' });
    const controller = new AbortController();
    this.pending.set(invocationKey, { controller, callId: originCallId, providerCallId });
    try {
      const result = await this.api.tool(originCallId, providerCallId, name, args, controller.signal);
      if (!isCurrent()) return;
      return JSON.stringify(result.result);
    } catch {
      if (!isCurrent()) return;
      return JSON.stringify({ error: 'quip_tool_failed' });
    } finally {
      if (this.pending.get(invocationKey)?.controller === controller) this.pending.delete(invocationKey);
    }
  }
}
