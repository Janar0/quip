<script lang="ts">
  import { getFileUrl } from '$lib/api/files';
  import { scale } from 'svelte/transition';
  import { D1 } from '$lib/motion';

  type Attachment = {
    file_id: string;
    filename: string;
    file_type: string;
    content_type?: string;
  };

  let { attachments, mb = 'mb-2' }: { attachments: readonly Attachment[]; mb?: string } = $props();

  let images = $derived(
    attachments.filter((a) => a.file_type === 'image').map((a) => ({ ...a, url: getFileUrl(a.file_id) })),
  );
  let files = $derived(attachments.filter((a) => a.file_type !== 'image'));
</script>

{#if images.length}
  <div class="flex flex-wrap gap-2 {mb}">
    {#each images as img, i (img.file_id)}
      <div class="relative" in:scale={{ start: 0.9, duration: D1, delay: Math.min(i * 30, 150) }}>
        <a href={img.url} target="_blank" rel="noopener" class="block">
          <img
            src={img.url}
            alt={img.filename}
            loading="lazy"
            class="max-w-[300px] max-h-[300px] rounded-lg object-contain cursor-pointer hover:opacity-80 transition-opacity"
            onerror={(e) => {
              const el = e.currentTarget as HTMLImageElement;
              el.style.display = 'none';
              el.nextElementSibling?.classList.remove('hidden');
            }}
          />
          <div class="hidden items-center gap-2 px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700/30 text-sm">
            <svg class="w-4 h-4 opacity-50 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </svg>
            <span class="truncate max-w-48">{img.filename}</span>
          </div>
        </a>
      </div>
    {/each}
  </div>
{/if}
{#if files.length}
  <div class="flex flex-wrap gap-2 {mb}">
    {#each files as att, i (att.file_id)}
      {#if att.file_type === 'video'}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video src={getFileUrl(att.file_id)} controls preload="metadata" class="max-w-[300px] max-h-[300px] rounded-lg" aria-label={att.filename}></video>
      {:else if att.file_type === 'audio'}
        <audio src={getFileUrl(att.file_id)} controls preload="metadata" aria-label={att.filename}></audio>
      {:else}
        <a href={getFileUrl(att.file_id)} target="_blank" rel="noopener" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700/30 text-sm hover:bg-slate-800/60" in:scale={{ start: 0.9, duration: D1, delay: Math.min(i, 4) * 30 }}>
          <svg class="w-4 h-4 opacity-50 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <span class="truncate max-w-48">{att.filename}</span>
        </a>
      {/if}
    {/each}
  </div>
{/if}
