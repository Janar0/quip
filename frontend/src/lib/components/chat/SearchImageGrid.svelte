<script lang="ts">
  import { t } from 'svelte-i18n';
  import { fade, scale } from 'svelte/transition';
  import { D1, D2, easeOut } from '$lib/motion';
  import type { SearchImageInfo } from '$lib/stores/chat';

  let { images }: { images: SearchImageInfo[] } = $props();

  let lightboxIndex = $state<number | null>(null);
  let hiddenSrcs = $state<Set<string>>(new Set());

  let visibleImages = $derived(images.filter((i) => !hiddenSrcs.has(i.img_src)));
  let thumbs = $derived(visibleImages.slice(0, 4));
  let overflow = $derived(Math.max(visibleImages.length - 4, 0));

  function openLightbox(idx: number) {
    lightboxIndex = idx;
  }

  function closeLightbox() {
    lightboxIndex = null;
  }

  function prevImage() {
    if (lightboxIndex === null) return;
    lightboxIndex = (lightboxIndex - 1 + visibleImages.length) % visibleImages.length;
  }

  function nextImage() {
    if (lightboxIndex === null) return;
    lightboxIndex = (lightboxIndex + 1) % visibleImages.length;
  }

  function handleKey(e: KeyboardEvent) {
    if (lightboxIndex === null) return;
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') prevImage();
    if (e.key === 'ArrowRight') nextImage();
  }

  function markBroken(src: string) {
    hiddenSrcs = new Set([...hiddenSrcs, src]);
    if (lightboxIndex !== null && visibleImages.length <= 1) {
      closeLightbox();
    }
  }
</script>

<svelte:window onkeydown={handleKey} />

{#if visibleImages.length >= 2}
  <div class="mb-3 flex gap-1.5 max-w-md">
    {#each thumbs as img, i (img.img_src)}
      <button
        type="button"
        class="group relative flex-1 aspect-square rounded-lg overflow-hidden border transition-colors hover:border-slate-500"
        style="border-color: var(--quip-border); background: var(--quip-bg-raised)"
        onclick={() => openLightbox(i)}
        aria-label={$t('search.openImage')}
      >
        <img
          src={img.img_src}
          alt={img.title || ''}
          loading="lazy"
          referrerpolicy="no-referrer"
          class="w-full h-full object-cover transition-transform group-hover:scale-105"
          onerror={() => markBroken(img.img_src)}
        />
        {#if i === 3 && overflow > 0}
          <div class="absolute inset-0 bg-black/60 flex items-center justify-center text-slate-100 text-sm font-medium">
            +{overflow}
          </div>
        {/if}
      </button>
    {/each}
  </div>
{/if}

{#if lightboxIndex !== null && visibleImages[lightboxIndex]}
  {@const current = visibleImages[lightboxIndex]}
  <div
    class="fixed inset-0 z-[100] bg-black/90 backdrop-blur-sm flex items-center justify-center p-4"
    role="dialog"
    aria-modal="true"
    transition:fade={{ duration: D1 }}
  >
    <!-- Close catcher (backdrop) -->
    <button
      type="button"
      class="absolute inset-0 w-full h-full cursor-default"
      onclick={closeLightbox}
      aria-label="Close"
    ></button>

    <!-- Close button -->
    <button
      type="button"
      class="absolute top-4 right-4 z-10 p-2 rounded-lg bg-slate-900/80 hover:bg-slate-800 text-slate-200 border border-slate-700"
      onclick={closeLightbox}
      aria-label="Close"
    >
      <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="18" y1="6" x2="6" y2="18"/>
        <line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button>

    <!-- Prev button -->
    {#if visibleImages.length > 1}
      <button
        type="button"
        class="absolute left-4 top-1/2 -translate-y-1/2 z-10 p-3 rounded-full bg-slate-900/80 hover:bg-slate-800 text-slate-200 border border-slate-700"
        onclick={prevImage}
        aria-label="Previous"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="15 18 9 12 15 6"/>
        </svg>
      </button>
      <button
        type="button"
        class="absolute right-4 top-1/2 -translate-y-1/2 z-10 p-3 rounded-full bg-slate-900/80 hover:bg-slate-800 text-slate-200 border border-slate-700"
        onclick={nextImage}
        aria-label="Next"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </button>
    {/if}

    <!-- Image + caption -->
    <div
      class="relative z-[1] max-w-[90vw] max-h-[85vh] flex flex-col items-center gap-3"
      in:scale={{ start: 0.94, duration: D2, easing: easeOut }}
    >
      <img
        src={current.img_src}
        alt={current.title || ''}
        referrerpolicy="no-referrer"
        class="max-w-full max-h-[75vh] object-contain rounded-lg shadow-2xl"
        onerror={() => markBroken(current.img_src)}
      />
      <div class="flex flex-col items-center gap-1 text-center max-w-lg">
        {#if current.title}
          <p class="text-sm text-slate-200 line-clamp-2">{current.title}</p>
        {/if}
        <a
          href={current.source_url}
          target="_blank"
          rel="noopener"
          class="text-xs text-slate-400 hover:text-slate-200 underline underline-offset-2"
        >
          {$t('search.viewSource')}
        </a>
      </div>
    </div>
  </div>
{/if}
