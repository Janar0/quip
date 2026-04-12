<script lang="ts">
  import type { MessageInfo } from '$lib/stores/chat';
  import { isStreaming } from '$lib/stores/chat';
  import {
    renderMarkdown,
    extractSources,
    extractPrimarySource,
    resolveSearchImagePlaceholders,
    hljsLoaded,
    katexLoaded,
    type SourceInfo,
    type ImageMode,
  } from '$lib/utils/markdown';
  import { stripArtifactTags } from '$lib/utils/artifacts';
  import { formatRelativeTime } from '$lib/utils/time';
  import { getFileUrl } from '$lib/api/files';
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import { fly } from 'svelte/transition';
  import { D2, easeOut, prm } from '$lib/motion';
  import InlineArtifact from '$lib/components/artifacts/InlineArtifact.svelte';
  import ToolExecutionBlock from '$lib/components/chat/ToolExecutionBlock.svelte';
  import SearchProgress from '$lib/components/chat/SearchProgress.svelte';
  import SearchImageGrid from '$lib/components/chat/SearchImageGrid.svelte';
  import PrimarySourceBanner from '$lib/components/chat/PrimarySourceBanner.svelte';
  import DeepResearchProgress from '$lib/components/chat/DeepResearchProgress.svelte';
  import FileAttachment from '$lib/components/chat/FileAttachment.svelte';

  let {
    message,
    onRegenerate,
    onEdit,
  }: {
    message: MessageInfo;
    onRegenerate?: (messageId: string) => void;
    onEdit?: (messageId: string, content: string) => void;
  } = $props();

  let isUser = $derived(message.role === 'user');
  let isAssistant = $derived(message.role === 'assistant');
  let hasReasoning = $derived(!!message.reasoning);
  let hasContent = $derived(!!message.content);
  let isStreamingEmpty = $derived(message.id === 'streaming' && !message.content);
  let reasoningOpen = $state(false);
  let toolsOpen = $state(false);
  let sourcesOpen = $state(false);
  let editing = $state(false);
  let editText = $state('');
  const SEARCH_TOOLS = new Set(['web_search', 'read_url']);
  let hasArtifacts = $derived(!!(message.artifacts?.length));
  let hasToolExecs = $derived(!!(message.toolExecutions?.length));
  let searchExecs = $derived((message.toolExecutions ?? []).filter((e) => SEARCH_TOOLS.has(e.name)));
  let sandboxExecs = $derived((message.toolExecutions ?? []).filter((e) => !SEARCH_TOOLS.has(e.name)));
  let hasSearchExecs = $derived(searchExecs.length > 0);
  let hasSandboxExecs = $derived(sandboxExecs.length > 0);
  let hasRunningTools = $derived(sandboxExecs.some((e) => e.status === 'running'));
  $effect(() => {
    if (hasRunningTools) toolsOpen = true;
  });
  let hasResearch = $derived(!!(message.researchHistory?.length && message.researchStatus));
  // `hasTopGrid` is set in the derive chain below after the image mode is resolved
  // from the model's `![](search-image:...)` markers.
  // Files starting with _ or temp/tmp prefix are AI-internal intermediates — hide from user
  const _TEMP_FILE_RE = /^(temp[_\-.~]|tmp[_\-.~]|_)/i;
  let createdFiles = $derived.by(() => {
    if (!sandboxExecs.length) return [];
    const files: string[] = [];
    for (const exec of sandboxExecs) {
      const created = (exec.result as Record<string, unknown> | undefined)?.files_created as string[] | undefined;
      if (created) {
        for (const f of created) {
          if (!files.includes(f) && !_TEMP_FILE_RE.test(f)) files.push(f);
        }
      }
    }
    return files;
  });
  let imageAttachments = $derived(
    (message.attachments ?? [])
      .filter((a) => a.file_type === 'image')
      .map((a) => ({ ...a, url: getFileUrl(a.file_id) })),
  );
  let docAttachments = $derived((message.attachments ?? []).filter((a) => a.file_type === 'document'));
  let hasAttachments = $derived(imageAttachments.length > 0 || docAttachments.length > 0);
  // Always strip artifact tags — even during streaming when hasArtifacts is still false
  // (incomplete <artifact> tags contain raw HTML that would inject into the page via {@html})
  let stripped = $derived(isUser ? message.content : stripArtifactTags(message.content));
  let primarySourceResult = $derived(
    isUser ? { primarySource: null, stripped } : extractPrimarySource(stripped),
  );
  let imageResolved = $derived(
    isUser
      ? { text: primarySourceResult.stripped, imageMode: 'none' as ImageMode }
      : resolveSearchImagePlaceholders(primarySourceResult.stripped, message.searchImages),
  );
  let extracted = $derived(
    isUser
      ? { cleanContent: imageResolved.text, sources: [] as SourceInfo[] }
      : extractSources(imageResolved.text),
  );
  let rendered = $derived.by(() => {
    $hljsLoaded; $katexLoaded; // re-run when lazy libs load
    return isUser ? '' : renderMarkdown(extracted.cleanContent, extracted.sources, message.chat_id);
  });
  let primarySource = $derived(primarySourceResult.primarySource);
  let imageMode = $derived(imageResolved.imageMode);
  let sources = $derived(extracted.sources);
  let hasTopGrid = $derived(
    imageMode === 'top' && !!(message.searchImages && message.searchImages.length >= 2),
  );
  let timestamp = $derived(message.created_at ? formatRelativeTime(message.created_at) : '');
  let fullDate = $derived(message.created_at ? new Date(message.created_at).toLocaleString() : '');

  function copyContent() {
    navigator.clipboard.writeText(message.content);
    toast.success($t('toast.copied'));
  }

  function startEdit() {
    editText = message.content;
    editing = true;
  }

  function cancelEdit() {
    editing = false;
    editText = '';
  }

  function submitEdit() {
    if (editText.trim() && editText !== message.content) {
      onEdit?.(message.id, editText.trim());
    }
    editing = false;
  }

  function editKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitEdit();
    }
    if (e.key === 'Escape') {
      cancelEdit();
    }
  }

  let shouldAnimate = $derived(message.id !== 'streaming' && message.id !== 'temp-user');
  let entryParams = $derived(
    shouldAnimate
      ? { y: 8, duration: prm(D2), easing: easeOut }
      : { duration: 0 },
  );
