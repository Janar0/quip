<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import Mustache from 'mustache';
  import {
    getSkills,
    createSkill,
    updateSkill,
    deleteSkill,
    generateSkillDraft,
    type SkillInfo,
    type SkillUpsertData,
    type SkillSettingField,
  } from '$lib/api/admin';
  import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

  let skills = $state<SkillInfo[]>([]);
  let loading = $state(true);

  // Modal state
  type Tab = 'general' | 'prompt' | 'template' | 'api' | 'settings' | 'preview';
  let modalOpen = $state(false);
  let editingSkill = $state<SkillInfo | null>(null);
  let activeTab = $state<Tab>('general');
  let saving = $state(false);

  // Delete state
  let deleteConfirmOpen = $state(false);
  let skillToDelete = $state<SkillInfo | null>(null);

  // AI generator state
  let aiModalOpen = $state(false);
  let aiPrompt = $state('');
  let aiGenerating = $state(false);

  type FormShape = SkillUpsertData & {
    id: string;
    settings_schema: SkillSettingField[] | null;
    settings: Record<string, unknown> | null;
  };

  const emptyForm = (): FormShape => ({
    id: '',
    name: '',
    description: '',
    category: 'widget',
    icon: null,
    type: 'content',
    enabled: true,
    prompt_instructions: '',
    data_schema: null,
    template_html: null,
    template_css: null,
    api_config: null,
    settings_schema: null,
    settings: null,
  });

  let form = $state<FormShape>(emptyForm());

  // Live-rendered preview (widget category only)
  let previewHtml = $derived.by(() => {
    if (form.category !== 'widget' || !form.template_html) return '';
    const schema = form.data_schema || {};
    const sample = ((schema as Record<string, unknown>).example as Record<string, unknown>) || schema;
    try {
      return Mustache.render(form.template_html, sample);
    } catch (e) {
      return `<pre style="color:#f87171">Preview error: ${String(e)}</pre>`;
    }
  });

  onMount(async () => {
    await reload();
  });

  async function reload() {
    loading = true;
    skills = await getSkills();
    loading = false;
  }

  function openCreate() {
    editingSkill = null;
    form = emptyForm();
    activeTab = 'general';
    modalOpen = true;
  }

  function openEdit(skill: SkillInfo) {
    editingSkill = skill;
    form = {
      id: skill.id,
      name: skill.name,
      description: skill.description,
      category: skill.category,
      icon: skill.icon,
      type: skill.type,
      enabled: skill.enabled,
      prompt_instructions: skill.prompt_instructions,
      data_schema: skill.data_schema,
      template_html: skill.template_html,
      template_css: skill.template_css,
      api_config: skill.api_config,
      settings_schema: skill.settings_schema,
      settings: skill.settings || {},
    };
    activeTab = 'general';
    modalOpen = true;
  }

  async function save() {
    saving = true;
    if (editingSkill) {
      const { id: _id, settings_schema: _ss, ...updateData } = form;
      const ok = await updateSkill(editingSkill.id, updateData);
      if (ok) {
        toast.success($t('admin.skills.saved'));
        modalOpen = false;
        await reload();
      } else {
        toast.error($t('common.error'));
      }
    } else {
      const ok = await createSkill(form);
      if (ok) {
        toast.success($t('admin.skills.created'));
        modalOpen = false;
        await reload();
      } else {
        toast.error($t('common.error'));
      }
    }
    saving = false;
  }

  async function toggleEnabled(skill: SkillInfo) {
    const ok = await updateSkill(skill.id, { enabled: !skill.enabled });
    if (ok) {
      skills = skills.map(s => s.id === skill.id ? { ...s, enabled: !s.enabled } : s);
    }
  }

  function confirmDelete(skill: SkillInfo) {
    skillToDelete = skill;
    deleteConfirmOpen = true;
  }

  async function performDelete() {
    if (!skillToDelete) return;
    const ok = await deleteSkill(skillToDelete.id);
    if (ok) {
      toast.success($t('admin.skills.deleted'));
      skills = skills.filter(s => s.id !== skillToDelete!.id);
    } else {
      toast.error($t('common.error'));
    }
    deleteConfirmOpen = false;
    skillToDelete = null;
  }

  function getCategoryColor(category: string): string {
    if (category === 'widget') return 'preset-filled-primary-500';
    if (category === 'tool') return 'preset-filled-secondary-500';
    return 'preset-outlined';
  }

  function setSetting(key: string, value: unknown) {
    form.settings = { ...(form.settings || {}), [key]: value };
  }

  function getSetting(key: string, def: unknown): unknown {
    const cur = (form.settings || {})[key];
    return cur === undefined ? def : cur;
  }

  async function runAiGenerate() {
    if (!aiPrompt.trim()) return;
    aiGenerating = true;
    const draft = await generateSkillDraft(aiPrompt);
    aiGenerating = false;
    if (!draft) {
      toast.error($t('common.error'));
      return;
    }
    aiModalOpen = false;
    // Pre-fill the create modal with the draft
    editingSkill = null;
    form = {
      id: (draft.id as string) || '',
      name: (draft.name as string) || '',
      description: (draft.description as string) || '',
      category: (draft.category as string) || 'widget',
      icon: null,
      type: (draft.type as string) || 'content',
      enabled: true,
      prompt_instructions: (draft.prompt_instructions as string) || '',
      data_schema: draft.data_schema || null,
      template_html: draft.template_html || null,
      template_css: draft.template_css || null,
      api_config: draft.api_config || null,
      settings_schema: draft.settings_schema || null,
      settings: {},
    };
    activeTab = 'preview';
    modalOpen = true;
    aiPrompt = '';
  }

  const ALL_TABS: Tab[] = ['general', 'prompt', 'template', 'api', 'settings', 'preview'];
  function visibleTabs(f: FormShape): Tab[] {
    return ALL_TABS.filter((tab) => {
      if (tab === 'template' && f.category !== 'widget') return false;
      if (tab === 'api' && f.type !== 'api') return false;
      if (tab === 'settings' && !(f.settings_schema && f.settings_schema.length)) return false;
      if (tab === 'preview' && f.category !== 'widget') return false;
      return true;
    });
  }

  function tabLabel(tab: Tab): string {
    if (tab === 'api') return $t('admin.skills.apiConfig');
    if (tab === 'settings') return $t('admin.skills.settings');
    if (tab === 'preview') return $t('admin.skills.preview');
    return $t(`admin.skills.${tab}`);
  }
