<script lang="ts">
  import { t } from 'svelte-i18n';
  import { fetchWorkspaceOverview, type WorkspaceFile } from '$lib/api/workspaces';
  import { getFileUrl } from '$lib/api/files';
  import { closeDrawer } from '$lib/stores/drawer';

  let { workspaceId }: { workspaceId: string } = $props();
  let files = $state<WorkspaceFile[]>([]);
  let loading = $state(true);
  let loadError = $state(false);

  $effect(() => {
    const id = workspaceId;
    let current = true;
    files = [];
    loadError = false;
    loading = true;
    fetchWorkspaceOverview(id)
      .then((overview) => {
        if (current) files = overview.files;
      })
      .catch(() => {
        if (current) loadError = true;
      })
      .finally(() => {
        if (current) loading = false;
      });
    return () => { current = false; };
  });

  function size(bytes: number | null) {
    if (!bytes) return '—';
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  function statusLabel(status: string | null) {
    const keys: Record<string, string> = {
      pending: 'workspace.embeddingPending',
      processing: 'workspace.embeddingProcessing',
      completed: 'workspace.embeddingCompleted',
      failed: 'workspace.embeddingFailed',
      skipped: 'workspace.embeddingSkipped',
    };
    return $t(keys[status ?? 'pending'] ?? 'workspace.embeddingUnknown');
  }
</script>

<div class="flex flex-col h-full">
  <div class="flex items-center justify-between px-4 py-3 border-b" style="border-color: var(--quip-border)">
    <div>
      <h3 class="font-medium text-sm">{$t('workspace.files')}</h3>
      <a href={`/workspace/${workspaceId}`} class="text-[10px]" style="color: var(--quip-link)">{$t('workspace.openHome')} →</a>
    </div>
    <button class="quip-theme-hover p-1.5 rounded-lg" onclick={closeDrawer} aria-label={$t('common.close')}>
      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
    </button>
  </div>
  <div class="flex-1 overflow-y-auto p-3">
    {#if loading}
      <p class="text-xs p-4" style="color: var(--quip-text-muted)">{$t('common.loading')}</p>
    {:else if loadError}
      <p class="text-xs p-4 text-center" style="color: var(--quip-text-muted)">{$t('workspace.filesLoadError')}</p>
    {:else}
      {#each files as file (file.id)}
        <a href={getFileUrl(file.id)} target="_blank" class="quip-theme-hover flex gap-3 items-center rounded-xl p-3">
          <span class="w-9 h-9 rounded-lg flex items-center justify-center text-[10px] uppercase" style="background: var(--quip-hover); color: var(--quip-text-muted)">{file.filename.split('.').pop()?.slice(0, 3) ?? 'file'}</span>
          <span class="min-w-0 flex-1">
            <span class="block text-sm truncate" style="color: var(--quip-text-dim)">{file.filename}</span>
            <span class="block text-[10px] mt-0.5" style="color: var(--quip-text-muted)">{size(file.size)} · {statusLabel(file.embedding_status)}</span>
          </span>
        </a>
      {:else}
        <p class="text-xs p-4 text-center" style="color: var(--quip-text-muted)">{$t('workspace.noFiles')}</p>
      {/each}
    {/if}
  </div>
</div>
