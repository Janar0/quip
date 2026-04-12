<script lang="ts">
  import {
    selectedArtifactId,
    artifactVersions,
    allArtifacts,
    closeArtifactPanel,
    selectArtifact,
  } from '$lib/stores/artifacts';
  import { downloadFile, getExtension } from '$lib/utils/download';
  import { toast } from 'svelte-sonner';
  import { t } from 'svelte-i18n';
  import ArtifactRenderer from './ArtifactRenderer.svelte';
  import type { Artifact } from '$lib/stores/chat';

  let artifact = $derived.by(() => {
    const all = $allArtifacts;
    return all.find((a) => a.id === $selectedArtifactId) ?? null;
  });

  let versions = $derived.by(() => {
    if (!artifact) return [];
    return $artifactVersions.get(artifact.identifier) ?? [];
  });

  function copy() {
    if (!artifact) return;
    navigator.clipboard.writeText(artifact.content);
    toast.success($t('toast.copied'));
  }

  function download() {
    if (!artifact) return;
    const ext =
      artifact.type === 'html'
        ? '.html'
        : artifact.type === 'svg'
          ? '.svg'
          : artifact.type === 'mermaid'
            ? '.mmd'
            : artifact.type === 'code'
              ? getExtension(artifact.language)
              : '.json';
    const filename = (artifact.title || 'artifact').replace(/[^a-zA-Z0-9_-]/g, '_') + ext;
    downloadFile(filename, artifact.content);
  }
</script>

{#if artifact}
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-slate-800">
      <div class="flex items-center gap-2 min-w-0">
        <h3 class="font-medium text-sm truncate">{artifact.title}</h3>
        {#if versions.length > 1}
          <select
            class="text-xs bg-slate-900/50 border border-slate-800 rounded px-1.5 py-0.5"
            value={artifact.id}
            onchange={(e) => selectArtifact((e.target as HTMLSelectElement).value)}
          >
            {#each versions as v}
              <option value={v.id}>v{v.version}</option>
            {/each}
          </select>
        {/if}
      </div>
      <button
        class="p-1 rounded hover:bg-slate-800 opacity-50 hover:opacity-100 transition-opacity"
        onclick={closeArtifactPanel}
        title={$t('artifacts.close')}
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-auto">
      <ArtifactRenderer {artifact} />
    </div>

    <!-- Footer actions -->
    <div class="flex items-center gap-2 px-4 py-2 border-t border-slate-800">
      <button
        class="text-xs px-3 py-1.5 rounded-lg bg-slate-900/50 hover:bg-slate-800 transition-colors"
        onclick={copy}
      >
        {$t('artifacts.copy')}
      </button>
      <button
        class="text-xs px-3 py-1.5 rounded-lg bg-slate-900/50 hover:bg-slate-800 transition-colors"
        onclick={download}
      >
        {$t('artifacts.download')}
      </button>
    </div>
  </div>
{/if}
