<script lang="ts">
  import { t } from 'svelte-i18n';
  import type { SourceInfo } from '$lib/utils/markdown';

  let { sources }: { sources: SourceInfo[] } = $props();
  let open = $state(false);
</script>

<div class="mt-3 pt-2 border-t border-slate-800/50">
  <button
    type="button"
    class="text-xs text-slate-500 hover:text-slate-400 select-none transition-colors flex items-center gap-1"
    onclick={() => (open = !open)}
  >
    <span
      class="inline-block transition-transform"
      style:transform={open ? 'rotate(90deg)' : ''}
      style:transition-duration="var(--quip-d-1)"
    >▸</span>
    {$t('chat.sources')} ({sources.length})
  </button>
  <div
    class="grid"
    style:grid-template-rows={open ? '1fr' : '0fr'}
    style:transition="grid-template-rows var(--quip-d-2) var(--quip-ease-out)"
  >
    <div class="overflow-hidden">
      <div class="mt-1.5 flex flex-col gap-1.5">
        {#each sources as src (src.num)}
          <a href={src.url} target="_blank" rel="noopener noreferrer" class="source-card">
            <div
              class="flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center"
              style="background: var(--quip-hover)"
            >
              <img
                src="https://www.google.com/s2/favicons?domain={src.domain}&sz=32"
                alt=""
                class="w-5 h-5 rounded-sm"
              />
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium truncate" style="color: var(--quip-text)">{src.title}</div>
              <div class="text-xs truncate" style="color: var(--quip-text-muted)">{src.domain}</div>
            </div>
            <div class="flex-shrink-0 source-card-icon">
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </div>
          </a>
        {/each}
      </div>
    </div>
  </div>
</div>
