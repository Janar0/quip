<script lang="ts">
  import type { ToolExecution } from '$lib/stores/sandbox';
  import { getHljs, hljsLoaded } from '$lib/utils/markdown';

  let { execution, chatId }: { execution: ToolExecution; chatId: string } = $props();

  let expanded = $state(false);
  let isRunning = $derived(execution.status === 'running');
  let r = $derived(execution.result as Record<string, unknown> | undefined);
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

  let exitCode = $derived((r?.exit_code as number | undefined));

  let dotClass = $derived(
    isRunning ? 'animate-pulse' : ''
  );
  let dotColor = $derived(
    isRunning ? '#60a5fa' : isError ? '#f87171' : isSuccess ? '#34d399' : '#475569'
  );

  function getFileUrl(path: string): string {
    const token = localStorage.getItem('access_token');
    return `/api/sandbox/${chatId}/file/${encodeURIComponent(path)}?token=${encodeURIComponent(token ?? '')}`;
  }
</script>

<div class="group/tool">
  <!-- Header row -->
  <button
    class="flex items-center gap-2 w-full px-1 py-1 rounded transition-colors text-left"
    style="hover:background: var(--quip-hover)"
    onmouseenter={(e) => (e.currentTarget as HTMLElement).style.background = 'var(--quip-hover)'}
    onmouseleave={(e) => (e.currentTarget as HTMLElement).style.background = ''}
    onclick={() => (expanded = !expanded)}
  >
    <!-- Status dot -->
    <span
      class="flex-shrink-0 w-1.5 h-1.5 rounded-full {dotClass}"
      style="background: {dotColor}"
    ></span>

    <!-- Tool label -->
    <span class="font-mono text-[11px] flex-1 min-w-0 truncate" style="color: var(--quip-text-dim)">{toolLabel}</span>

    <!-- Exit code badge -->
    {#if !isRunning && exitCode !== undefined && exitCode !== 0}
      <span class="text-[9px] font-mono px-1 py-0.5 rounded flex-shrink-0" style="background: rgba(127,29,29,0.4); color: #f87171">exit {exitCode}</span>
    {/if}

    <!-- Expand chevron — only show if there's expandable content -->
    {#if codeContent || r?.stdout || r?.stderr || (r?.files_created as string[] | undefined)?.length}
      <span
        class="flex-shrink-0 text-[10px] transition-transform"
        style="color: var(--quip-text-muted); transform: {expanded ? 'rotate(90deg)' : 'rotate(0deg)'}; transition-duration: 150ms"
      >▶</span>
    {/if}
  </button>

  <!-- Expandable body -->
  <div
    class="grid"
    style:grid-template-rows={expanded ? '1fr' : '0fr'}
    style:transition="grid-template-rows 150ms ease-out"
  >
    <div class="overflow-hidden">
      <!-- Code block -->
      {#if codeContent}
        <div class="rounded overflow-x-auto mt-0.5" style="background: var(--quip-code-bg); border: 1px solid var(--quip-border)">
          <pre class="px-3 py-2 text-[11px] leading-relaxed font-mono m-0"><code>{@html highlightedCode}</code></pre>
        </div>
      {/if}

      <!-- stdout -->
      {#if r?.stdout}
        <div class="mt-0.5 px-3 py-2 rounded" style="background: var(--quip-code-bg); border: 1px solid var(--quip-border)">
          <span class="text-[9px] font-mono uppercase tracking-widest" style="color: #34d399; opacity: 0.5">stdout</span>
          <pre class="mt-1 text-[11px] whitespace-pre-wrap font-mono leading-relaxed" style="color: var(--quip-text-dim)">{r.stdout as string}</pre>
        </div>
      {/if}

      <!-- stderr -->
      {#if r?.stderr}
        <div class="mt-0.5 px-3 py-2 rounded" style="background: rgba(127,29,29,0.06); border: 1px solid var(--quip-border)">
          <span class="text-[9px] font-mono uppercase tracking-widest" style="color: #f87171; opacity: 0.5">stderr</span>
          <pre class="mt-1 text-[11px] whitespace-pre-wrap font-mono leading-relaxed" style="color: #f87171; opacity: 0.7">{r.stderr as string}</pre>
        </div>
      {/if}

      <!-- Created files -->
      {#if (r?.files_created as string[] | undefined)?.length}
        <div class="mt-0.5 flex flex-wrap gap-1.5">
          {#each (r!.files_created as string[]) as file}
            <a
              href={getFileUrl(file)}
              target="_blank"
              class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-mono transition-colors"
              style="background: var(--quip-bg-raised); color: var(--quip-text-dim); border: 1px solid var(--quip-border)"
            >
              <svg class="w-3 h-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              {file}
            </a>
          {/each}
        </div>
      {/if}
    </div>
  </div>
</div>
