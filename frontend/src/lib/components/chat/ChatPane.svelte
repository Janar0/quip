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
    onSend: (text: string, fileIds?: string[], uploadedFiles?: UploadedFile[], modeHint?: 'search' | 'research') => void | Promise<void>;
    onRegenerate?: (messageId: string) => void;
    onEdit?: (messageId: string, content: string) => void;
    loading?: boolean;
  }
  let { chatId, workspaceId, onSend, onRegenerate, onEdit, loading = false }: Props = $props();

  function handleWindowKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && ($activeDrawer === 'artifacts' || $activeDrawer === 'files')) closeDrawer();
  }
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<div class="relative flex flex-1 min-h-0 overflow-hidden">
  <div class="relative flex flex-col flex-1 min-w-0">
    {#if loading}
      <div class="flex-1 flex items-center justify-center">
        <div class="w-6 h-6 border-2 border-outline border-t-slate-300 rounded-full animate-spin"></div>
      </div>
    {:else}
      <div in:fly={{ y: 10, duration: D2 }} class="flex-1 flex flex-col min-h-0">
        <MessageList {onRegenerate} {onEdit} />
      </div>
    {/if}
    <div class="relative shrink-0">
      <div class="quip-composer-scrim" aria-hidden="true"></div>
      <ChatInput {onSend} {chatId} {workspaceId} />
    </div>
  </div>
  {#if $activeDrawer === 'artifacts'}
    <aside
      class="quip-chat-drawer absolute inset-y-0 right-0 z-30 flex w-full md:w-[min(480px,100%)] max-w-full flex-col"
      aria-label={$t('artifacts.panelLabel')}
    >
      <ArtifactPanel />
    </aside>
  {:else if $activeDrawer === 'files' && workspaceId}
    <aside
      class="quip-chat-drawer absolute inset-y-0 right-0 z-30 flex w-full md:w-[min(380px,100%)] max-w-full flex-col"
      aria-label={$t('workspace.files')}
    >
      <WorkspaceFilesPanel {workspaceId} />
    </aside>
  {/if}
</div>
