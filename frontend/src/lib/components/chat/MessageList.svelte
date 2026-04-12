<script lang="ts">
  import { messages, isStreaming } from '$lib/stores/chat';
  import { t } from 'svelte-i18n';
  import { buildThread, type ThreadMessage } from '$lib/utils/thread';
  import MessageBubble from './MessageBubble.svelte';
  import { tick } from 'svelte';

  let {
    onRegenerate,
    onEdit,
  }: {
    onRegenerate?: (messageId: string) => void;
    onEdit?: (messageId: string, content: string) => void;
  } = $props();

  let container: HTMLDivElement;
  let isAtBottom = $state(true);
  let userSentMessage = $state(false);

  // Branch selections: parentId → selectedChildId
  let branchSelections = $state<Record<string, string>>({});

  // Build thread from messages + selections
  let thread = $derived(buildThread($messages, branchSelections));

  function selectSibling(parentId: string | null | undefined, siblingId: string) {
    const key = parentId ?? '__root__';
    branchSelections = { ...branchSelections, [key]: siblingId };
  }

  function checkScroll() {
    if (!container) return;
    isAtBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 80;
  }

  function scrollToBottom() {
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  }

  // Auto-scroll only if user was at bottom or just sent a message
  $effect(() => {
    if ($messages.length > 0 && (isAtBottom || userSentMessage)) {
      tick().then(() => {
        if (container) {
          container.scrollTop = container.scrollHeight;
        }
        userSentMessage = false;
      });
    }
  });

  // Detect when user sends a message (temp-user appears)
  $effect(() => {
    if ($messages.some((m) => m.id === 'temp-user')) {
      userSentMessage = true;
    }
  });
</script>

<div bind:this={container} class="flex-1 overflow-y-auto py-6 relative" onscroll={checkScroll}>
  <div class="max-w-4xl mx-auto w-full space-y-8">
    {#each thread as message (message.id)}
      <div>
        <MessageBubble {message} {onRegenerate} {onEdit} />
        {#if message.siblingCount > 1}
          <div class="flex items-center justify-center gap-2 mt-1">
            <button
              class="p-0.5 rounded hover:bg-slate-800 disabled:opacity-20 transition-colors"
              disabled={message.siblingIndex <= 1}
              onclick={() => selectSibling(message.parent_id, message.siblingIds[message.siblingIndex - 2])}
              aria-label="Previous branch"
            >
              <svg class="w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg>
            </button>
            <span class="text-xs text-slate-600 tabular-nums">{message.siblingIndex} / {message.siblingCount}</span>
            <button
              class="p-0.5 rounded hover:bg-slate-800 disabled:opacity-20 transition-colors"
              disabled={message.siblingIndex >= message.siblingCount}
              onclick={() => selectSibling(message.parent_id, message.siblingIds[message.siblingIndex])}
              aria-label="Next branch"
            >
              <svg class="w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
            </button>
          </div>
        {/if}
      </div>
    {/each}
  </div>

  {#if !isAtBottom}
    <button
      class="sticky bottom-4 left-1/2 -translate-x-1/2 z-10 p-2 rounded-full bg-slate-800 border border-slate-700 hover:bg-slate-700 backdrop-blur-sm transition-all shadow-lg text-slate-300"
      onclick={scrollToBottom}
      title={$t('chat.scrollToBottom')}
      aria-label={$t('chat.scrollToBottom')}
    >
      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 13l5 5 5-5M7 6l5 5 5-5"/></svg>
    </button>
  {/if}
</div>
