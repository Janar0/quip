<script lang="ts">
  import { getHljs, hljsLoaded } from '$lib/utils/markdown';
  import { toast } from 'svelte-sonner';
  import { t } from 'svelte-i18n';
  import { downloadFile, getExtension } from '$lib/utils/download';

  let { content, language = '' }: { content: string; language?: string } = $props();

  let highlighted = $derived.by(() => {
    $hljsLoaded; // re-run when hljs loads
    const hljs = getHljs();
    if (!hljs) return content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    try {
      if (language && hljs.getLanguage(language)) {
        return hljs.highlight(content, { language }).value;
      }
      return hljs.highlightAuto(content).value;
    } catch {
      return content.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
  });

  let lines = $derived(content.split('\n'));

  function copy() {
    navigator.clipboard.writeText(content);
    toast.success($t('common.copied'));
  }

  function download() {
    const ext = getExtension(language);
    downloadFile(`artifact${ext}`, content);
  }
</script>

<div class="relative group">
  <div class="flex items-center justify-between px-3 py-1 text-xs" style="background: var(--quip-bg-elevated)">
    {#if language}
      <span class="opacity-40">{language}</span>
    {:else}
      <span></span>
    {/if}
    <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button class="px-1.5 py-0.5 rounded hover:bg-slate-800 opacity-50 hover:opacity-100" onclick={copy}>{$t('chat.copy')}</button>
      <button class="px-1.5 py-0.5 rounded hover:bg-slate-800 opacity-50 hover:opacity-100" onclick={download}>{$t('artifacts.download')}</button>
    </div>
  </div>
  <div class="overflow-x-auto">
    <pre class="text-sm p-3 leading-relaxed"><code>{@html highlighted}</code></pre>
  </div>
</div>
