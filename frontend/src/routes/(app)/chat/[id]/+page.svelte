<script lang="ts">
  import { page } from '$app/state';
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import { fly } from 'svelte/transition';
  import { D2, easeOut } from '$lib/motion';
  import { loadChat, streamChat, regenerateMessage, editMessage } from '$lib/api/chats';
  import { activeChat, messages, isLoading } from '$lib/stores/chat';
  import type { UploadedFile } from '$lib/api/files';
  import { artifactPanelOpen } from '$lib/stores/artifacts';
  import { exportAsJSON, exportAsMarkdown } from '$lib/utils/export';
  import ModelSelector from '$lib/components/chat/ModelSelector.svelte';
  import MessageList from '$lib/components/chat/MessageList.svelte';
  import ChatInput from '$lib/components/chat/ChatInput.svelte';
  import ArtifactPanel from '$lib/components/artifacts/ArtifactPanel.svelte';

  let chatId = $derived(page.params.id ?? '');
  let showExportMenu = $state(false);

  $effect(() => {
    if (chatId) loadChat(chatId);
  });

  async function handleSend(text: string, fileIds: string[] = [], uploadedFiles: UploadedFile[] = []) {
    await streamChat(text, chatId, fileIds.length ? fileIds : undefined, uploadedFiles.length ? uploadedFiles : undefined);
  }

  function handleRegenerate(messageId: string) {
    if (chatId) regenerateMessage(chatId, messageId);
  }

  function handleEdit(messageId: string, content: string) {
    if (chatId) editMessage(chatId, messageId, content);
  }

  function handleExportJSON() {
    if ($activeChat) {
      exportAsJSON($activeChat, $messages);
      toast.success($t('toast.exported'));
    }
    showExportMenu = false;
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

<div class="flex flex-col h-full">
  <header class="flex items-center justify-between pl-14 sm:pl-3 pr-3 py-2.5 border-b backdrop-blur-md" style="border-color: var(--quip-border); background: color-mix(in srgb, var(--quip-bg) 50%, transparent)">
    <div class="flex items-center gap-2 min-w-0">
      <ModelSelector />
      {#if $activeChat}
        <span class="hidden sm:block text-sm text-slate-500 truncate max-w-[200px]">{$activeChat.title}</span>
      {/if}
    </div>
    <!-- Export -->
    <div class="relative">
      <button
        class="p-2 rounded-lg border border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-700 transition-all active:scale-[0.95]"
        onclick={(e) => { e.stopPropagation(); showExportMenu = !showExportMenu; }}
        title={$t('chat.export')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      </button>
      {#if showExportMenu}
        <div
          class="absolute right-0 top-full mt-1 rounded-xl p-1 z-20 min-w-36 shadow-xl shadow-black/30"
          style="background: var(--quip-bg-raised); border: 1px solid var(--quip-border-strong)"
          transition:fly={{ y: -4, duration: D2, easing: easeOut }}
        >
          <button class="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 rounded-lg transition-colors" onclick={handleExportJSON}>
            {$t('chat.exportJSON')}
          </button>
          <button class="w-full text-left px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 rounded-lg transition-colors" onclick={handleExportMarkdown}>
            {$t('chat.exportMarkdown')}
          </button>
        </div>
      {/if}
    </div>
  </header>

  <div class="flex flex-1 overflow-hidden">
    <div class="flex flex-col flex-1 min-w-0">
      {#if $isLoading && !$messages.length}
        <div class="flex-1 flex items-center justify-center">
          <div class="w-6 h-6 border-2 border-slate-800 border-t-slate-300 rounded-full animate-spin"></div>
        </div>
      {:else}
        <MessageList onRegenerate={handleRegenerate} onEdit={handleEdit} />
      {/if}
      <ChatInput onSend={handleSend} chatId={chatId} />
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
</div>
