<script lang="ts">
  import { goto } from '$app/navigation';
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import {
    addWorkspace,
    selectWorkspace,
    selectedWorkspace,
    workspaces,
  } from '$lib/stores/workspaces';

  let { onchange }: { onchange?: () => void | Promise<void> } = $props();

  let open = $state(false);
  let creating = $state(false);
  let name = $state('');
  let saving = $state(false);

  async function choose(id: string) {
    selectWorkspace(id);
    open = false;
    await onchange?.();
    await goto(`/workspace/${id}`);
  }

  async function create() {
    const trimmed = name.trim();
    if (!trimmed || saving) return;
    saving = true;
    try {
      const workspace = await addWorkspace({ name: trimmed });
      name = '';
      creating = false;
      open = false;
      await onchange?.();
      await goto(`/workspace/${workspace.id}`);
    } catch {
      toast.error($t('workspace.createError'));
    } finally {
      saving = false;
    }
  }
</script>

<div class="relative px-3 pb-2">
  <button
    type="button"
    class="w-full flex items-center gap-2.5 rounded-[11px] px-3 py-2.5 text-left transition-colors hover:bg-white/[.05]"
    style="background: var(--quip-bg-elevated); border: 1px solid var(--quip-border-strong)"
    aria-expanded={open}
    onclick={() => (open = !open)}
  >
    <span class="w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-semibold" style="background: var(--quip-hover); color: var(--quip-text-dim)">
      {($selectedWorkspace?.name ?? 'W').slice(0, 1).toUpperCase()}
    </span>
    <span class="min-w-0 flex-1">
      <span class="block text-[10px] uppercase tracking-[0.14em]" style="color: var(--quip-text-muted)">{$t('workspace.label')}</span>
      <span class="block truncate text-[13px] font-medium" style="color: var(--quip-text)">{$selectedWorkspace?.name ?? $t('common.loading')}</span>
    </span>
    <svg class="w-3.5 h-3.5 transition-transform {open ? 'rotate-180' : ''}" style="color: var(--quip-text-muted)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
  </button>

  {#if open}
    <div
      class="absolute left-3 right-3 top-full mt-1 z-40 rounded-xl p-1.5 shadow-2xl"
      style="background: var(--quip-bg-raised); border: 1px solid var(--quip-border-strong)"
    >
      {#each $workspaces as workspace (workspace.id)}
        <button
          type="button"
          class="w-full flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-white/[.06] {workspace.id === $selectedWorkspace?.id ? 'bg-white/[.06]' : ''}"
          onclick={() => choose(workspace.id)}
        >
          <span class="truncate flex-1">{workspace.name}</span>
          {#if workspace.is_personal}<span class="text-[9px] uppercase opacity-40">{$t('workspace.personal')}</span>{/if}
          {#if workspace.id === $selectedWorkspace?.id}<span class="text-emerald-400 text-xs">●</span>{/if}
        </button>
      {/each}

      <div class="mt-1 pt-1 border-t" style="border-color: var(--quip-border)">
        {#if creating}
          <form class="flex gap-1 p-1" onsubmit={(event) => { event.preventDefault(); create(); }}>
            <input
              class="min-w-0 flex-1 rounded-lg px-2 py-1.5 text-xs bg-transparent"
              style="border: 1px solid var(--quip-border-strong)"
              bind:value={name}
              placeholder={$t('workspace.namePlaceholder')}
              maxlength="255"
            />
            <button class="px-2 text-xs rounded-lg hover:bg-white/[.06]" disabled={saving}>{saving ? '…' : '↵'}</button>
          </form>
        {:else}
          <button
            type="button"
            class="w-full px-2.5 py-2 rounded-lg text-left text-xs hover:bg-white/[.06]"
            style="color: var(--quip-text-dim)"
            onclick={() => (creating = true)}
          >+ {$t('workspace.new')}</button>
        {/if}
      </div>
    </div>
  {/if}
</div>
