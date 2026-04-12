<script lang="ts">
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';

  let file = $state<File | null>(null);
  let uploading = $state(false);
  let dragging = $state(false);
  let result = $state<{ imported_chats: number; imported_messages: number; skipped: number } | null>(null);

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragging = false;
    const f = e.dataTransfer?.files[0];
    if (f?.name.endsWith('.json')) file = f;
  }

  function handleFileSelect(e: Event) {
    file = (e.currentTarget as HTMLInputElement).files?.[0] ?? null;
  }

  async function handleImport() {
    if (!file) return;
    uploading = true;
    result = null;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/migrate/openwebui', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: formData,
      });

      if (res.ok) {
        result = await res.json();
        toast.success($t('toast.importSuccess'));
      } else {
        const err = await res.json().catch(() => ({ detail: 'Import failed' }));
        toast.error(err.detail ?? $t('toast.importError'));
      }
    } catch {
      toast.error($t('toast.importError'));
    } finally {
      uploading = false;
    }
  }
</script>

<div class="p-8 max-w-2xl mx-auto space-y-8">
  <h1 class="text-2xl font-bold">{$t('nav.admin')} — {$t('migrate.title')}</h1>

  <section class="card p-6 space-y-4">
    <div class="flex items-center gap-2">
      <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
      <h2 class="text-lg font-semibold">{$t('migrate.title')}</h2>
    </div>
    <p class="text-sm opacity-50">{$t('migrate.description')}</p>

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="border-2 border-dashed rounded-xl p-8 text-center transition-colors
        {dragging ? 'border-slate-500/50 bg-slate-500/5' : 'border-slate-800'}"
      ondragover={(e) => { e.preventDefault(); dragging = true; }}
      ondragleave={() => (dragging = false)}
      ondrop={handleDrop}
    >
      <svg class="w-10 h-10 mx-auto opacity-30 mb-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
      </svg>
      <p class="opacity-50">{$t('migrate.dropzone')}</p>
      <label class="text-slate-400 text-sm cursor-pointer underline">
        {$t('migrate.browse')}
        <input type="file" accept=".json" class="hidden" onchange={handleFileSelect} />
      </label>
      {#if file}
        <p class="text-sm mt-2 opacity-70">{file.name}</p>
      {/if}
    </div>

    <button
      class="btn preset-filled-primary-500 w-full"
      onclick={handleImport}
      disabled={!file || uploading}
    >
      {uploading ? $t('migrate.importing') : $t('migrate.import')}
    </button>

    {#if result}
      <div class="card p-5 space-y-2">
        <h3 class="font-semibold text-success-400">{$t('migrate.importComplete')}</h3>
        <div class="grid grid-cols-3 gap-4 text-center text-sm">
          <div>
            <div class="text-xl font-bold">{result.imported_chats}</div>
            <div class="opacity-50">{$t('migrate.chatsImported')}</div>
          </div>
          <div>
            <div class="text-xl font-bold">{result.imported_messages}</div>
            <div class="opacity-50">{$t('migrate.messagesImported')}</div>
          </div>
          <div>
            <div class="text-xl font-bold opacity-50">{result.skipped}</div>
            <div class="opacity-50">{$t('migrate.skipped')}</div>
          </div>
        </div>
      </div>
    {/if}
  </section>
</div>
