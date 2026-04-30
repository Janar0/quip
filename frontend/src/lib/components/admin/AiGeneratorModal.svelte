<script lang="ts">
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import { generateSkillDraft, type SkillInfo } from '$lib/api/admin';

  let {
    open,
    ongenerated,
    onclose,
  }: {
    open: boolean;
    ongenerated: (draft: SkillInfo) => void;
    onclose: () => void;
  } = $props();

  let aiPrompt = $state('');
  let aiGenerating = $state(false);

  async function runAiGenerate() {
    if (!aiPrompt.trim()) return;
    aiGenerating = true;
    const draft = await generateSkillDraft(aiPrompt);
    aiGenerating = false;
    if (!draft) {
      toast.error($t('common.error'));
      return;
    }
    ongenerated(draft);
    aiPrompt = '';
  }
</script>

{#if open}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 bg-black/60 z-40 flex items-center justify-center p-4"
    tabindex="-1"
    onclick={() => onclose()}
    onkeydown={(e) => e.key === 'Escape' && onclose()}
  >
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="card w-full max-w-xl flex flex-col" onclick={(e) => e.stopPropagation()}>
      <div class="p-4 border-b border-surface-500/20 flex items-center justify-between">
        <h2 class="text-lg font-semibold">✨ {$t('admin.skills.generateAi')}</h2>
        <button class="btn btn-sm preset-outlined" onclick={() => onclose()}>✕</button>
      </div>
      <div class="p-4 space-y-3">
        <label class="label">
          <span class="text-sm">{$t('admin.skills.generateAiPrompt')}</span>
          <textarea
            class="textarea"
            rows="6"
            bind:value={aiPrompt}
            placeholder={$t('admin.skills.generateAiPlaceholder')}
          ></textarea>
        </label>
        <p class="text-xs opacity-60">{$t('admin.skills.generateAiHint')}</p>
      </div>
      <div class="p-4 border-t border-surface-500/20 flex justify-end gap-2">
        <button class="btn preset-outlined" onclick={() => onclose()}>{$t('common.cancel')}</button>
        <button class="btn preset-filled-primary-500" onclick={runAiGenerate} disabled={aiGenerating || !aiPrompt.trim()}>
          {aiGenerating ? '...' : $t('admin.skills.generate')}
        </button>
      </div>
    </div>
  </div>
{/if}
