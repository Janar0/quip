<script lang="ts">
  import { page } from '$app/state';
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import { fly } from 'svelte/transition';
  import { D2, easeOut } from '$lib/motion';
  import { loadChat, streamChat, regenerateMessage, editMessage } from '$lib/api/chats';
  import { activeChat, messages, isLoading, isStreaming } from '$lib/stores/chat';
  import type { UploadedFile } from '$lib/api/files';
  import { exportAsMarkdown } from '$lib/utils/export';
  import ModelSelector from '$lib/components/chat/ModelSelector.svelte';
  import ChatPane from '$lib/components/chat/ChatPane.svelte';
  import { selectedWorkspaceId } from '$lib/stores/workspaces';
  import { onMount } from 'svelte';
  import { activeDrawer, closeDrawer, openDrawer } from '$lib/stores/drawer';

  let chatId = $derived(page.params.id ?? '');
  let showExportMenu = $state(false);
  let workspaceId = $derived($activeChat?.workspace_id ?? $selectedWorkspaceId ?? undefined);

  $effect(() => {
    if (chatId) loadChat(chatId);
  });

  onMount(() => {
    const timer = setInterval(() => {
      if (chatId && $activeChat?.source === 'telegram' && !$isLoading && !$isStreaming) {
        loadChat(chatId);
      }
    }, 4000);
    return () => clearInterval(timer);
  });

  async function handleSend(text: string, fileIds: string[] = [], uploadedFiles: UploadedFile[] = []) {
    await streamChat(
      text,
      chatId,
      fileIds.length ? fileIds : undefined,
      uploadedFiles.length ? uploadedFiles : undefined,
      undefined,
      workspaceId,
    );
  }

  function handleRegenerate(messageId: string) {
    if (chatId) regenerateMessage(chatId, messageId);
  }

  function handleEdit(messageId: string, content: string) {
    if (chatId) editMessage(chatId, messageId, content);
  }

  function handleExportMarkdown() {
    if ($activeChat) {
      exportAsMarkdown($activeChat, $messages);
      toast.success($t('toast.exported'));
    }
    showExportMenu = false;
  }
</script>

<svelte:window onclick={() => (showExportMenu = false)} />

<div class="relative flex flex-col h-full">
  <ChatPane
    chatId={chatId}
    onSend={handleSend}
    onRegenerate={handleRegenerate}
    onEdit={handleEdit}
    loading={$isLoading && !$messages.length}
    {workspaceId}
  />
  <div class="absolute left-0 right-0 top-0 z-10">
    <div class="quip-header-scrim" aria-hidden="true"></div>
    <header class="relative flex items-center pl-14 sm:pl-3 pr-3 py-2.5">
      <div class="flex-1 flex items-center gap-2 min-w-0 justify-center sm:justify-start">
        <ModelSelector />
        {#if $activeChat}
          <span class="hidden sm:block text-sm text-slate-500 truncate max-w-[200px]">{$activeChat.title}</span>
        {/if}
      </div>
      {#if workspaceId}
        <button
          class="p-2 mr-2 rounded-lg transition-colors backdrop-blur-sm active:scale-[0.95]"
          style="background: var(--quip-input-bg); border: 1px solid var(--quip-border); color: var(--quip-text-dim)"
          onclick={(event) => { event.stopPropagation(); $activeDrawer === 'files' ? closeDrawer() : openDrawer('files'); }}
          title={$t('workspace.files')}
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 7.5h7l2 2h9v9.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7.5Z"/><path d="M3 7.5v-2A2.5 2.5 0 0 1 5.5 3H9l2 2h7.5A2.5 2.5 0 0 1 21 7.5v2"/></svg>
        </button>
      {/if}
      <!-- Export -->
      <div class="relative">
        <button
          class="p-2 rounded-lg transition-colors backdrop-blur-sm active:scale-[0.95]"
          style="background: var(--quip-input-bg); border: 1px solid var(--quip-border); color: var(--quip-text-dim)"
          onclick={(e) => { e.stopPropagation(); showExportMenu = !showExportMenu; }}
          title={$t('chat.export')}
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </button>
        {#if showExportMenu}
          <div
            class="quip-export-menu absolute right-0 top-full mt-1 rounded-xl p-1 z-20 min-w-36"
            transition:fly={{ y: -4, duration: D2, easing: easeOut }}
          >
            <button class="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 rounded-lg transition-colors" onclick={handleExportMarkdown}>
              {$t('chat.exportMarkdown')}
            </button>
          </div>
        {/if}
      </div>
    </header>
  </div>
</div>
