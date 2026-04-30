<script lang="ts">
  import { t } from 'svelte-i18n';
  import type { SkillInfo } from '$lib/api/admin';

  let {
    skill,
    onedit,
    ontoggle,
    ondelete,
  }: {
    skill: SkillInfo;
    onedit?: (skill: SkillInfo) => void;
    ontoggle?: (skill: SkillInfo) => void;
    ondelete?: (skill: SkillInfo) => void;
  } = $props();

  function getCategoryColor(category: string): string {
    if (category === 'widget') return 'preset-filled-primary-500';
    if (category === 'tool') return 'preset-filled-secondary-500';
    return 'preset-outlined';
  }
</script>

<div class="card p-4 space-y-3 {skill.enabled ? '' : 'opacity-50'}">
  <div class="flex items-start justify-between gap-2">
    <div class="flex-1 min-w-0">
      <div class="font-semibold text-sm truncate">{skill.name}</div>
      <div class="text-xs opacity-60 mt-0.5 truncate">{skill.id}</div>
    </div>
    <span class="badge text-xs {getCategoryColor(skill.category)} flex-shrink-0">
      {skill.category}
    </span>
  </div>
  <p class="text-xs opacity-60 line-clamp-2">{skill.description}</p>
  <div class="flex items-center gap-1.5">
    <span class="badge badge-sm text-xs {skill.type === 'api' ? 'preset-filled-warning-500' : 'preset-outlined'}">
      {skill.type}
    </span>
    {#if skill.is_builtin}
      <span class="badge badge-sm text-xs preset-outlined opacity-50">{$t('admin.skills.builtin')}</span>
    {/if}
  </div>
  <div class="flex items-center justify-between pt-1 border-t border-surface-500/20">
    <label class="flex items-center gap-1.5 cursor-pointer">
      <input
        type="checkbox"
        class="checkbox checkbox-sm"
        checked={skill.enabled}
        onchange={() => ontoggle?.(skill)}
      />
      <span class="text-xs">{$t('admin.skills.enabled')}</span>
    </label>
    <div class="flex gap-1">
      <button class="btn btn-sm preset-outlined" onclick={() => onedit?.(skill)} aria-label={$t('admin.skills.edit')} title={$t('admin.skills.edit')}>
        ✎
      </button>
      {#if !skill.is_builtin}
        <button class="btn btn-sm preset-filled-error-500" onclick={() => ondelete?.(skill)} aria-label={$t('admin.skills.delete')} title={$t('admin.skills.delete')}>
          ✕
        </button>
      {/if}
    </div>
  </div>
</div>
