<script lang="ts">
  import { t } from 'svelte-i18n';
  import { fade, scale } from 'svelte/transition';
  import { D1, D2, easeOut } from '$lib/motion';

  let {
    open = false,
    title = '',
    message = '',
    confirmLabel = '',
    onConfirm,
    onCancel,
  }: {
    open: boolean;
    title: string;
    message?: string;
    confirmLabel?: string;
    onConfirm: () => void;
    onCancel: () => void;
  } = $props();

  let cancelBtn = $state<HTMLButtonElement>();

  $effect(() => {
    if (open && cancelBtn) {
      cancelBtn.focus();
    }
  });

  function handleKeydown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      onConfirm();
    }
  }
</script>

{#if open}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
    transition:fade={{ duration: D1 }}
    onclick={onCancel}
    onkeydown={handleKeydown}
  ></div>
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="pointer-events-auto bg-slate-900 border border-slate-800 rounded-xl p-6 w-full max-w-sm space-y-4 shadow-xl"
      in:scale={{ duration: D2, start: 0.96, easing: easeOut }}
      out:scale={{ duration: D1, start: 0.98, easing: easeOut }}
      role="dialog"
      aria-modal="true"
      tabindex="-1"
      onclick={(e) => e.stopPropagation()}
    >
      <h3 class="text-lg font-semibold text-slate-100">{title}</h3>
      {#if message}
        <p class="text-sm text-slate-400">{message}</p>
      {/if}
      <div class="flex justify-end gap-2">
        <button bind:this={cancelBtn} class="px-3 py-1.5 text-sm rounded-lg border border-slate-700 text-slate-400 hover:text-slate-200 transition-all active:scale-[0.97]" onclick={onCancel}>
          {$t('common.cancel')}
        </button>
        <button class="px-3 py-1.5 text-sm rounded-lg bg-red-600 text-white hover:bg-red-500 transition-all active:scale-[0.97]" onclick={onConfirm}>
          {confirmLabel || $t('confirm.delete')}
        </button>
      </div>
    </div>
  </div>
{/if}
