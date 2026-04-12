<script lang="ts">
  import { t, locale } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { fade, fly } from 'svelte/transition';
  import { goto } from '$app/navigation';
  import { getRandomBackronym, getBackronyms, getHeadlineName } from '$lib/quip/backronyms';
  import { D2, D3, easeOut } from '$lib/motion';
  import { messages, modePreference } from '$lib/stores/chat';
  import { artifactPanelOpen } from '$lib/stores/artifacts';
  import { streamChat, regenerateMessage, editMessage } from '$lib/api/chats';
  import type { UploadedFile } from '$lib/api/files';
  import ModelSelector from '$lib/components/chat/ModelSelector.svelte';
  import ChatInput from '$lib/components/chat/ChatInput.svelte';
  import ArtifactPanel from '$lib/components/artifacts/ArtifactPanel.svelte';

  // MessageList (and its heavy deps: MessageBubble, markdown, katex, hljs) is never
  // needed on the home screen — load it asynchronously after mount.
  let MessageList = $state<any>(null);

  let backronym = $state('');
  let headline = $state('QUIP');
  let chatId = $state<string | undefined>(undefined);
  let mounted = $state(false);
  let hasMessages = $derived($messages.length > 0);

  $effect(() => {
    const lang = $locale ?? 'en';
    headline = getHeadlineName(lang);
    if (!backronym) backronym = getRandomBackronym(lang);
  });

  onMount(() => {
    messages.set([]);
    chatId = undefined;
    mounted = true;
    // Preload message rendering stack off the critical path
    import('$lib/components/chat/MessageList.svelte').then(m => { MessageList = m.default; });
    const id = setInterval(() => {
      const list = getBackronyms($locale ?? 'en');
      if (list.length < 2) return;
      let next = backronym;
      while (next === backronym) next = list[Math.floor(Math.random() * list.length)];
      backronym = next;
    }, 7000);
    return () => clearInterval(id);
  });

  async function handleSend(text: string, fileIds: string[] = [], uploadedFiles: UploadedFile[] = []) {
    const newChatId = await streamChat(text, chatId, fileIds.length ? fileIds : undefined, uploadedFiles.length ? uploadedFiles : undefined);
    if (newChatId && !chatId) {
      chatId = newChatId;
      goto(`/chat/${newChatId}`, { replaceState: true });
    }
  }

  function handleRegenerate(messageId: string) {
    if (chatId) regenerateMessage(chatId, messageId);
  }

  function handleEdit(messageId: string, content: string) {
    if (chatId) editMessage(chatId, messageId, content);
  }
</script>

<div class="flex flex-col h-full">
  {#if hasMessages}
    <!-- Header (shown once conversation starts) -->
    <header class="flex items-center justify-between pl-14 sm:pl-3 pr-3 py-2.5 border-b" style="border-color: var(--quip-border)">
      <ModelSelector />
    </header>
  {/if}

  <div class="flex flex-1 overflow-hidden">
    <div class="flex flex-col flex-1 min-w-0">
      {#if hasMessages}
        {#if MessageList}
          <svelte:component this={MessageList} onRegenerate={handleRegenerate} onEdit={handleEdit} />
        {/if}
        <ChatInput onSend={handleSend} chatId={chatId} />
      {:else}
        <!-- ═══ START SCREEN ═══ -->
        <div class="flex-1 flex flex-col items-center justify-center relative">
          <!-- Subtle radial glow -->
          <div class="absolute inset-0 bg-[radial-gradient(circle_at_50%_40%,rgba(15,23,42,0.6)_0%,transparent_70%)]"></div>

          {#if mounted}
            <div class="relative z-10 flex flex-col items-center gap-3 mb-6 w-full max-w-2xl">
              <div class="relative inline-block" in:fly={{ y: 12, duration: D3, easing: easeOut }}>
                <h1
                  class="font-headline text-7xl md:text-8xl font-extrabold tracking-tighter select-none text-center"
                  style="color: var(--quip-text)"
                >
                  {headline}
                </h1>
                <span class="absolute -top-2 -right-1 translate-x-full text-[9px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-400 border border-indigo-500/30 select-none">beta</span>
              </div>
              <div class="relative h-4 w-full">
                {#key backronym}
                  <p
                    in:fade={{ duration: D2, delay: 80 }}
                    out:fade={{ duration: D2 }}
                    class="absolute inset-x-0 text-center text-[10px] uppercase tracking-[0.4em] whitespace-nowrap"
                    style="color: var(--quip-text-muted)"
                  >
                    {backronym}
                  </p>
                {/key}
              </div>
            </div>

            {#if $modePreference === 'auto'}
              <div in:fly={{ y: 12, duration: D3, delay: 120, easing: easeOut }} class="relative z-10 mb-4">
                <ModelSelector />
              </div>
            {/if}

            <div in:fly={{ y: 12, duration: D3, delay: 180, easing: easeOut }} class="relative z-10 w-full max-w-3xl px-4">
              <ChatInput onSend={handleSend} chatId={chatId} variant="start" />
            </div>

            <p in:fade={{ duration: D2, delay: 260 }} class="relative z-10 text-[11px] mt-6 text-center" style="color: var(--quip-text-muted)">{$t('home.disclaimer')}</p>
          {/if}
        </div>
      {/if}
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
