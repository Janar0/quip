<script lang="ts">
  import { t } from 'svelte-i18n';
  import { fetchWorkspaceOverview, type WorkspaceFile } from '$lib/api/workspaces';
  import { getFileUrl } from '$lib/api/files';
  import { closeDrawer } from '$lib/stores/drawer';

  let { workspaceId }: { workspaceId: string } = $props();
  let files = $state<WorkspaceFile[]>([]);
  let loading = $state(true);

  $effect(() => {
    const id = workspaceId;
    loading = true;
    fetchWorkspaceOverview(id)
      .then((overview) => (files = overview.files))
      .finally(() => (loading = false));
  });

  function size(bytes: number | null) {
    if (!bytes) return '—';
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
</script>

<div class="flex flex-col h-full">
  <div class="flex items-center justify-between px-4 py-3 border-b" style="border-color: var(--quip-border)">
    <div>
      <h3 class="font-medium text-sm">{$t('workspace.files')}</h3>
      <a href={`/workspace/${workspaceId}`} class="text-[10px] opacity-50 hover:opacity-80">{$t('workspace.openHome')} →</a>
    </div>
    <button class="p-1.5 rounded-lg hover:bg-white/[.06]" onclick={closeDrawer} aria-label={$t('common.close')}>
      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
    </button>
  </div>
  <div class="flex-1 overflow-y-auto p-3">
    {#if loading}
      <p class="text-xs opacity-40 p-4">{$t('common.loading')}</p>
    {:else}
      {#each files as file (file.id)}
        <a href={getFileUrl(file.id)} target="_blank" class="flex gap-3 items-center rounded-xl p-3 hover:bg-white/[.04]">
          <span class="w-9 h-9 rounded-lg flex items-center justify-center text-[10px] uppercase" style="background: var(--quip-hover); color: var(--quip-text-muted)">{file.filename.split('.').pop()?.slice(0, 3) ?? 'file'}</span>
          <span class="min-w-0 flex-1">
            <span class="block text-sm truncate" style="color: var(--quip-text-dim)">{file.filename}</span>
            <span class="block text-[10px] mt-0.5" style="color: var(--quip-text-muted)">{size(file.size)} · {file.embedding_status}</span>
          </span>
        </a>
      {:else}
        <p class="text-xs opacity-40 p-4 text-center">{$t('workspace.noFiles')}</p>
      {/each}
    {/if}
  </div>
</div>
