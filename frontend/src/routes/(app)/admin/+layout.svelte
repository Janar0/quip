<script lang="ts">
  import { page } from '$app/state';
  import { t } from 'svelte-i18n';

  let { children } = $props();

  const tabs = [
    { href: '/admin/settings', key: 'admin.tabs.settings', icon: 'M12.22 2h-.44a2 2 0 00-2 2v.18a2 2 0 01-1 1.73l-.43.25a2 2 0 01-2 0l-.15-.08a2 2 0 00-2.73.73l-.22.38a2 2 0 00.73 2.73l.15.1a2 2 0 011 1.72v.51a2 2 0 01-1 1.74l-.15.09a2 2 0 00-.73 2.73l.22.38a2 2 0 002.73.73l.15-.08a2 2 0 012 0l.43.25a2 2 0 011 1.73V20a2 2 0 002 2h.44a2 2 0 002-2v-.18a2 2 0 011-1.73l.43-.25a2 2 0 012 0l.15.08a2 2 0 002.73-.73l.22-.39a2 2 0 00-.73-2.73l-.15-.08a2 2 0 01-1-1.74v-.5a2 2 0 011-1.74l.15-.09a2 2 0 00.73-2.73l-.22-.38a2 2 0 00-2.73-.73l-.15.08a2 2 0 01-2 0l-.43-.25a2 2 0 01-1-1.73V4a2 2 0 00-2-2zM12 15a3 3 0 100-6 3 3 0 000 6z' },
    { href: '/admin/models', key: 'admin.tabs.models', icon: 'M4 6h16M4 10h16M4 14h16M4 18h16' },
    { href: '/admin/users', key: 'admin.tabs.users', icon: 'M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4-4v2m22 4v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75M13 7a4 4 0 11-8 0 4 4 0 018 0z' },
    { href: '/admin/usage', key: 'admin.tabs.usage', icon: 'M18 20V10M12 20V4M6 20v-6' },
    { href: '/admin/budgets', key: 'admin.tabs.budgets', icon: 'M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6' },
    { href: '/admin/skills', key: 'admin.tabs.skills', icon: 'M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z' },
    { href: '/admin/migrate', key: 'admin.tabs.import', icon: 'M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12' },
  ];

  let isActive = $derived((href: string) => page.url.pathname.startsWith(href));
</script>

<div class="flex h-full">
  <!-- Admin sidebar nav -->
  <nav class="w-48 border-r border-slate-800/50 flex flex-col p-3 gap-1 shrink-0">
    <h2 class="text-xs font-bold uppercase tracking-wider opacity-40 px-3 py-2">{$t('nav.admin')}</h2>
    {#each tabs as tab}
      <a
        href={tab.href}
        class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors
          {isActive(tab.href) ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-900'}"
      >
        <svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d={tab.icon}/></svg>
        {$t(tab.key)}
      </a>
    {/each}
  </nav>

  <!-- Content -->
  <div class="flex-1 overflow-y-auto">
    {@render children()}
  </div>
</div>
