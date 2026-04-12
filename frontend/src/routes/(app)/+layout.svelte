<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { isAuthenticated, currentUser } from '$lib/stores/auth';
  import { chatList } from '$lib/stores/chat';
  import { showSidebar, toggleSidebar } from '$lib/stores/ui';
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import { logout } from '$lib/api/auth';
  import { loadChats, loadMoreChats, canLoadMoreChats, deleteChat, renameChat, togglePin, searchChats, fetchFeatures, type SearchResult } from '$lib/api/chats';
  import { fetchModels } from '$lib/stores/models';
  import { getTimeGroup } from '$lib/utils/time';
  import type { ChatInfo } from '$lib/stores/chat';
  import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
  import ShortcutsModal from '$lib/components/common/ShortcutsModal.svelte';
  import ThemeSwitcher from '$lib/components/common/ThemeSwitcher.svelte';
  import { fade, fly } from 'svelte/transition';
  import { flip } from 'svelte/animate';
  import { D1, D2, D3, easeOut } from '$lib/motion';

  let { children } = $props();
  let isAdmin = $derived($currentUser?.role === 'admin');

  // Search
  let searchQuery = $state('');
  let searchResults = $state<SearchResult[]>([]);
  let isSearching = $state(false);
  let searchTimeout: ReturnType<typeof setTimeout>;
  let loadingMore = $state(false);

  function sentinel(node: HTMLElement) {
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && canLoadMoreChats() && !loadingMore) {
        loadingMore = true;
        loadMoreChats().finally(() => { loadingMore = false; });
      }
    }, { threshold: 0.1 });
    obs.observe(node);
    return { destroy: () => obs.disconnect() };
  }

  // Rename
  let renamingChatId = $state<string | null>(null);
  let renameValue = $state('');

  // Delete confirm
  let deletingChatId = $state<string | null>(null);

  // Shortcuts modal
  let showShortcuts = $state(false);

  // Mobile detection
  let isMobile = $state(typeof window !== 'undefined' && window.innerWidth < 768);

  // Time-grouped chats (pinned separated)
  const groupOrder = ['today', 'yesterday', 'week', 'month', 'older'] as const;
  let pinnedChats = $derived($chatList.filter((c) => c.pinned));
  let groupedChats = $derived.by(() => {
    const unpinned = $chatList.filter((c) => !c.pinned);
    const groups: Record<string, typeof unpinned> = {};
    for (const chat of unpinned) {
      const group = getTimeGroup(chat.updated_at);
      (groups[group] ??= []).push(chat);
    }
    return groupOrder.filter((g) => groups[g]?.length).map((g) => ({ group: g, chats: groups[g] }));
  });

  function handleSearch() {
    clearTimeout(searchTimeout);
    if (!searchQuery.trim()) {
      searchResults = [];
      isSearching = false;
      return;
    }
    isSearching = true;
    searchTimeout = setTimeout(async () => {
      try {
        searchResults = await searchChats(searchQuery);
      } catch {
        searchResults = [];
      } finally {
        isSearching = false;
      }
    }, 300);
  }

  function clearSearch() {
    searchQuery = '';
    searchResults = [];
    isSearching = false;
  }

  // Rename handlers
  function startRename(chatId: string, currentTitle: string) {
    renamingChatId = chatId;
    renameValue = currentTitle;
  }

  async function submitRename() {
    if (renamingChatId && renameValue.trim()) {
      await renameChat(renamingChatId, renameValue.trim());
      toast.success($t('toast.chatRenamed'));
    }
    renamingChatId = null;
  }

  function cancelRename() {
    renamingChatId = null;
  }

  function renameKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') { e.preventDefault(); submitRename(); }
    if (e.key === 'Escape') { e.preventDefault(); cancelRename(); }
  }

  // Pin handler
  async function togglePinChat(chat: ChatInfo) {
    await togglePin(chat.id, !chat.pinned);
    toast.success($t(chat.pinned ? 'toast.chatUnpinned' : 'toast.chatPinned'));
  }

  // Delete handlers
  async function confirmDelete() {
    if (deletingChatId) {
      await deleteChat(deletingChatId);
      toast.success($t('toast.chatDeleted'));
    }
    deletingChatId = null;
  }

  $effect(() => {
    if (!$isAuthenticated) {
      goto('/auth/login');
    }
  });

  // Auto-close sidebar on mobile navigation
  $effect(() => {
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    page.url.pathname;
    if (isMobile) showSidebar.set(false);
  });

  onMount(() => {
    Promise.all([loadChats(), fetchModels(), fetchFeatures()]);

    const mql = window.matchMedia('(min-width: 768px)');
    const handler = (e: MediaQueryListEvent) => {
      isMobile = !e.matches;
      if (e.matches) showSidebar.set(true);
    };
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  });

  function handleLogout() {
    logout();
    goto('/auth/login');
  }

  // Global keyboard shortcuts
  function handleKeydown(e: KeyboardEvent) {
    const target = e.target as HTMLElement;
    const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;

    if (e.key === '/' && !isInput) {
      e.preventDefault();
      document.getElementById('chat-input')?.focus();
    }
    if (e.key === 'N' && e.ctrlKey && e.shiftKey) {
      e.preventDefault();
      goto('/chat');
    }
    if (e.key === 'Escape' && isMobile && $showSidebar) {
      showSidebar.set(false);
    }
    if (e.key === '?' && !isInput) {
      e.preventDefault();
      showShortcuts = !showShortcuts;
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<ConfirmDialog
  open={!!deletingChatId}
  title={$t('sidebar.confirmDelete')}
  message={$t('sidebar.confirmDeleteMsg')}
  onConfirm={confirmDelete}
  onCancel={() => (deletingChatId = null)}
/>

<ShortcutsModal open={showShortcuts} onClose={() => (showShortcuts = false)} />

{#if $isAuthenticated}
  <div class="flex h-screen" style="background: var(--quip-bg)">
    <!-- Mobile backdrop -->
    {#if isMobile && $showSidebar}
      <button
        class="fixed inset-0 bg-black/50 z-20 backdrop-blur-sm"
        transition:fade={{ duration: D2 }}
        onclick={() => showSidebar.set(false)}
        aria-label="Close sidebar"
      ></button>
    {/if}

    <!-- Sidebar -->
    {#if $showSidebar}
      <aside
        class="{isMobile ? 'fixed inset-y-0 left-0 z-30' : ''} w-64 border-r flex flex-col overflow-hidden shrink-0"
        style="background: var(--quip-sidebar-bg, var(--quip-bg)); border-color: var(--quip-border)"
        transition:fly={{ x: -260, duration: D3, easing: easeOut }}
      >
        <!-- Header: Logo + Collapse -->
        <div class="h-14 flex items-center justify-between px-5 border-b shrink-0" style="border-color: var(--quip-border)">
          <span class="text-lg font-bold tracking-tighter font-headline" style="color: var(--quip-text)">QUIP</span>
          <button
            class="p-1.5 text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 rounded-lg transition-colors"
            onclick={toggleSidebar}
            aria-label="Collapse sidebar"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 19l-7-7 7-7M18 19l-7-7 7-7"/></svg>
          </button>
        </div>

        <!-- New Chat Button -->
        <div class="px-3 pt-4 pb-2 shrink-0">
          <a
            href="/chat"
            class="flex items-center justify-between w-full px-3 py-2.5 rounded-lg transition-all active:scale-[0.98] group text-sm font-medium"
            style="background: var(--quip-bg-raised); border: 1px solid var(--quip-border-strong); color: var(--quip-text)"
            onclick={clearSearch}
          >
            <span class="flex items-center gap-2.5">
              <svg class="w-4 h-4 text-slate-400 group-hover:text-slate-200" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
              {$t('nav.newChat')}
            </span>
            <span class="text-[10px] text-slate-600 font-mono">Ctrl+N</span>
          </a>
        </div>

        <!-- Search -->
        <div class="px-3 pb-2 shrink-0">
          <div class="relative">
            <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
            <input
              type="text"
              class="w-full rounded-lg pl-9 pr-8 py-2 text-sm focus:outline-none transition-colors"
              style="background: var(--quip-bg-elevated); border: 1px solid var(--quip-border-strong); color: var(--quip-text)"
              placeholder={$t('search.searchChats')}
              bind:value={searchQuery}
              oninput={handleSearch}
            />
            {#if searchQuery}
              <button
                class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                onclick={clearSearch}
                aria-label={$t('search.clear')}
              >
                <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            {/if}
          </div>
        </div>

        <!-- Chat list -->
        <nav class="flex-1 overflow-y-auto px-3 pb-2">
          {#if searchQuery}
            {#if isSearching}
              <p class="text-xs text-slate-500 text-center py-4">{$t('search.searching')}</p>
            {:else if searchResults.length === 0}
              <p class="text-xs text-slate-500 text-center py-4">{$t('search.noResults')}</p>
            {:else}
              {#each searchResults as result (result.id)}
                <a
                  href="/chat/{result.id}"
                  class="block px-3 py-2 rounded-lg text-sm text-slate-400 hover:bg-slate-900 hover:text-slate-200 transition-colors"
                  onclick={clearSearch}
                >
                  <div class="truncate">{result.title}</div>
                  {#if result.snippet}
                    <div class="text-xs text-slate-600 truncate mt-0.5">{result.snippet}</div>
                  {/if}
                </a>
              {/each}
            {/if}
          {:else}
            {#snippet chatItem(chat: ChatInfo)}
              {#if renamingChatId === chat.id}
                <div class="px-1" in:fade={{ duration: D1 }}>
                  <!-- svelte-ignore a11y_autofocus -->
                  <input
                    class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-slate-600"
                    bind:value={renameValue}
                    onkeydown={renameKeydown}
                    onblur={submitRename}
                    autofocus
                  />
                </div>
              {:else}
                <a
                  href="/chat/{chat.id}"
                  class="group relative flex items-center px-3 py-2 rounded-lg text-sm text-slate-400 hover:bg-slate-900 hover:text-slate-200 transition-colors"
                  in:fade={{ duration: D1 }}
                  ondblclick={(e) => { e.preventDefault(); startRename(chat.id, chat.title); }}
                >
                  <span class="truncate w-full group-hover:pr-[72px] transition-all" style="transition-duration: var(--quip-d-1)">{chat.title}</span>
                  <span class="absolute right-0 inset-y-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity px-1 rounded-r-lg" style="background: linear-gradient(to right, transparent, var(--quip-sidebar-bg, #0f172a) 20%)">
                    <button
                      class="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300"
                      onclick={(e: MouseEvent) => { e.stopPropagation(); e.preventDefault(); togglePinChat(chat); }}
                      title={$t(chat.pinned ? 'sidebar.unpin' : 'sidebar.pin')}
                    >
                      <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill={chat.pinned ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="2"><path d="M12 17v5M9 10.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V16a1 1 0 001 1h12a1 1 0 001-1v-.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V7a1 1 0 011-1 1 1 0 001-1V4a1 1 0 00-1-1H8a1 1 0 00-1 1v1a1 1 0 001 1 1 1 0 011 1v3.76z"/></svg>
                    </button>
                    <button
                      class="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300"
                      onclick={(e: MouseEvent) => { e.stopPropagation(); e.preventDefault(); startRename(chat.id, chat.title); }}
                      title={$t('sidebar.rename')}
                    >
                      <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button
                      class="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-red-400"
                      onclick={(e: MouseEvent) => { e.stopPropagation(); e.preventDefault(); deletingChatId = chat.id; }}
                      title={$t('confirm.delete')}
                    >
                      <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                    </button>
                  </span>
                </a>
              {/if}
            {/snippet}

            {#if pinnedChats.length > 0}
              <div class="px-2 pt-3 pb-1.5">
                <span class="text-[10px] font-bold text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
                  <svg class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M12 17v5M9 10.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V16a1 1 0 001 1h12a1 1 0 001-1v-.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V7a1 1 0 011-1 1 1 0 001-1V4a1 1 0 00-1-1H8a1 1 0 00-1 1v1a1 1 0 001 1 1 1 0 011 1v3.76z"/></svg>
                  {$t('sidebar.pinned')}
                </span>
              </div>
              {#each pinnedChats as chat (chat.id)}
                <div animate:flip={{ duration: D2 }}>
                  {@render chatItem(chat)}
                </div>
              {/each}
            {/if}

            {#each groupedChats as { group, chats } (group)}
              <div class="px-2 pt-4 pb-1.5">
                <span class="text-[10px] font-bold text-slate-500 uppercase tracking-widest">{$t('sidebar.' + group)}</span>
              </div>
              {#each chats as chat (chat.id)}
                <div animate:flip={{ duration: D2 }}>
                  {@render chatItem(chat)}
                </div>
              {/each}
            {/each}
            {#if !pinnedChats.length && !groupedChats.length}
              <p class="text-xs text-slate-600 text-center py-8">{$t('sidebar.noChats')}</p>
            {:else if canLoadMoreChats()}
              <div use:sentinel class="h-6 flex items-center justify-center">
                {#if loadingMore}<span class="text-xs opacity-30">···</span>{/if}
              </div>
            {/if}
          {/if}
        </nav>

        <!-- Bottom bar -->
        <div class="flex flex-col gap-1.5 p-3 border-t shrink-0" style="border-color: var(--quip-border)">
          <a href="/settings" class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-slate-500 hover:text-slate-300 hover:bg-slate-900 transition-colors">
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
            {$t('nav.settings')}
          </a>
          {#if isAdmin}
            <a href="/admin/settings" class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-slate-500 hover:text-slate-300 hover:bg-slate-900 transition-colors">
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/></svg>
              {$t('nav.admin')}
            </a>
          {/if}
          <div class="flex items-center justify-between px-3 py-2">
            <div class="flex items-center gap-2.5">
              <div class="w-7 h-7 rounded-full flex items-center justify-center" style="background: var(--quip-hover); border: 1px solid var(--quip-border-strong)">
                <svg class="w-3.5 h-3.5" style="color: var(--quip-text-dim)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              </div>
              <span class="text-sm truncate max-w-28" style="color: var(--quip-text-dim)">{$currentUser?.name ?? ''}</span>
            </div>
            <button
              class="text-xs transition-colors" style="color: var(--quip-text-muted)"
              onclick={handleLogout}
            >{$t('auth.logout')}</button>
          </div>
          <div class="flex justify-center pt-1">
            <ThemeSwitcher />
          </div>
        </div>
      </aside>
    {/if}

    <!-- Main content -->
    <main class="flex-1 overflow-hidden flex flex-col relative">
      <!-- Hamburger button when sidebar is hidden -->
      {#if !$showSidebar}
        <button
          class="fixed top-3 left-3 z-10 p-2 rounded-lg transition-colors backdrop-blur-sm"
          style="background: var(--quip-input-bg); border: 1px solid var(--quip-border); color: var(--quip-text-dim)"
          onclick={toggleSidebar}
          aria-label="Open sidebar"
        >
          <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
        </button>
      {/if}
      {@render children()}
    </main>
  </div>
{/if}
