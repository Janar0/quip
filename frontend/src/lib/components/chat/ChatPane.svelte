<script lang="ts">
  import { t } from 'svelte-i18n';
  import { artifactPanelOpen } from '$lib/stores/artifacts';
  import type { UploadedFile } from '$lib/api/files';
  import MessageList from './MessageList.svelte';
  import ChatInput from './ChatInput.svelte';
  import ArtifactPanel from '$lib/components/artifacts/ArtifactPanel.svelte';

  interface Props {
    chatId: string | undefined;
    onSend: (text: string, fileIds?: string[], uploadedFiles?: UploadedFile[]) => void | Promise<void>;
    onRegenerate?: (messageId: string) => void;
    onEdit?: (messageId: string, content: string) => void;
    loading?: boolean;
  }
  let { chatId, onSend, onRegenerate, onEdit, loading = false }: Props = $props();
</script>

<div class="flex flex-1 overflow-hidden">
  <div class="relative flex flex-col flex-1 min-w-0">
    {#if loading}
      <div class="flex-1 flex items-center justify-center">
        <div class="w-6 h-6 border-2 border-slate-800 border-t-slate-300 rounded-full animate-spin"></div>
      </div>
    {:else}
      <MessageList {onRegenerate} {onEdit} />
    {/if}
    <div class="absolute left-0 right-0 bottom-0">
      <div class="quip-composer-scrim" aria-hidden="true"></div>
      <ChatInput {onSend} {chatId} />
    </div>
  </div>
  {#if $artifactPanelOpen}
    <div class="border-l border-slate-800/50 w-[480px] min-w-[320px] max-w-[60vw] flex-col hidden md:flex">
      <ArtifactPanel />
    </div>
    <div class="fixed inset-0 z-50 bg-slate-950 flex flex-col md:hidden">
      <button
        class="absolute top-3 right-3 z-10 p-2 rounded-lg bg-slate-800/50 hover:bg-slate-800"
        onclick={() => artifactPanelOpen.set(false)}
        aria-label={$t('artifacts.close')}
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
      <ArtifactPanel />
    </div>
  {/if}
</div>
