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
  let rootEl: HTMLDivElement;
  let triggerEl = $state<HTMLButtonElement | undefined>(undefined);
  let menuEl = $state<HTMLDivElement | undefined>(undefined);
  let menuStyle = $state('');

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => { if (node.parentNode) node.parentNode.removeChild(node); } };
  }

  function placeMenu() {
    if (!triggerEl) return;
    const rect = triggerEl.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const width = Math.max(0, Math.min(Math.max(rect.width, 280), viewportWidth - 16));
    const left = Math.max(8, Math.min(viewportWidth - width - 8, rect.left + rect.width / 2 - width / 2));
    const gap = 8;
    const spaceAbove = Math.max(0, rect.top - gap - 8);
    const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - gap - 8);
    const opensAbove = spaceAbove > spaceBelow;
    const available = opensAbove ? spaceAbove : spaceBelow;
    const maxHeight = Math.min(360, available);
    const top = opensAbove ? rect.top - gap - maxHeight : rect.bottom + gap;
    menuStyle = `top: ${Math.round(top)}px; left: ${Math.round(left)}px; width: ${Math.round(width)}px; max-height: ${Math.round(maxHeight)}px;`;
  }

  function toggleMenu() {
    open = !open;
  }

  $effect(() => {
    if (!open) return;
    placeMenu();
    function onDocumentMouseDown(event: MouseEvent) {
      const target = event.target as Node;
      if (rootEl && !rootEl.contains(target) && !menuEl?.contains(target)) open = false;
    }
    function onKeydown(event: KeyboardEvent) {
      if (event.key === 'Escape') open = false;
    }
    document.addEventListener('mousedown', onDocumentMouseDown);
    document.addEventListener('keydown', onKeydown);
    window.addEventListener('resize', placeMenu);
    window.addEventListener('scroll', placeMenu, true);
    return () => {
      document.removeEventListener('mousedown', onDocumentMouseDown);
      document.removeEventListener('keydown', onKeydown);
      window.removeEventListener('resize', placeMenu);
      window.removeEventListener('scroll', placeMenu, true);
    };
  });

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

<div class="relative px-3 pb-2" bind:this={rootEl}>
  <button
    type="button"
    class="quip-theme-hover w-full flex items-center gap-2.5 rounded-[11px] px-3 py-2.5 text-left transition-colors"
    style="background: var(--quip-bg-elevated); border: 1px solid var(--quip-border-strong)"
    bind:this={triggerEl}
    aria-haspopup="dialog"
    aria-expanded={open}
    onclick={toggleMenu}
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
      class="quip-workspace-menu"
      bind:this={menuEl}
      style={menuStyle}
      role="dialog"
      aria-label={$t('workspace.label')}
      use:portal
    >
      {#each $workspaces as workspace (workspace.id)}
        <button
          type="button"
          class="quip-theme-hover w-full flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm {workspace.id === $selectedWorkspace?.id ? 'quip-theme-selected' : ''}"
          onclick={() => choose(workspace.id)}
        >
          <span class="truncate flex-1">{workspace.name}</span>
          {#if workspace.is_personal}<span class="text-[9px] uppercase" style="color: var(--quip-text-muted)">{$t('workspace.personal')}</span>{/if}
          {#if workspace.id === $selectedWorkspace?.id}<span class="text-xs" style="color: var(--quip-success)">●</span>{/if}
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
              aria-label={$t('workspace.name')}
              maxlength="255"
            />
            <button class="quip-theme-hover px-2 text-xs rounded-lg" disabled={saving}>{saving ? '…' : '↵'}</button>
          </form>
        {:else}
          <button
            type="button"
            class="quip-theme-hover w-full px-2.5 py-2 rounded-lg text-left text-xs"
            style="color: var(--quip-text-dim)"
            onclick={() => (creating = true)}
          >+ {$t('workspace.new')}</button>
        {/if}
      </div>
    </div>
  {/if}
</div>
