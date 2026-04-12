<script lang="ts">
  import type { Artifact } from '$lib/stores/chat';
  import { selectArtifact } from '$lib/stores/artifacts';
  import { downloadFile, getExtension } from '$lib/utils/download';
  import { toast } from 'svelte-sonner';
  import { t } from 'svelte-i18n';
  import ArtifactRenderer from './ArtifactRenderer.svelte';

  let { artifact }: { artifact: Artifact } = $props();

  function copy() {
    navigator.clipboard.writeText(artifact.content);
    toast.success($t('toast.copied'));
  }

  function download() {
    const ext = artifact.type === 'html' ? '.html'
      : artifact.type === 'svg' ? '.svg'
      : artifact.type === 'mermaid' ? '.mmd'
      : artifact.type === 'code' ? getExtension(artifact.language)
      : '.json';
    const filename = (artifact.title || 'artifact').replace(/[^a-zA-Z0-9_-]/g, '_') + ext;
    downloadFile(filename, artifact.content);
  }
</script>

<div class="rounded-xl border border-slate-800 overflow-hidden my-3">
  <div class="flex items-center justify-between px-3 py-1.5 bg-slate-900/50 text-xs">
    <span class="font-medium opacity-70">{artifact.title}</span>
    <div class="flex gap-1">
      <button
        class="px-1.5 py-0.5 rounded hover:bg-slate-800 opacity-50 hover:opacity-100 transition-opacity"
        title={$t('artifacts.expand')}
        onclick={() => selectArtifact(artifact.id)}
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" />
        </svg>
      </button>
      <button
        class="px-1.5 py-0.5 rounded hover:bg-slate-800 opacity-50 hover:opacity-100 transition-opacity"
        title={$t('artifacts.download')}
        onclick={download}
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
      </button>
      <button
        class="px-1.5 py-0.5 rounded hover:bg-slate-800 opacity-50 hover:opacity-100 transition-opacity"
        title={$t('artifacts.copy')}
        onclick={copy}
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      </button>
    </div>
  </div>
  <div class="bg-slate-950/50">
    <ArtifactRenderer {artifact} />
  </div>
</div>
