<script lang="ts">
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import { fade } from 'svelte/transition';
  import { D1 } from '$lib/motion';
  import { isStreaming, modePreference, searchEnabled, type ModePreference } from '$lib/stores/chat';
  import { stopGeneration } from '$lib/api/chats';
  import { uploadFiles, getFileUrl, deleteFile, type UploadedFile } from '$lib/api/files';

  let {
    onSend,
    chatId,
    variant = 'chat',
  }: {
    onSend: (text: string, fileIds: string[], uploadedFiles: UploadedFile[]) => void;
    chatId?: string;
    variant?: 'chat' | 'start';
  } = $props();

  let text = $state('');
  let textareaEl: HTMLTextAreaElement;
  let fileInputEl: HTMLInputElement;
  let isDragOver = $state(false);
  let dragCounter = 0;

  interface AttachedFile {
    _id: number;
    file: File;
    preview?: string;
    uploading: boolean;
    uploaded?: UploadedFile;
    error?: string;
  }

  let _nextId = 0;
  let attachedFiles = $state<AttachedFile[]>([]);

  // Cleanup ObjectURLs when component unmounts
  $effect(() => {
    return () => {
      for (const att of attachedFiles) {
        if (att.preview) URL.revokeObjectURL(att.preview);
      }
    };
  });

  // Auto-resize textarea
  $effect(() => {
    if (textareaEl) {
      textareaEl.style.height = 'auto';
      textareaEl.style.height = Math.min(textareaEl.scrollHeight, 200) + 'px';
    }
    void text;
  });

  function isImageFile(file: File): boolean {
    return file.type.startsWith('image/');
  }

  async function addFiles(files: FileList | File[]) {
    const fileArray = Array.from(files);
    if (!fileArray.length) return;

    const batchIds: number[] = [];
    const newAttachments: AttachedFile[] = fileArray.map((file) => {
      const id = _nextId++;
      batchIds.push(id);
      const att: AttachedFile = { _id: id, file, uploading: true };
      if (isImageFile(file)) {
        att.preview = URL.createObjectURL(file);
      }
      return att;
    });

    attachedFiles = [...attachedFiles, ...newAttachments];

    try {
      const uploaded = await uploadFiles(fileArray, chatId);
      attachedFiles = attachedFiles.map((att) => {
        const batchIdx = batchIds.indexOf(att._id);
        if (batchIdx < 0) return att;
        if (batchIdx < uploaded.length) {
          return { ...att, uploading: false, uploaded: uploaded[batchIdx] };
        }
        return { ...att, uploading: false, error: 'Upload failed' };
      });
    } catch {
      toast.error($t('chat.uploadFailed'));
      attachedFiles = attachedFiles.map((att) =>
        batchIds.includes(att._id) && att.uploading ? { ...att, uploading: false, error: 'Upload failed' } : att,
      );
    }
  }

  async function removeAttachment(index: number) {
    const att = attachedFiles[index];
    if (att.preview) URL.revokeObjectURL(att.preview);
    if (att.uploaded) {
      deleteFile(att.uploaded.id).catch(() => {});
    }
    attachedFiles = attachedFiles.filter((_, i) => i !== index);
  }

  function handleFileSelect(e: Event) {
    const input = e.target as HTMLInputElement;
    if (input.files?.length) {
      addFiles(input.files);
      input.value = '';
    }
  }

  // Window-level drag-and-drop
  $effect(() => {
    function onDragEnter(e: DragEvent) {
      if (e.dataTransfer?.types.includes('Files')) {
        e.preventDefault();
        dragCounter++;
        isDragOver = true;
      }
    }
    function onDragOver(e: DragEvent) {
      if (e.dataTransfer?.types.includes('Files')) {
        e.preventDefault();
      }
    }
    function onDragLeave() {
      dragCounter--;
      if (dragCounter <= 0) {
        dragCounter = 0;
        isDragOver = false;
      }
    }
    function onDrop(e: DragEvent) {
      e.preventDefault();
      dragCounter = 0;
      isDragOver = false;
      if (e.dataTransfer?.files?.length) {
        addFiles(e.dataTransfer.files);
      }
    }

    document.addEventListener('dragenter', onDragEnter);
    document.addEventListener('dragover', onDragOver);
    document.addEventListener('dragleave', onDragLeave);
    document.addEventListener('drop', onDrop);

    return () => {
      document.removeEventListener('dragenter', onDragEnter);
      document.removeEventListener('dragover', onDragOver);
      document.removeEventListener('dragleave', onDragLeave);
      document.removeEventListener('drop', onDrop);
    };
  });

  function handlePaste(e: ClipboardEvent) {
    const items = e.clipboardData?.items;
    if (!items) return;

    const imageFiles: File[] = [];
    for (const item of items) {
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) imageFiles.push(file);
      }
    }
    if (imageFiles.length) {
      e.preventDefault();
      addFiles(imageFiles);
    }
  }

  function handleSubmit(e: Event) {
    e.preventDefault();
    const trimmed = text.trim();
    const hasFiles = attachedFiles.some((a) => a.uploaded);
    if ((!trimmed && !hasFiles) || $isStreaming) return;
    if (attachedFiles.some((a) => a.uploading)) return;

    const uploaded = attachedFiles
      .filter((a) => a.uploaded)
      .map((a) => a.uploaded!);
    const fileIds = uploaded.map((u) => u.id);
    onSend(trimmed || ' ', fileIds, uploaded);

    for (const att of attachedFiles) {
      if (att.preview) URL.revokeObjectURL(att.preview);
    }
    text = '';
    attachedFiles = [];
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }

  function getFileIcon(file: File): string {
    if (file.type.startsWith('image/')) return '🖼';
    if (file.type.startsWith('video/')) return '🎬';
    if (file.type === 'application/pdf') return '📄';
    if (file.type.includes('word') || file.type.includes('docx')) return '📝';
    if (file.type.includes('csv') || file.type.includes('spreadsheet')) return '📊';
    return '📎';
  }

  function formatSize(bytes: number): string {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }
