<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from 'svelte-i18n';
  import { voiceApi } from '$lib/api/voice';
  import { VoiceSession, type VoiceSessionState, type VoiceTranscriptEntry } from '$lib/services/voice/session';

  type Props = { chatId: string; onClose: () => void };
  let { chatId, onClose }: Props = $props();
  let callState: VoiceSessionState = $state({
    status: 'idle', muted: false, cameraSelected: false, cameraEnabled: false,
    cameraError: null, error: null, usage: null, task: null,
  });
  let taskInstruction = $state('');
  let taskActionError = $state(false);
  let transcript: VoiceTranscriptEntry[] = $state([]);
  let videoStream: MediaStream | null = $state(null);
  let localPreview: HTMLVideoElement | undefined = $state();
  let remoteAudio: HTMLAudioElement | undefined = $state();
  let cameraSupported = $state(false);
  let session: VoiceSession | null = null;

  onMount(() => {
    void voiceApi.config().then((configuration) => {
      cameraSupported = configuration.camera_supported;
      session?.setCameraSupported(cameraSupported);
    }).catch(() => {
      cameraSupported = false;
      session?.setCameraSupported(false);
    });
    session = new VoiceSession(chatId, {
      onState: (next) => { callState = next; },
      onTranscript: (entry) => { transcript = [...transcript, entry].slice(-8); },
      onLocalVideoStream: (stream) => { videoStream = stream; },
    });
    session.attachRemoteAudio(remoteAudio ?? null);
    return () => { void session?.end(); };
  });

  $effect(() => {
    if (localPreview && videoStream) {
      localPreview.srcObject = videoStream;
      void localPreview.play().catch(() => {});
    } else if (localPreview && !videoStream) {
      localPreview.srcObject = null;
    }
  });

  async function startCall() {
    await session?.start();
  }

  async function endCall() {
    await session?.end({ keepTaskVisible: true });
  }

  async function submitTaskSteering(event: SubmitEvent) {
    event.preventDefault();
    const instruction = taskInstruction.trim();
    if (!instruction || !session) return;
    taskActionError = false;
    try {
      await session.steerTask(instruction);
      taskInstruction = '';
    } catch {
      taskActionError = true;
    }
  }

  async function cancelDelegatedTask() {
    if (!session) return;
    taskActionError = false;
    try { await session.cancelTask(); }
    catch { taskActionError = true; }
  }

  function toggleCameraSelection() {
    if (!session) return;
    try { session.chooseCamera(!callState.cameraSelected); }
    catch { /* the active call explains when video can be enabled */ }
  }

  function toggleMute() {
    session?.mute(!callState.muted);
  }

  function interruptSpeech() {
    session?.interruptSpeech();
  }

  function turnCameraOff() {
    void session?.setCamera(false);
  }

  function statusLabel() {
    if (callState.status === 'connecting') return $t('voice.statusConnecting');
    if (callState.status === 'active') return $t('voice.statusActive');
    if (callState.status === 'ending') return $t('voice.statusEnding');
    if (callState.status === 'ended') return $t('voice.statusEnded');
    if (callState.status === 'error') return $t('voice.statusError');
    return $t('voice.statusReady');
  }
</script>