</script>

<div class="p-8 max-w-6xl mx-auto space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-bold">{$t('admin.skills.title')}</h1>
    <div class="flex gap-2">
      <button class="btn preset-outlined" onclick={() => { aiModalOpen = true; aiPrompt = ''; }}>
        ✨ {$t('admin.skills.generateAi')}
      </button>
      <button class="btn preset-filled-primary-500" onclick={openCreate}>
        + {$t('admin.skills.add')}
      </button>
    </div>
  </div>

  {#if loading}
    <p class="opacity-50">{$t('common.loading')}</p>
  {:else if skills.length === 0}
    <p class="opacity-50">{$t('admin.skills.empty')}</p>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {#each skills as skill (skill.id)}
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
                onchange={() => toggleEnabled(skill)}
              />
              <span class="text-xs">{$t('admin.skills.enabled')}</span>
            </label>
            <div class="flex gap-1">
              <button class="btn btn-sm preset-outlined" onclick={() => openEdit(skill)}>
                ✎
              </button>
              {#if !skill.is_builtin}
                <button class="btn btn-sm preset-filled-error-500" onclick={() => confirmDelete(skill)}>
                  ✕
                </button>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<!-- Edit/Create Modal -->
{#if modalOpen}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 bg-black/60 z-40 flex items-center justify-center p-4"
    tabindex="-1"
    onclick={() => (modalOpen = false)}
    onkeydown={(e) => e.key === 'Escape' && (modalOpen = false)}
  >
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="card w-full max-w-3xl max-h-[92vh] flex flex-col"
      onclick={(e) => e.stopPropagation()}
    >
      <div class="p-4 border-b border-surface-500/20 flex items-center justify-between">
        <h2 class="text-lg font-semibold">
          {editingSkill ? $t('admin.skills.edit') : $t('admin.skills.add')}
        </h2>
        <button class="btn btn-sm preset-outlined" onclick={() => (modalOpen = false)}>✕</button>
      </div>

      <!-- Tabs -->
      <div class="flex gap-1 px-4 pt-3 border-b border-surface-500/20 flex-wrap">
        {#each visibleTabs(form) as tab}
          <button
            class="btn btn-sm {activeTab === tab ? 'preset-filled' : 'preset-outlined'}"
            onclick={() => (activeTab = tab)}
          >
            {tabLabel(tab)}
          </button>
        {/each}
      </div>

      <!-- Tab content -->
      <div class="flex-1 overflow-y-auto p-4 space-y-4">
        {#if activeTab === 'general'}
          <label class="label">
            <span class="text-sm">{$t('admin.skills.id')}</span>
            <input class="input" type="text" bind:value={form.id} disabled={!!editingSkill} placeholder="my-skill" />
          </label>
          <label class="label">
            <span class="text-sm">{$t('admin.skills.name')}</span>
            <input class="input" type="text" bind:value={form.name} placeholder="My Skill" />
          </label>
          <label class="label">
            <span class="text-sm">{$t('admin.skills.description')}</span>
            <input class="input" type="text" bind:value={form.description} placeholder="Short description for AI index" />
          </label>
          <div class="grid grid-cols-2 gap-4">
            <label class="label">
              <span class="text-sm">{$t('admin.skills.category')}</span>
              <select class="select" bind:value={form.category}>
                <option value="widget">widget</option>
                <option value="tool">tool</option>
                <option value="artifact">artifact</option>
              </select>
            </label>
            <label class="label">
              <span class="text-sm">{$t('admin.skills.type')}</span>
              <select class="select" bind:value={form.type}>
                <option value="content">{$t('admin.skills.typeContent')}</option>
                <option value="api">{$t('admin.skills.typeApi')}</option>
              </select>
            </label>
          </div>
          <label class="flex items-center gap-2">
            <input type="checkbox" class="checkbox" bind:checked={form.enabled} />
            <span class="text-sm">{$t('admin.skills.enabled')}</span>
          </label>

        {:else if activeTab === 'prompt'}
          <label class="label">
            <span class="text-sm">{$t('admin.skills.promptInstructions')}</span>
            <textarea
              class="textarea font-mono text-xs"
              rows="18"
              bind:value={form.prompt_instructions}
              placeholder="Instructions shown to the AI when it calls load_skill()"
            ></textarea>
          </label>

        {:else if activeTab === 'template'}
          <label class="label">
            <span class="text-sm">{$t('admin.skills.templateHtml')}</span>
            <textarea
              class="textarea font-mono text-xs"
              rows="10"
              bind:value={form.template_html}
              placeholder={"<div class='widget-myskill'>{{field}}</div>"}
            ></textarea>
          </label>
          <label class="label">
            <span class="text-sm">{$t('admin.skills.templateCss')}</span>
            <textarea
              class="textarea font-mono text-xs"
              rows="6"
              bind:value={form.template_css}
              placeholder=".widget-card .widget-myskill {'{ ... }'}"
            ></textarea>
          </label>

        {:else if activeTab === 'api'}
          <p class="text-sm opacity-60">API configuration as JSON object with url, method, headers, params_mapping, response_mapping fields.</p>
          <label class="label">
            <span class="text-sm">api_config (JSON)</span>
            <textarea
              class="textarea font-mono text-xs"
              rows="12"
              value={form.api_config ? JSON.stringify(form.api_config, null, 2) : ''}
              oninput={(e) => {
                try {
                  form.api_config = JSON.parse(e.currentTarget.value);
                } catch {
                  // keep invalid JSON in textarea without breaking form
                }
              }}
              placeholder={'{"url": "https://api.example.com/...", "method": "GET", ..."}'}
            ></textarea>
          </label>

        {:else if activeTab === 'settings'}
          {#if form.settings_schema && form.settings_schema.length}
            {#each form.settings_schema as field (field.key)}
              <label class="label">
                <span class="text-sm">{field.label || field.key}</span>
                {#if field.type === 'select'}
                  <select class="select" value={getSetting(field.key, field.default ?? '')}
                    onchange={(e) => setSetting(field.key, e.currentTarget.value)}>
                    {#each (field.options || []) as opt}
                      <option value={opt}>{opt}</option>
                    {/each}
                  </select>
                {:else if field.type === 'boolean'}
                  <input type="checkbox" class="checkbox"
                    checked={!!getSetting(field.key, field.default ?? false)}
                    onchange={(e) => setSetting(field.key, e.currentTarget.checked)} />
                {:else if field.type === 'number'}
                  <input type="number" class="input"
                    value={getSetting(field.key, field.default ?? 0) as number}
                    oninput={(e) => setSetting(field.key, Number(e.currentTarget.value))} />
                {:else}
                  <input
                    type={field.type === 'password' ? 'password' : 'text'}
                    class="input"
                    value={getSetting(field.key, field.default ?? '') as string}
                    oninput={(e) => setSetting(field.key, e.currentTarget.value)}
                  />
                {/if}
                {#if field.help}
                  <span class="text-xs opacity-60 mt-1 block">{field.help}</span>
                {/if}
              </label>
            {/each}
          {:else}
            <p class="text-sm opacity-60">{$t('admin.skills.noSettings')}</p>
          {/if}

        {:else if activeTab === 'preview'}
          {#if form.template_css}
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html `<style>${form.template_css}</style>`}
          {/if}
          <div class="widget-card p-0 rounded-lg border border-surface-500/30 bg-surface-900/40 overflow-hidden">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html previewHtml}
          </div>
          <p class="text-xs opacity-60">
            {$t('admin.skills.previewHint')}
          </p>
        {/if}
      </div>

      <div class="p-4 border-t border-surface-500/20 flex justify-end gap-2">
        <button class="btn preset-outlined" onclick={() => (modalOpen = false)}>{$t('common.cancel')}</button>
        <button class="btn preset-filled-primary-500" onclick={save} disabled={saving || !form.name || !form.id}>
          {saving ? '...' : $t('common.save')}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- AI Generator Modal -->
{#if aiModalOpen}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 bg-black/60 z-40 flex items-center justify-center p-4"
    tabindex="-1"
    onclick={() => (aiModalOpen = false)}
    onkeydown={(e) => e.key === 'Escape' && (aiModalOpen = false)}
  >
    <div class="card w-full max-w-xl flex flex-col" onclick={(e) => e.stopPropagation()}>
      <div class="p-4 border-b border-surface-500/20">
        <h2 class="text-lg font-semibold">✨ {$t('admin.skills.generateAi')}</h2>
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
        <button class="btn preset-outlined" onclick={() => (aiModalOpen = false)}>{$t('common.cancel')}</button>
        <button class="btn preset-filled-primary-500" onclick={runAiGenerate} disabled={aiGenerating || !aiPrompt.trim()}>
          {aiGenerating ? '...' : $t('admin.skills.generate')}
        </button>
      </div>
    </div>
  </div>
{/if}

<ConfirmDialog
  open={deleteConfirmOpen}
  title={$t('admin.skills.delete')}
  message={$t('admin.skills.deleteConfirm')}
  onConfirm={performDelete}
  onCancel={() => { deleteConfirmOpen = false; skillToDelete = null; }}
/>
