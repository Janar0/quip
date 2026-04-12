<script lang="ts">
  import type { PrimarySourceInfo } from '$lib/utils/markdown';
  import { t } from 'svelte-i18n';
  import { fly } from 'svelte/transition';
  import { D2, easeOut } from '$lib/motion';

  let { primarySource }: { primarySource: PrimarySourceInfo } = $props();

  let domain = $derived.by(() => {
    try {
      return new URL(primarySource.url).hostname.replace(/^www\./, '');
    } catch {
      return primarySource.url;
    }
  });
</script>

<a
  href={primarySource.url}
  target="_blank"
  rel="noopener noreferrer"
  class="group block rounded-xl border p-3 mb-3 transition-all hover:border-slate-700 active:scale-[0.99]"
  style="background: var(--quip-bg-raised); border-color: var(--quip-border-strong)"
  in:fly={{ y: -4, duration: D2, easing: easeOut }}
>
  <div class="flex items-center gap-2 mb-1">
    <img
      src={`https://www.google.com/s2/favicons?domain=${domain}&sz=32`}
      alt=""
      class="w-4 h-4 rounded"
      loading="lazy"
    />
    <span class="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">
      {$t('chat.primarySource')}
    </span>
    <span class="text-xs text-slate-500 ml-auto truncate max-w-[40%]">{domain}</span>
    <svg
      class="w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 transition-colors flex-shrink-0"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  </div>
  <div class="text-sm font-medium text-slate-200 leading-snug">{primarySource.title}</div>
  {#if primarySource.summary}
    <div class="text-xs text-slate-400 mt-1 line-clamp-2 leading-relaxed">{primarySource.summary}</div>
  {/if}
</a>
