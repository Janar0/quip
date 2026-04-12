<script lang="ts">
  let { filename, chatId }: { filename: string; chatId: string } = $props();

  let ext = $derived(filename.split('.').pop()?.toUpperCase() ?? '');
  let label = $derived.by(() => {
    const map: Record<string, string> = {
      PNG: 'Image', JPG: 'Image', JPEG: 'Image', GIF: 'Image', SVG: 'Image', WEBP: 'Image',
      PDF: 'Document', DOCX: 'Document', DOC: 'Document', ODT: 'Document',
      PPTX: 'Presentation', PPT: 'Presentation', ODP: 'Presentation',
      XLSX: 'Spreadsheet', XLS: 'Spreadsheet', CSV: 'Data',
      MP3: 'Audio', WAV: 'Audio', OGG: 'Audio',
      MP4: 'Video', WEBM: 'Video', AVI: 'Video',
      ZIP: 'Archive', TAR: 'Archive', GZ: 'Archive',
      PY: 'Script', JS: 'Script', TS: 'Script', SH: 'Script',
      JSON: 'Data', XML: 'Data', YAML: 'Data', YML: 'Data',
      TXT: 'Text', MD: 'Text', HTML: 'Web page',
    };
    return map[ext] ?? 'File';
  });

  let iconColor = $derived.by(() => {
    const colors: Record<string, string> = {
      Image: 'text-emerald-400 bg-emerald-500/15',
      Document: 'text-blue-400 bg-blue-500/15',
      Presentation: 'text-orange-400 bg-orange-500/15',
      Spreadsheet: 'text-green-400 bg-green-500/15',
      Data: 'text-yellow-400 bg-yellow-500/15',
      Audio: 'text-purple-400 bg-purple-500/15',
      Video: 'text-pink-400 bg-pink-500/15',
      Archive: 'text-slate-400 bg-slate-500/15',
      Script: 'text-cyan-400 bg-cyan-500/15',
      Text: 'text-slate-400 bg-slate-500/15',
      'Web page': 'text-indigo-400 bg-indigo-500/15',
    };
    return colors[label] ?? 'text-slate-400 bg-slate-500/15';
  });

  function getDownloadUrl(): string {
    const token = localStorage.getItem('access_token');
    return `/api/sandbox/${chatId}/file/${encodeURIComponent(filename)}?token=${encodeURIComponent(token ?? '')}`;
  }
</script>

<a
  href={getDownloadUrl()}
  target="_blank"
  class="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/30 hover:bg-slate-800/50 transition-colors p-3 my-1.5 max-w-sm"
>
  <!-- File icon -->
  <div class="flex-shrink-0 w-10 h-10 rounded-lg {iconColor} flex items-center justify-center">
    {#if label === 'Image'}
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0 0 22.5 18.75V5.25A2.25 2.25 0 0 0 20.25 3H3.75A2.25 2.25 0 0 0 1.5 5.25v13.5A2.25 2.25 0 0 0 3.75 21Z"/>
      </svg>
    {:else if label === 'Presentation'}
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5"/>
      </svg>
    {:else}
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"/>
      </svg>
    {/if}
  </div>

  <!-- File info -->
  <div class="flex-1 min-w-0">
    <div class="text-sm font-medium truncate">{filename}</div>
    <div class="text-xs opacity-40">{label}{ext ? ` \u00b7 ${ext}` : ''}</div>
  </div>

  <!-- Download icon -->
  <div class="flex-shrink-0 opacity-40 hover:opacity-80 transition-opacity">
    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"/>
    </svg>
  </div>
</a>