</script>

{#if isDragOver}
  <div
    class="fixed inset-0 z-50 bg-slate-500/5 border-2 border-dashed border-slate-500/40 pointer-events-none flex items-center justify-center"
    transition:fade={{ duration: D1 }}
  >
    <span class="text-lg text-slate-400">{$t('chat.dropFiles')}</span>
  </div>
{/if}


<form
  onsubmit={handleSubmit}
  class="relative px-4 pb-4 pt-2"
  aria-label="Chat input"
>
  <div class="max-w-4xl mx-auto">
    <div class="quip-glass-strong rounded-[20px]">
      <!-- Attachment preview strip -->
      {#if attachedFiles.length > 0}
        <div class="flex gap-2 px-4 pt-3 pb-1 overflow-x-auto">
          {#each attachedFiles as att, i}
            <div class="relative group flex-shrink-0">
              {#if att.preview}
                <div class="w-16 h-16 rounded-lg overflow-hidden border border-slate-700/30 bg-slate-800/50">
                  <img src={att.preview} alt={att.file.name} class="w-full h-full object-cover" />
                  {#if att.uploading}
                    <div class="absolute inset-0 bg-black/50 flex items-center justify-center rounded-lg">
                      <div class="w-5 h-5 border-2 border-white/50 border-t-white rounded-full animate-spin"></div>
                    </div>
                  {/if}
                  {#if att.error}
                    <div class="absolute inset-0 bg-red-500/50 flex items-center justify-center rounded-lg">
                      <svg class="w-5 h-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                    </div>
                  {/if}
                </div>
              {:else}
                <div class="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-700/30 bg-slate-800/50 max-w-48">
                  <span class="text-lg">{getFileIcon(att.file)}</span>
                  <div class="min-w-0 flex-1">
                    <div class="text-xs font-medium truncate text-slate-300">{att.file.name}</div>
                    <div class="text-[10px] text-slate-500">{formatSize(att.file.size)}</div>
                  </div>
                  {#if att.uploading}
                    <div class="w-4 h-4 border-2 border-slate-600 border-t-slate-300 rounded-full animate-spin flex-shrink-0"></div>
                  {/if}
                  {#if att.error}
                    <svg class="w-4 h-4 text-red-500 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                  {/if}
                </div>
              {/if}
              <button
                type="button"
                class="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-slate-700 border border-slate-600 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-500"
                onclick={() => removeAttachment(i)}
                aria-label="Remove attachment"
              >
                <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          {/each}
        </div>
      {/if}

      <!-- Textarea -->
      <div class="px-4 pt-3 pb-2">
        <textarea
          id="chat-input"
          class="w-full min-h-[44px] max-h-[200px] resize-none bg-transparent border-none focus:outline-none text-sm leading-relaxed"
          style="color: var(--quip-text); --tw-placeholder-opacity: 1"
          placeholder={isDragOver ? $t('chat.dropFiles') : (variant === 'chat' ? $t('chat.replyPlaceholder') : $t('home.startChat'))}
          bind:value={text}
          bind:this={textareaEl}
          onkeydown={handleKeydown}
          onpaste={handlePaste}
          disabled={$isStreaming}
        ></textarea>
      </div>

      <!-- Action bar -->
      <div class="flex items-center justify-between px-3 pb-3">
        <div class="flex items-center gap-1">
          <!-- Paperclip -->
          <button
            type="button"
            class="p-2 rounded-lg quip-icon-btn active:scale-[0.92]"
            onclick={() => fileInputEl.click()}
            title={$t('chat.attach')}
            aria-label={$t('chat.attach')}
            disabled={$isStreaming}
          >
            <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>
          <input
            type="file"
            multiple
            class="hidden"
            bind:this={fileInputEl}
            onchange={handleFileSelect}
            accept="*/*"
          />

          {#if $searchEnabled}
            <div class="quip-seg ml-1">
              {#each ['auto', 'search'] as const as m (m)}
                <button
                  type="button"
                  class={$modePreference === m ? 'on' : ''}
                  onclick={() => modePreference.set(m as ModePreference)}
                  disabled={$isStreaming}
                >{$t(`chat.mode_${m}`)}</button>
              {/each}
            </div>
          {/if}
        </div>

        <!-- Send / Stop -->
        <div class="flex items-center gap-2">
          {#if $isStreaming}
            <button
              type="button"
              class="quip-send-btn"
              onclick={stopGeneration}
              title={$t('chat.stopGeneration')}
              aria-label={$t('chat.stopGeneration')}
            >
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
            </button>
          {:else}
            <button
              type="submit"
              class="quip-send-btn"
              disabled={!text.trim() && !attachedFiles.some((a) => a.uploaded)}
              aria-label={$t('chat.sendMessage')}
            >
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
            </button>
          {/if}
        </div>
      </div>
    </div>
  </div>
</form>
