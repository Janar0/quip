<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    title = '',
    description = '',
    class: klass = '',
    children,
    actions,
  }: {
    title?: string;
    description?: string;
    class?: string;
    children: Snippet;
    actions?: Snippet;
  } = $props();
</script>

<section class="admin-card {klass}">
  {#if title || actions}
    <div class="admin-card-head flex items-start justify-between gap-3">
      {#if title}
        <div class="min-w-0">
          <h2 class="admin-card-title">{title}</h2>
          {#if description}<p class="admin-card-desc">{description}</p>{/if}
        </div>
      {/if}
      {#if actions}<div class="shrink-0 flex items-center gap-2">{@render actions()}</div>{/if}
    </div>
  {/if}
  {@render children()}
</section>
