<script lang="ts">
  let { src, label = '' }: { src: string; label?: string } = $props();

  let audio = $state<HTMLAudioElement | null>(null);
  let paused = $state(true);
  let currentTime = $state(0);
  let duration = $state(0);
  let volume = $state(1);
  let muted = $state(false);

  function fmt(t: number): string {
    if (!isFinite(t) || t < 0) return '0:00';
    return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  }

  function togglePlay() {
    if (!audio) return;
    paused ? audio.play() : audio.pause();
  }

  function seek(e: Event) {
    if (!audio) return;
    audio.currentTime = +(e.currentTarget as HTMLInputElement).value;
    currentTime = audio.currentTime;
  }

  function setVolume(e: Event) {
    volume = +(e.currentTarget as HTMLInputElement).value;
    if (audio) audio.volume = volume;
    muted = volume === 0;
  }

  function toggleMute() {
    if (!audio) return;
    muted = !muted;
    audio.muted = muted;
  }

  let pct = $derived(duration > 0 ? (currentTime / duration) * 100 : 0);
  let trackBg = $derived(
    `linear-gradient(to right, var(--quip-text-dim) ${pct}%, var(--quip-border-strong) ${pct}%)`
  );
  let volPct = $derived(muted ? 0 : volume * 100);
  let volBg = $derived(
    `linear-gradient(to right, var(--quip-text-dim) ${volPct}%, var(--quip-border-strong) ${volPct}%)`
  );
</script>

<div class="player">
  <div class="header">
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" class="note-icon">
      <path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
    </svg>
    {#if label}
      <span class="label">{label}</span>
    {/if}
  </div>

  <div class="controls">
    <button class="play-btn" onclick={togglePlay} aria-label={paused ? 'Play' : 'Pause'}>
      {#if paused}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      {:else}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
      {/if}
    </button>

    <input
      type="range"
      min="0"
      max={duration || 100}
      step="0.05"
      value={currentTime}
      oninput={seek}
      style:background={trackBg}
      class="track"
    />

    <span class="time">{fmt(currentTime)} / {fmt(duration)}</span>

    <button class="vol-btn" onclick={toggleMute} aria-label={muted ? 'Unmute' : 'Mute'}>
      {#if muted || volume === 0}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>
        </svg>
      {:else if volume < 0.5}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
        </svg>
      {:else}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
        </svg>
      {/if}
    </button>
    <input
      type="range"
      min="0"
      max="1"
      step="0.02"
      value={muted ? 0 : volume}
      oninput={setVolume}
      style:background={volBg}
      class="track vol-track"
      aria-label="Volume"
    />
  </div>

  <!-- svelte-ignore a11y_media_has_caption -->
  <audio
    bind:this={audio}
    {src}
    onplay={() => (paused = false)}
    onpause={() => (paused = true)}
    onended={() => { paused = true; currentTime = 0; }}
    ontimeupdate={() => { if (audio) currentTime = audio.currentTime; }}
    onloadedmetadata={() => { if (audio) duration = audio.duration; }}
  ></audio>
</div>

<style>
  .player {
    border-radius: 10px;
    border: 1px solid var(--quip-border-strong);
    background: var(--quip-bg-raised);
    overflow: hidden;
    my: 0.5rem;
  }

  .header {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 10px 14px 4px;
  }

  .note-icon {
    color: var(--quip-text-muted);
    flex-shrink: 0;
    margin-top: 1px;
  }

  .label {
    font-size: 11px;
    line-height: 1.4;
    color: var(--quip-text-dim);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .controls {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 14px 10px;
  }

  .play-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: 1px solid var(--quip-border-strong);
    background: transparent;
    color: var(--quip-text);
    cursor: pointer;
    flex-shrink: 0;
    transition: background 120ms;
  }
  .play-btn:hover {
    background: var(--quip-hover);
  }
  .play-btn:active {
    transform: scale(0.92);
  }

  .track {
    -webkit-appearance: none;
    appearance: none;
    flex: 1;
    height: 3px;
    border-radius: 2px;
    outline: none;
    cursor: pointer;
    border: none;
    padding: 0;
    margin: 0;
  }
  .track::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 11px;
    height: 11px;
    border-radius: 50%;
    background: var(--quip-text-dim);
    cursor: pointer;
    transition: transform 120ms;
  }
  .track:hover::-webkit-slider-thumb {
    transform: scale(1.25);
  }
  .track::-moz-range-thumb {
    width: 11px;
    height: 11px;
    border-radius: 50%;
    background: var(--quip-text-dim);
    border: none;
    cursor: pointer;
  }
  .track::-moz-range-track {
    background: transparent;
  }

  .time {
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    color: var(--quip-text-muted);
    white-space: nowrap;
    flex-shrink: 0;
  }

  .vol-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border: none;
    background: transparent;
    color: var(--quip-text-muted);
    cursor: pointer;
    flex-shrink: 0;
    padding: 0;
    transition: color 120ms;
  }
  .vol-btn:hover {
    color: var(--quip-text);
  }

  .vol-track {
    flex: 0 0 56px;
  }
</style>
