<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    icon = '',
    title,
    description = '',
    actions,
  }: {
    icon?: string;
    title: string;
    description?: string;
    actions?: Snippet;
  } = $props();
</script>

<header class="admin-page-head">
  <div class="flex items-start gap-3 min-w-0">
    {#if icon}
      <span class="admin-page-icon">
        <svg class="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d={icon} /></svg>
      </span>
    {/if}
    <div class="min-w-0">
      <h1 class="admin-page-title truncate">{title}</h1>
      {#if description}<p class="admin-page-desc">{description}</p>{/if}
    </div>
  </div>
  {#if actions}
    <div class="shrink-0 flex items-center gap-2">{@render actions()}</div>
  {/if}
</header>
