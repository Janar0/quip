<script lang="ts">
  import { t } from 'svelte-i18n';
  import { fade, scale } from 'svelte/transition';
  import { D1, D2, easeOut } from '$lib/motion';

  let { open = false, onClose }: { open: boolean; onClose: () => void } = $props();

  const shortcuts = [
    { keys: ['/'], label: 'shortcuts.focusInput' },
    { keys: ['Ctrl', 'Shift', 'N'], label: 'shortcuts.newChat' },
    { keys: ['?'], label: 'shortcuts.showShortcuts' },
    { keys: ['Esc'], label: 'shortcuts.closeSidebar' },
    { keys: ['Enter'], label: 'shortcuts.sendMessage' },
    { keys: ['Shift', 'Enter'], label: 'shortcuts.newLine' },
  ];

  function handleKeydown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  }
</script>

{#if open}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
    transition:fade={{ duration: D1 }}
    onclick={onClose}
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
      <h3 class="text-lg font-semibold text-slate-100">{$t('shortcuts.title')}</h3>
      <div class="space-y-2">
        {#each shortcuts as s}
          <div class="flex items-center justify-between text-sm">
            <span class="text-slate-400">{$t(s.label)}</span>
            <span class="flex gap-1">
              {#each s.keys as key}
                <kbd class="bg-slate-800 px-2 py-0.5 rounded text-xs font-mono text-slate-300">{key}</kbd>
              {/each}
            </span>
          </div>
        {/each}
      </div>
      <button class="w-full px-3 py-1.5 text-sm rounded-lg border border-slate-700 text-slate-400 hover:text-slate-200 transition-all active:scale-[0.98]" onclick={onClose}>{$t('common.cancel')}</button>
    </div>
  </div>
{/if}
