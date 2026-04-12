<script lang="ts">
  import type { ToolExecution } from '$lib/stores/sandbox';
  import { getHljs, hljsLoaded } from '$lib/utils/markdown';
  import WidgetCard from './WidgetCard.svelte';

  let { execution, chatId }: { execution: ToolExecution; chatId: string } = $props();

  let expanded = $state(false);
  let isRunning = $derived(execution.status === 'running');
  let r = $derived(execution.result as Record<string, unknown> | undefined);
  let isWidget = $derived(!!r?.widget);
  let isError = $derived(execution.status === 'error' || !!r?.error || ((r?.exit_code as number) ?? 0) !== 0);
  let isSuccess = $derived(execution.status === 'completed' && !r?.error && ((r?.exit_code as number) ?? 0) === 0);

  let parsedArgs = $derived.by(() => {
    try {
      return JSON.parse(execution.arguments ?? '{}');
    } catch {
      return {};
    }
  });

  let codeContent = $derived(parsedArgs.code ?? '');
  let language = $derived(parsedArgs.language ?? '');

  let highlightedCode = $derived.by(() => {
    $hljsLoaded; // re-run when hljs loads
    if (!codeContent) return '';
    const hljs = getHljs();
    if (!hljs) return codeContent.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    try {
      if (language && hljs.getLanguage(language)) {
        return hljs.highlight(codeContent, { language }).value;
      }
      return hljs.highlightAuto(codeContent).value;
    } catch {
      return codeContent.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
  });

  let toolLabel = $derived.by(() => {
    const labels: Record<string, string> = {
      sandbox_execute: language ? `run ${language}` : 'execute',
      sandbox_install: `pip install ${parsedArgs.packages?.join(' ') ?? ''}`,
      sandbox_write_file: `write ${parsedArgs.path ?? ''}`,
      sandbox_read_file: `read ${parsedArgs.path ?? ''}`,
      sandbox_list_files: 'ls',
      web_search: `search "${parsedArgs.query ?? ''}"`,
      read_url: `fetch ${parsedArgs.url ?? ''}`,
      use_widget: parsedArgs.name ?? 'widget',
    };
    return labels[execution.name] ?? execution.name;
  });

  // Status-based accent color (CSS var approach for left border)
  let accentColor = $derived(
    isRunning ? '#60a5fa' : isError ? '#f87171' : isSuccess ? '#34d399' : '#475569'
  );

  let exitCode = $derived((r?.exit_code as number | undefined));

  function getFileUrl(path: string): string {
    const token = localStorage.getItem('access_token');
    return `/api/sandbox/${chatId}/file/${encodeURIComponent(path)}?token=${encodeURIComponent(token ?? '')}`;
  }
</script>

<!-- Each block is a row inside the shared container — no outer border, just separator -->
<div class="group/tool" style="border-left: 2px solid {accentColor}">
  <!-- Header row -->
  <button
    class="flex items-center gap-2.5 w-full px-3 py-2 hover:bg-slate-800/30 transition-colors text-left"
    onclick={() => (expanded = !expanded)}
  >
    <!-- Animated status indicator -->
    <span class="flex-shrink-0 w-1.5 h-1.5 rounded-full {isRunning ? 'animate-pulse bg-blue-400' : isError ? 'bg-red-400' : isSuccess ? 'bg-emerald-400' : 'bg-slate-600'}"></span>

    <!-- Tool label — monospace -->
    <span class="font-mono text-[11px] text-slate-300/75 flex-1 min-w-0 truncate">{toolLabel}</span>

    <!-- Exit code badge -->
    {#if !isRunning && exitCode !== undefined && exitCode !== 0}
      <span class="text-[9px] font-mono px-1 py-0.5 rounded bg-red-950/60 text-red-400/70 flex-shrink-0">exit {exitCode}</span>
    {/if}

    <!-- Expand chevron -->
    <span
      class="flex-shrink-0 text-[10px] text-slate-600 transition-transform"
      style:transform={expanded ? 'rotate(90deg)' : ''}
      style:transition-duration="150ms"
    >▶</span>
  </button>

  <!-- Expandable body -->
  <div
    class="grid"
    style:grid-template-rows={isWidget || expanded ? '1fr' : '0fr'}
    style:transition="grid-template-rows 150ms ease-out"
  >
    <div class="overflow-hidden">
      {#if isWidget}
        <div class="px-2 pb-2 pt-1">
          <WidgetCard templateName={(r?.template as string) ?? ''} data={(r?.data as Record<string, unknown>) ?? {}} />
        </div>
      {:else}
        <!-- Code block -->
        {#if codeContent}
          <div class="border-t border-slate-800/40 bg-slate-950/60 overflow-x-auto">
            <pre class="px-4 py-3 text-[11px] leading-relaxed font-mono m-0"><code>{@html highlightedCode}</code></pre>
          </div>
        {/if}

        <!-- stdout -->
        {#if r?.stdout}
          <div class="border-t border-slate-800/40 px-4 py-2.5 bg-slate-950/30">
            <span class="text-[9px] font-mono uppercase tracking-widest text-emerald-400/40">stdout</span>
            <pre class="mt-1 text-[11px] text-slate-400/80 whitespace-pre-wrap font-mono leading-relaxed">{r.stdout as string}</pre>
          </div>
        {/if}

        <!-- stderr -->
        {#if r?.stderr}
          <div class="border-t border-slate-800/40 px-4 py-2.5 bg-red-950/10">
            <span class="text-[9px] font-mono uppercase tracking-widest text-red-400/40">stderr</span>
            <pre class="mt-1 text-[11px] text-red-300/60 whitespace-pre-wrap font-mono leading-relaxed">{r.stderr as string}</pre>
          </div>
        {/if}

        <!-- Created files -->
        {#if (r?.files_created as string[] | undefined)?.length}
          <div class="border-t border-slate-800/40 px-3 py-2 flex flex-wrap gap-1.5">
            {#each (r!.files_created as string[]) as file}
              <a
                href={getFileUrl(file)}
                target="_blank"
                class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/60 text-slate-400 hover:bg-slate-700/60 hover:text-slate-200 transition-colors text-[11px] font-mono"
              >
                <svg class="w-3 h-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                {file}
              </a>
            {/each}
          </div>
        {/if}
      {/if}
    </div>
  </div>
</div>
