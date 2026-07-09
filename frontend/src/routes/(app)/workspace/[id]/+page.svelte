<script lang="ts">
  import { page } from '$app/state';
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import {
    fetchWorkspaceOverview,
    updateWorkspace,
    type WorkspaceOverview,
  } from '$lib/api/workspaces';
  import { getFileUrl } from '$lib/api/files';
  import { loadWorkspaces, selectWorkspace } from '$lib/stores/workspaces';

  let workspaceId = $derived(page.params.id ?? '');
  let overview = $state<WorkspaceOverview | null>(null);
  let loading = $state(true);
  let editing = $state(false);
  let saving = $state(false);
  let name = $state('');
  let description = $state('');
  let instructions = $state('');

  $effect(() => {
    const id = workspaceId;
    if (!id) return;
    selectWorkspace(id);
    loading = true;
    fetchWorkspaceOverview(id)
      .then((data) => {
        overview = data;
        name = data.workspace.name;
        description = data.workspace.description ?? '';
        instructions = data.workspace.instructions ?? '';
      })
      .catch(() => toast.error($t('workspace.loadError')))
      .finally(() => (loading = false));
  });

  async function saveSettings() {
    if (!overview || !name.trim()) return;
    saving = true;
    try {
      const workspace = await updateWorkspace(overview.workspace.id, {
        name: name.trim(),
        description: description.trim() || null,
        instructions: instructions.trim() || null,
      });
      overview = { ...overview, workspace };
      editing = false;
      await loadWorkspaces();
      toast.success($t('workspace.saved'));
    } catch {
      toast.error($t('common.error'));
    } finally {
      saving = false;
    }
  }

  function formatSize(bytes: number | null): string {
    if (!bytes) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
</script>

{#if loading}
  <div class="flex flex-1 items-center justify-center">
    <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color: var(--quip-border); border-top-color: var(--quip-text-dim)"></div>
  </div>
{:else if overview}
  <div class="flex-1 overflow-y-auto">
    <div class="max-w-6xl mx-auto px-5 sm:px-8 py-8 sm:py-12 space-y-8">
      <header class="flex flex-col sm:flex-row sm:items-start gap-5 justify-between">
        <div class="min-w-0">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-[10px] uppercase tracking-[0.2em]" style="color: var(--quip-text-muted)">{$t('workspace.label')}</span>
            {#if overview.workspace.is_personal}
              <span class="text-[9px] uppercase rounded-full px-2 py-0.5" style="background: var(--quip-hover); color: var(--quip-text-muted)">{$t('workspace.personal')}</span>
            {/if}
          </div>
          <h1 class="text-3xl sm:text-4xl font-headline font-bold tracking-tight" style="color: var(--quip-text)">{overview.workspace.name}</h1>
          {#if overview.workspace.description}
            <p class="mt-2 max-w-2xl text-sm leading-relaxed" style="color: var(--quip-text-dim)">{overview.workspace.description}</p>
          {/if}
        </div>
        <div class="flex gap-2 shrink-0">
          <button class="btn preset-outlined text-sm" onclick={() => (editing = !editing)}>{$t('workspace.settings')}</button>
          <a class="btn preset-filled-primary-500 text-sm" href={`/chat?workspace=${overview.workspace.id}`}>+ {$t('nav.newChat')}</a>
        </div>
      </header>

      {#if editing}
        <section class="rounded-2xl p-5 sm:p-6 space-y-4" style="background: var(--quip-bg-elevated); border: 1px solid var(--quip-border-strong)">
          <div class="grid sm:grid-cols-2 gap-4">
            <label class="label">
              <span>{$t('workspace.name')}</span>
              <input class="input" bind:value={name} maxlength="255" />
            </label>
            <label class="label">
              <span>{$t('workspace.description')}</span>
              <input class="input" bind:value={description} maxlength="4000" />
            </label>
          </div>
          <label class="label">
            <span>{$t('workspace.instructions')}</span>
            <span class="text-xs opacity-50 mb-1">{$t('workspace.instructionsHint')}</span>
            <textarea class="textarea min-h-36" bind:value={instructions} maxlength="20000"></textarea>
          </label>
          <div class="flex justify-end gap-2">
            <button class="btn preset-outlined" onclick={() => (editing = false)}>{$t('common.cancel')}</button>
            <button class="btn preset-filled-primary-500" onclick={saveSettings} disabled={saving || !name.trim()}>{saving ? '…' : $t('common.save')}</button>
          </div>
        </section>
      {:else}
        <section class="rounded-2xl p-5 sm:p-6" style="background: linear-gradient(135deg, var(--quip-bg-elevated), transparent); border: 1px solid var(--quip-border)">
          <div class="flex items-center gap-2 mb-3">
            <svg class="w-4 h-4" style="color: var(--quip-text-muted)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M9 18h6M10 22h4M8.5 14.5A7 7 0 1 1 15.5 14.5c-.9.7-1.5 1.4-1.5 2.5h-4c0-1.1-.6-1.8-1.5-2.5Z"/></svg>
            <h2 class="text-xs uppercase tracking-[0.16em]" style="color: var(--quip-text-muted)">{$t('workspace.instructions')}</h2>
          </div>
          {#if overview.workspace.instructions}
            <p class="text-sm whitespace-pre-wrap leading-relaxed max-w-4xl" style="color: var(--quip-text-dim)">{overview.workspace.instructions}</p>
          {:else}
            <button class="text-sm text-left opacity-50 hover:opacity-80" onclick={() => (editing = true)}>{$t('workspace.addInstructions')}</button>
          {/if}
        </section>
      {/if}

      <div class="grid lg:grid-cols-[1.25fr_.75fr] gap-6">
        <section class="min-w-0">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-sm font-semibold" style="color: var(--quip-text)">{$t('workspace.recentChats')}</h2>
            <span class="text-xs" style="color: var(--quip-text-muted)">{overview.chats.length}</span>
          </div>
          <div class="grid sm:grid-cols-2 gap-2.5">
            {#each overview.chats as chat (chat.id)}
              <a href={`/chat/${chat.id}`} class="group rounded-xl p-4 transition-colors hover:bg-white/[.04]" style="background: var(--quip-bg-elevated); border: 1px solid var(--quip-border)">
                <div class="font-medium text-sm truncate" style="color: var(--quip-text)">{chat.title}</div>
                <div class="mt-2 flex items-center justify-between gap-2 text-[11px]" style="color: var(--quip-text-muted)">
                  <span class="truncate">{chat.model ?? $t('workspace.defaultModel')}</span>
                  <span>{new Date(chat.updated_at).toLocaleDateString()}</span>
                </div>
              </a>
            {:else}
              <a href={`/chat?workspace=${overview.workspace.id}`} class="sm:col-span-2 rounded-xl p-6 text-center text-sm border border-dashed opacity-60 hover:opacity-90" style="border-color: var(--quip-border-strong)">{$t('workspace.startFirstChat')}</a>
            {/each}
          </div>
        </section>

        <section class="min-w-0">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-sm font-semibold" style="color: var(--quip-text)">{$t('workspace.files')}</h2>
            <span class="text-xs" style="color: var(--quip-text-muted)">{overview.files.length}</span>
          </div>
          <div class="rounded-xl overflow-hidden" style="background: var(--quip-bg-elevated); border: 1px solid var(--quip-border)">
            {#each overview.files as file, index (file.id)}
              <a href={getFileUrl(file.id)} target="_blank" class="flex items-center gap-3 px-3.5 py-3 hover:bg-white/[.04]" style:border-top={index ? '1px solid var(--quip-border)' : 'none'}>
                <span class="w-8 h-8 rounded-lg flex items-center justify-center text-xs uppercase" style="background: var(--quip-hover); color: var(--quip-text-muted)">{file.filename.split('.').pop()?.slice(0, 3) ?? 'file'}</span>
                <span class="min-w-0 flex-1">
                  <span class="block text-sm truncate" style="color: var(--quip-text-dim)">{file.filename}</span>
                  <span class="block text-[10px] mt-0.5" style="color: var(--quip-text-muted)">{formatSize(file.size)} · {file.embedding_status ?? '—'}</span>
                </span>
              </a>
            {:else}
              <p class="p-6 text-center text-xs opacity-40">{$t('workspace.noFiles')}</p>
            {/each}
          </div>
        </section>
      </div>
    </div>
  </div>
{/if}
