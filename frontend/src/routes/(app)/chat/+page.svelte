<script lang="ts">
  import { t, locale } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { fade, fly } from 'svelte/transition';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { getRandomBackronym, getBackronyms, getHeadlineName } from '$lib/quip/backronyms';
  import { D2, D3, easeOut } from '$lib/motion';
  import { messages } from '$lib/stores/chat';
  import { streamChat, regenerateMessage, editMessage } from '$lib/api/chats';
  import type { UploadedFile } from '$lib/api/files';
  import ModelSelector from '$lib/components/chat/ModelSelector.svelte';
  import ChatInput from '$lib/components/chat/ChatInput.svelte';
  import { selectedWorkspace, selectedWorkspaceId, selectWorkspace } from '$lib/stores/workspaces';
  import { activeDrawer, closeDrawer, openDrawer } from '$lib/stores/drawer';

  // ChatPane (and its heavy deps: MessageList, MessageBubble, markdown, katex, hljs,
  // ArtifactPanel) is never needed on the home screen — load it asynchronously.
  let ChatPane = $state<any>(null);

  let backronym = $state('');
  let headline = $state('QUIP');
  let chatId = $state<string | undefined>(undefined);
  let mounted = $state(false);
  let hasMessages = $derived($messages.length > 0);
  let workspaceId = $derived(page.url.searchParams.get('workspace') ?? $selectedWorkspaceId ?? undefined);

  $effect(() => {
    const requested = page.url.searchParams.get('workspace');
    if (requested && requested !== $selectedWorkspaceId) selectWorkspace(requested);
  });

  $effect(() => {
    const lang = $locale ?? 'en';
    headline = getHeadlineName(lang);
    if (!backronym) backronym = getRandomBackronym(lang);
  });

  onMount(() => {
    messages.set([]);
    chatId = undefined;
    mounted = true;
    // Preload chat pane (MessageList + composer + artifacts) off the critical path
    import('$lib/components/chat/ChatPane.svelte').then(m => { ChatPane = m.default; });
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
    const newChatId = await streamChat(
      text,
      chatId,
      fileIds.length ? fileIds : undefined,
      uploadedFiles.length ? uploadedFiles : undefined,
      undefined,
      false,
      workspaceId,
    );
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

<div class="relative flex flex-col h-full">
  {#if hasMessages}
    {#if ChatPane}
      {@const Pane = ChatPane}
      <Pane
        chatId={chatId}
        onSend={handleSend}
        onRegenerate={handleRegenerate}
        onEdit={handleEdit}
        {workspaceId}
      />
    {/if}
    <!-- Floating header (overlay so content scrolls beneath, scrim can blur it) -->
    <div class="absolute left-0 right-0 top-0 z-10">
      <div class="quip-header-scrim" aria-hidden="true"></div>
      <header class="relative flex items-center pl-14 sm:pl-4 pr-4 py-3 justify-between">
        <ModelSelector variant="pill" />
        {#if workspaceId}
          <button
            class="p-2 rounded-lg transition-colors backdrop-blur-sm"
            style="background: var(--quip-input-bg); border: 1px solid var(--quip-border); color: var(--quip-text-dim)"
            onclick={() => $activeDrawer === 'files' ? closeDrawer() : openDrawer('files')}
            title={$t('workspace.files')}
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 7.5h7l2 2h9v9.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7.5Z"/><path d="M3 7.5v-2A2.5 2.5 0 0 1 5.5 3H9l2 2h7.5A2.5 2.5 0 0 1 21 7.5v2"/></svg>
          </button>
        {/if}
      </header>
    </div>
  {:else}
    <!-- ═══ START SCREEN ═══ -->
    <div class="quip-aurora flex-1 flex flex-col items-center justify-center relative px-6">
      {#if mounted}
        <div class="relative z-10 flex flex-col items-center w-full max-w-2xl">
          <div class="relative inline-block mb-3" in:fly={{ y: 12, duration: D3, easing: easeOut }}>
            <h1 class="quip-hero-word text-[96px] md:text-[132px] select-none text-center m-0">
              {headline}
            </h1>
            <span class="quip-beta absolute top-2 -right-1 translate-x-full">beta</span>
          </div>
          <div class="relative min-h-4 w-full mb-7 px-4">
            {#key backronym}
              <p
                in:fade={{ duration: D2, delay: 80 }}
                out:fade={{ duration: D2 }}
                class="quip-mono absolute inset-x-4 text-center text-[10px] uppercase tracking-[0.32em] leading-snug"
                style="color: var(--quip-text-dim)"
              >
                {backronym}
              </p>
            {/key}
          </div>
        </div>

        <div
          in:fly={{ y: 12, duration: D3, delay: 120, easing: easeOut }}
          class="relative z-30 mb-5"
        >
          <ModelSelector variant="picker" />
        </div>

        {#if $selectedWorkspace}
          <a href={`/workspace/${$selectedWorkspace.id}`} class="relative z-20 mb-3 text-[11px] px-3 py-1.5 rounded-full hover:bg-white/[.05]" style="color: var(--quip-text-muted); border: 1px solid var(--quip-border)">
            {$t('workspace.label')}: {$selectedWorkspace.name}
          </a>
        {/if}

        <div in:fly={{ y: 12, duration: D3, delay: 180, easing: easeOut }} class="relative z-10 w-full max-w-3xl">
          <ChatInput onSend={handleSend} chatId={chatId} {workspaceId} variant="start" />
        </div>

        <p in:fade={{ duration: D2, delay: 260 }} class="relative z-10 text-[10px] mt-6 text-center opacity-40" style="color: var(--quip-text-muted)">{$t('home.disclaimer')}</p>
      {/if}
    </div>
  {/if}
</div>
