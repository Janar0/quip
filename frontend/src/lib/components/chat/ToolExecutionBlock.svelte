<script lang="ts">
  import type { ToolExecution } from '$lib/stores/sandbox';
  import { getHljs, hljsLoaded } from '$lib/utils/markdown';
  import { t } from 'svelte-i18n';

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
    $hljsLoaded;
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
      load_skill: `skill: ${parsedArgs.name ?? ''}`,
      generate_music: `generate music: ${(parsedArgs.prompt as string | undefined)?.slice(0, 48) ?? ''}`,
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

  let statusColor = $derived(
    isRunning ? 'var(--quip-text-muted)' : isError ? '#f87171' : isSuccess ? '#34d399' : 'var(--quip-text-muted)'
  );

  function getFileUrl(path: string): string {
    return `/api/sandbox/${chatId}/file/${encodeURIComponent(path)}`;
  }
</script>

<div class="group/tool">
  <!-- Header row -->
  <button
    class="flex items-center gap-2 w-full py-1 rounded transition-colors text-left cursor-pointer"
    style="color: var(--quip-text-muted)"
    onmouseenter={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--quip-text-dim)' }}
    onmouseleave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--quip-text-muted)' }}
    onclick={() => (expanded = !expanded)}
  >
    <!-- Status indicator -->
    <span class="flex-shrink-0 w-3.5 h-3.5 flex items-center justify-center">
      {#if isRunning}
        <span class="spinner-ring" style="width: 9px; height: 9px; border-width: 1.5px; border-top-color: {statusColor}"></span>
      {:else if isError}
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="#f87171" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
      {:else if isSuccess}
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
      {:else}
        <span class="block w-1.5 h-1.5 rounded-full" style="background: {statusColor}"></span>
      {/if}
    </span>

    <!-- Tool label -->
    <span class="font-mono text-[11px] flex-1 min-w-0 truncate opacity-50">{toolLabel}</span>

    <!-- Exit code badge -->
    {#if !isRunning && exitCode !== undefined && exitCode !== 0}
      <span class="text-[9px] font-mono px-1 py-0.5 rounded flex-shrink-0" style="background: rgba(127,29,29,0.4); color: #f87171">exit {exitCode}</span>
    {/if}

    <!-- Expand chevron -->
    {#if codeContent || r?.stdout || r?.stderr || (r?.files_created as string[] | undefined)?.length}
      <svg
        class="w-3 h-3 flex-shrink-0 opacity-40"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.5"
        stroke-linecap="round"
        stroke-linejoin="round"
        style="transition: transform var(--quip-d-2) var(--quip-ease-out); transform: rotate({expanded ? 90 : 0}deg)"
      >
        <path d="M9 5l7 7-7 7" />
      </svg>
    {/if}
  </button>

  <!-- Expandable body -->
  <div
    class="grid"
    style:grid-template-rows={expanded ? '1fr' : '0fr'}
    style:transition="grid-template-rows var(--quip-d-2) var(--quip-ease-out)"
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