<section class="mb-3 rounded-2xl border border-outline/40 bg-elevated/80 p-4" aria-label={$t('voice.panelTitle')}>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="min-w-0">
      <h2 class="text-sm font-semibold text-foreground">{$t('voice.panelTitle')}</h2>
      <p class="text-xs text-muted" aria-live="polite">{statusLabel()}</p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      {#if callState.status === 'idle' || callState.status === 'ended' || callState.status === 'error'}
        <button
          type="button"
          class="rounded-lg px-3 py-2 text-sm font-medium bg-accent text-white disabled:opacity-50"
          onclick={startCall}
          aria-label={$t('voice.start')}
        >{$t('voice.start')}</button>
        {#if cameraSupported}
          <button
            type="button"
            class="rounded-lg border border-outline/50 px-3 py-2 text-sm"
            onclick={toggleCameraSelection}
            aria-pressed={callState.cameraSelected}
            aria-label={$t(callState.cameraSelected ? 'voice.cameraSelected' : 'voice.chooseCamera')}
          >{callState.cameraSelected ? $t('voice.cameraSelected') : $t('voice.chooseCamera')}</button>
        {/if}
      {:else if callState.status === 'connecting'}
        <button type="button" class="rounded-lg border border-outline/50 px-3 py-2 text-sm" onclick={endCall} aria-label={$t('voice.cancel')}>
          {$t('voice.cancel')}
        </button>
      {:else if callState.status === 'active'}
        <button type="button" class="rounded-lg border border-outline/50 px-3 py-2 text-sm" onclick={toggleMute} aria-pressed={callState.muted}>
          {$t(callState.muted ? 'voice.unmute' : 'voice.mute')}
        </button>
        <button type="button" class="rounded-lg border border-outline/50 px-3 py-2 text-sm" onclick={interruptSpeech}>
          {$t('voice.interrupt')}
        </button>
        {#if callState.cameraEnabled}
          <button type="button" class="rounded-lg border border-outline/50 px-3 py-2 text-sm" onclick={turnCameraOff}>
            {$t('voice.turnCameraOff')}
          </button>
        {/if}
        <button type="button" class="rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white" onclick={endCall} aria-label={$t('voice.end')}>
          {$t('voice.end')}
        </button>
      {/if}
      <button type="button" class="rounded-lg p-2 text-muted hover:text-foreground" onclick={onClose} aria-label={$t('voice.close')}>
        <span aria-hidden="true">×</span>
      </button>
    </div>
  </div>

  <p class="mt-2 text-xs text-muted" role="note">{$t('voice.costNotice')}</p>
  {#if callState.status === 'idle' || callState.status === 'ended' || callState.status === 'error'}
    {#if cameraSupported}
      <p class="mt-2 text-xs text-muted">{$t('voice.cameraChoiceHint')}</p>
    {:else}
      <p class="mt-2 text-xs text-muted">{$t('voice.cameraModelUnsupported')}</p>
    {/if}
  {/if}
  {#if callState.status === 'active' && !callState.cameraEnabled}
    <p class="mt-2 text-xs text-muted">{$t('voice.cameraRestartHint')}</p>
  {/if}
  {#if callState.cameraError}
    <p class="mt-2 text-xs text-amber-700 dark:text-amber-300" role="status">{$t(`voice.${callState.cameraError}`)}</p>
  {/if}
  {#if callState.error}
    <p class="mt-2 text-xs text-red-600 dark:text-red-300" role="alert">{$t(`voice.error.${callState.error}`)}</p>
  {/if}

  {#if callState.task}
    <div class="mt-3 space-y-2 rounded-xl border border-outline/40 bg-canvas/70 p-3" aria-live="polite">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p class="text-xs font-semibold">{$t('voice.task.title')} · {$t(`voice.task.status.${callState.task.status}`)}</p>
          <p class="text-xs text-muted">{callState.task.progress}</p>
        </div>
        {#if ['queued', 'running'].includes(callState.task.status)}
          <button type="button" class="rounded-lg border border-red-500/40 px-3 py-2 text-xs" onclick={cancelDelegatedTask}>
            {$t('voice.task.cancel')}
          </button>
        {/if}
      </div>
      {#if callState.task.content}
        <div>
          <p class="text-xs font-semibold">{$t('voice.task.result')}</p>
          <p class="whitespace-pre-wrap text-xs text-foreground">{callState.task.content}</p>
        </div>
      {/if}
      {#if callState.task.error}
        <p class="text-xs text-red-600 dark:text-red-300">{$t('voice.task.failed')}</p>
      {/if}
      {#if ['queued', 'running'].includes(callState.task.status)}
        <form class="flex flex-wrap gap-2" onsubmit={submitTaskSteering}>
          <input
            bind:value={taskInstruction}
            maxlength="2000"
            class="min-w-0 flex-1 rounded-lg border border-outline/50 bg-canvas px-3 py-2 text-xs"
            aria-label={$t('voice.task.clarification')}
            placeholder={$t('voice.task.clarification')}
          />
          <button type="submit" disabled={!taskInstruction.trim()} class="rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-50">
            {$t('voice.task.sendSteering')}
          </button>
        </form>
      {/if}
      {#if taskActionError}
        <p class="text-xs text-red-600 dark:text-red-300" role="alert">{$t('voice.task.actionFailed')}</p>
      {/if}
    </div>
  {/if}

  {#if videoStream}
    <div class="mt-3 w-full max-w-sm overflow-hidden rounded-xl border border-outline/40 bg-black">
      <video bind:this={localPreview} autoplay muted playsinline class="aspect-video w-full object-cover" aria-label={$t('voice.localPreview')}></video>
    </div>
  {/if}

  {#if transcript.length}
    <div class="mt-3 max-h-36 space-y-1 overflow-y-auto rounded-xl bg-canvas/70 p-3" aria-live="polite" aria-label={$t('voice.transcript')}>
      {#each transcript as entry, index (`${index}-${entry.role}-${entry.text.slice(0, 16)}`)}
        <p class="text-xs text-foreground"><span class="font-semibold">{$t(entry.role === 'user' ? 'voice.you' : 'voice.assistant')}:</span> {entry.text}</p>
      {/each}
    </div>
  {/if}
  {#if callState.usage}
    <p class="mt-2 text-[11px] text-muted">{$t('voice.preliminaryUsage', { values: { total: callState.usage.total_tokens } })}</p>
  {/if}
  <audio bind:this={remoteAudio} autoplay playsinline class="hidden"></audio>
</section>