</script>

<!-- AI messages: full-width editorial layout. User messages: right-aligned pill. -->
{#if isUser}
  <!-- ═══ USER MESSAGE ═══ -->
  <div class="group flex justify-end px-4" in:fly={entryParams}>
    <div class="max-w-[75%]">
      <div class="rounded-2xl rounded-tr-sm px-4 py-3" style="background: var(--quip-user-msg); border: 1px solid var(--quip-border)">
        {#if hasAttachments}
          {#if imageAttachments.length}
            <div class="flex flex-wrap gap-2 mb-2">
              {#each imageAttachments as img (img.file_id)}
                <div class="relative">
                  <a href={img.url} target="_blank" rel="noopener" class="block">
                    <img
                      src={img.url}
                      alt={img.filename}
                      loading="lazy"
                      class="max-w-[300px] max-h-[300px] rounded-lg object-contain cursor-pointer hover:opacity-80 transition-opacity"
                      onerror={(e) => { const el = e.currentTarget as HTMLImageElement; el.style.display = 'none'; el.nextElementSibling?.classList.remove('hidden'); }}
                    />
                    <div class="hidden items-center gap-2 px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700/30 text-sm">
                      <svg class="w-4 h-4 opacity-50 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
                      <span class="truncate max-w-48">{img.filename}</span>
                    </div>
                  </a>
                </div>
              {/each}
            </div>
          {/if}
          {#if docAttachments.length}
            <div class="flex flex-wrap gap-2 mb-2">
              {#each docAttachments as att (att.file_id)}
                <div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700/30 text-sm">
                  <svg class="w-4 h-4 opacity-50 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  <span class="truncate max-w-48">{att.filename}</span>
                </div>
              {/each}
            </div>
          {/if}
        {/if}
        {#if editing}
          <textarea
            class="w-full min-h-20 bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-600 resize-none"
            bind:value={editText}
            onkeydown={editKeydown}
          ></textarea>
          <div class="flex gap-2 mt-2">
            <button class="px-3 py-1.5 text-sm rounded-lg bg-slate-100 text-slate-950 hover:bg-white transition-colors" onclick={submitEdit}>{$t('common.save')}</button>
            <button class="px-3 py-1.5 text-sm rounded-lg border border-slate-700 text-slate-400 hover:text-slate-200 transition-colors" onclick={cancelEdit}>{$t('common.cancel')}</button>
          </div>
        {:else}
          <div class="whitespace-pre-wrap break-words" style="color: var(--quip-text)">{message.content}</div>
        {/if}
      </div>
      <!-- User action buttons -->
      {#if hasContent && !$isStreaming && !editing && message.id !== 'streaming' && message.id !== 'temp-user'}
        <div class="flex items-center gap-1 mt-1 justify-end mr-1">
          {#if timestamp}
            <span class="text-xs opacity-0 group-hover:opacity-30 transition-opacity mr-1 text-slate-500" title={fullDate}>{timestamp}</span>
          {/if}
          <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <button class="p-1 rounded hover:bg-slate-800 transition-all active:scale-[0.88]" onclick={copyContent} title={$t('chat.copy')} aria-label={$t('chat.copy')}>
              <svg class="w-4 h-4 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
            </button>
            {#if onEdit}
              <button class="p-1 rounded hover:bg-slate-800 transition-all active:scale-[0.88]" onclick={startEdit} title={$t('chat.edit')} aria-label={$t('chat.edit')}>
                <svg class="w-4 h-4 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              </button>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  </div>
{:else}
  <!-- ═══ ASSISTANT MESSAGE ═══ -->
  <div class="group px-4" in:fly={entryParams}>
    <div class="{hasArtifacts || hasToolExecs ? 'max-w-full' : 'max-w-full'}">
      <!-- Role label: icon + QUIP + model -->
      <div class="flex items-center gap-1.5 mb-2">
        <svg class="w-4 h-4 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="currentColor" opacity="0.3" stroke="none"/>
          <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/>
        </svg>
        <span class="text-[10px] font-bold text-slate-500 uppercase tracking-widest">QUIP</span>
        {#if message.model}
          <span class="text-[10px] text-slate-600">&middot;</span>
          <span class="text-[10px] text-slate-600">{message.model}</span>
        {/if}
      </div>

      {#if hasReasoning}
        <div class="mb-3">
          <button
            type="button"
            class="text-xs text-slate-500 hover:text-slate-400 select-none transition-colors flex items-center gap-1"
            aria-expanded={reasoningOpen}
            onclick={() => (reasoningOpen = !reasoningOpen)}
          >
            <span
              class="inline-block transition-transform"
              style:transform={reasoningOpen ? 'rotate(90deg)' : ''}
              style:transition-duration="var(--quip-d-1)"
            >▸</span>
            {reasoningOpen ? $t('chat.hideThinking') : $t('chat.showThinking')} ({message.reasoning?.length} {$t('chat.chars')})
          </button>
          <div
            class="grid"
            style:grid-template-rows={reasoningOpen ? '1fr' : '0fr'}
            style:transition="grid-template-rows var(--quip-d-2) var(--quip-ease-out)"
          >
            <div class="overflow-hidden">
              <div class="mt-1.5 text-sm text-slate-400 break-words border-l-2 border-slate-800 pl-3 prose prose-invert prose-sm max-w-none">
                {@html renderMarkdown(message.reasoning ?? '')}
              </div>
            </div>
          </div>
        </div>
      {/if}

      {#if hasAttachments}
        {#if imageAttachments.length}
          <div class="flex flex-wrap gap-2 mb-3">
            {#each imageAttachments as img (img.file_id)}
              <div class="relative">
                <a href={img.url} target="_blank" rel="noopener" class="block">
                  <img
                    src={img.url}
                    alt={img.filename}
                    loading="lazy"
                    class="max-w-[300px] max-h-[300px] rounded-lg object-contain cursor-pointer hover:opacity-80 transition-opacity"
                    onerror={(e) => { const el = e.currentTarget as HTMLImageElement; el.style.display = 'none'; el.nextElementSibling?.classList.remove('hidden'); }}
                  />
                  <div class="hidden items-center gap-2 px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700/30 text-sm">
                    <svg class="w-4 h-4 opacity-50 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
                    <span class="truncate max-w-48">{img.filename}</span>
                  </div>
                </a>
              </div>
            {/each}
          </div>
        {/if}
        {#if docAttachments.length}
          <div class="flex flex-wrap gap-2 mb-3">
            {#each docAttachments as att (att.file_id)}
              <div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700/30 text-sm">
                <svg class="w-4 h-4 opacity-50 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span class="truncate max-w-48">{att.filename}</span>
              </div>
            {/each}
          </div>
        {/if}
      {/if}

      {#if hasResearch}
        <DeepResearchProgress history={message.researchHistory!} current={message.researchStatus!} />
      {/if}
      {#if hasSearchExecs}
        <SearchProgress executions={searchExecs} />
      {/if}

      {#if primarySource}
        <PrimarySourceBanner {primarySource} />
      {/if}

      {#if hasTopGrid}
        <SearchImageGrid images={message.searchImages!} />
      {/if}

      {#if isStreamingEmpty}
        <div class="typing-dots py-1">
          <span></span><span></span><span></span>
        </div>
      {:else}
        <div class="prose prose-invert prose-sm max-w-none break-words">{@html rendered}</div>
      {/if}

      {#if hasSandboxExecs}
        <div class="my-2">
          <button
            type="button"
            class="text-xs text-slate-500 hover:text-slate-400 select-none transition-colors flex items-center gap-1.5"
            aria-expanded={toolsOpen}
            onclick={() => (toolsOpen = !toolsOpen)}
          >
            {#if hasRunningTools}
              <span class="animate-spin text-slate-400 text-[10px]">&#9696;</span>
            {:else}
              <svg class="w-3.5 h-3.5 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              </svg>
            {/if}
            <span>{hasRunningTools ? $t('chat.usingTools') : $t('chat.usedTools')} ({sandboxExecs.length})</span>
            <span
              class="inline-block transition-transform opacity-60"
              style:transform={toolsOpen ? 'rotate(90deg)' : ''}
              style:transition-duration="var(--quip-d-1)"
            >▸</span>
          </button>
          <div
            class="grid"
            style:grid-template-rows={toolsOpen ? '1fr' : '0fr'}
            style:transition="grid-template-rows var(--quip-d-2) var(--quip-ease-out)"
          >
            <div class="overflow-hidden">
              <div class="mt-1.5 rounded-lg overflow-hidden border border-slate-800/60 bg-slate-950/40 divide-y divide-slate-800/40">
                {#each sandboxExecs as execution (execution.id)}
                  <ToolExecutionBlock {execution} chatId={message.chat_id} />
                {/each}
              </div>
            </div>
          </div>
        </div>
        {#if createdFiles.length}
          <div class="flex flex-col gap-1 mt-2">
            {#each createdFiles as file (file)}
              <FileAttachment filename={file} chatId={message.chat_id} />
            {/each}
          </div>
        {/if}
      {/if}

      {#if hasArtifacts}
        {#each message.artifacts! as artifact (artifact.id)}
          <InlineArtifact {artifact} />
        {/each}
      {/if}

      {#if sources.length > 0}
        <div class="mt-3 pt-2 border-t border-slate-800/50">
          <button
            type="button"
            class="text-xs text-slate-500 hover:text-slate-400 select-none transition-colors flex items-center gap-1"
            onclick={() => (sourcesOpen = !sourcesOpen)}
          >
            <span
              class="inline-block transition-transform"
              style:transform={sourcesOpen ? 'rotate(90deg)' : ''}
              style:transition-duration="var(--quip-d-1)"
            >▸</span>
            {$t('chat.sources')} ({sources.length})
          </button>
          <div
            class="grid"
            style:grid-template-rows={sourcesOpen ? '1fr' : '0fr'}
            style:transition="grid-template-rows var(--quip-d-2) var(--quip-ease-out)"
          >
            <div class="overflow-hidden">
              <div class="mt-1.5 flex flex-col gap-1.5">
                {#each sources as src (src.num)}
                  <a href={src.url} target="_blank" rel="noopener noreferrer" class="source-card">
                    <div class="flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center" style="background: var(--quip-hover)">
                      <img src="https://www.google.com/s2/favicons?domain={src.domain}&sz=32" alt="" class="w-5 h-5 rounded-sm" />
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="text-sm font-medium truncate" style="color: var(--quip-text)">{src.title}</div>
                      <div class="text-xs truncate" style="color: var(--quip-text-muted)">{src.domain}</div>
                    </div>
                    <div class="flex-shrink-0 source-card-icon">
                      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                        <polyline points="15 3 21 3 21 9"/>
                        <line x1="10" y1="14" x2="21" y2="3"/>
                      </svg>
                    </div>
                  </a>
                {/each}
              </div>
            </div>
          </div>
        </div>
      {/if}

      {#if message.cost}
        <div class="text-xs text-slate-600 mt-1 text-right">${Number(message.cost).toFixed(4)}</div>
      {/if}

      <!-- Assistant action buttons -->
      {#if hasContent && !$isStreaming && message.id !== 'streaming' && message.id !== 'temp-user'}
        <div class="flex items-center gap-1 mt-1.5 ml-0">
          {#if timestamp}
            <span class="text-xs opacity-0 group-hover:opacity-100 transition-opacity mr-1 text-slate-600" title={fullDate}>{timestamp}</span>
          {/if}
          <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <button class="p-1 rounded hover:bg-slate-800 transition-all active:scale-[0.88]" onclick={copyContent} title={$t('chat.copy')} aria-label={$t('chat.copy')}>
              <svg class="w-4 h-4 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
            </button>
            {#if onRegenerate}
              <button class="p-1 rounded hover:bg-slate-800 transition-all active:scale-[0.88]" onclick={() => onRegenerate(message.id)} title={$t('chat.regenerate')} aria-label={$t('chat.regenerate')}>
                <svg class="w-4 h-4 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
              </button>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  </div>
{/if}
