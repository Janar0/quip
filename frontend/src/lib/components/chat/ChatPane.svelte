<script lang="ts">
  import { t } from 'svelte-i18n';
  import { isStreaming } from '$lib/stores/chat';
  import type { UploadedFile } from '$lib/api/files';
  import { fly } from 'svelte/transition';
  import { D2 } from '$lib/motion';
  import MessageList from './MessageList.svelte';
  import ChatInput from './ChatInput.svelte';
  import ArtifactPanel from '$lib/components/artifacts/ArtifactPanel.svelte';
  import WorkspaceFilesPanel from '$lib/components/workspaces/WorkspaceFilesPanel.svelte';
  import { activeDrawer, closeDrawer, openDrawer } from '$lib/stores/drawer';

  interface Props {
    chatId: string | undefined;
    workspaceId?: string;
    onSend: (text: string, fileIds?: string[], uploadedFiles?: UploadedFile[]) => void | Promise<void>;
    onRegenerate?: (messageId: string) => void;
    onEdit?: (messageId: string, content: string) => void;
    loading?: boolean;
  }
  let { chatId, workspaceId, onSend, onRegenerate, onEdit, loading = false }: Props = $props();

</script>

<div class="flex flex-1 overflow-hidden">
  <div class="relative flex flex-col flex-1 min-w-0">
    {#if loading}
      <div class="flex-1 flex items-center justify-center">
        <div class="w-6 h-6 border-2 border-slate-800 border-t-slate-300 rounded-full animate-spin"></div>
      </div>
    {:else}
      <div in:fly={{ y: 10, duration: D2 }} class="flex-1 flex flex-col min-h-0">
        <MessageList {onRegenerate} {onEdit} />
      </div>
    {/if}
    <div class="absolute left-0 right-0 bottom-0">
      <div class="quip-composer-scrim" aria-hidden="true"></div>
      <ChatInput {onSend} {chatId} {workspaceId} />
    </div>
  </div>
  {#if $activeDrawer === 'artifacts'}
    <div class="border-l border-slate-800/50 w-[480px] min-w-[320px] max-w-[60vw] flex-col hidden md:flex">
      <ArtifactPanel />
    </div>
    <div class="fixed inset-0 z-50 bg-slate-950 flex flex-col md:hidden">
      <button
        class="absolute top-3 right-3 z-10 p-2 rounded-lg bg-slate-800/50 hover:bg-slate-800"
        onclick={closeDrawer}
        aria-label={$t('artifacts.close')}
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
      <ArtifactPanel />
    </div>
  {:else if $activeDrawer === 'files' && workspaceId}
    <div class="border-l w-[380px] min-w-[300px] max-w-[50vw] flex-col hidden md:flex" style="border-color: var(--quip-border)">
      <WorkspaceFilesPanel {workspaceId} />
    </div>
    <div class="fixed inset-0 z-50 flex flex-col md:hidden" style="background: var(--quip-bg)">
      <WorkspaceFilesPanel {workspaceId} />
    </div>
  {/if}
</div>
