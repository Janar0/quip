<script lang="ts">
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import Mustache from 'mustache';
  import {
    createSkill,
    updateSkill,
    type SkillInfo,
    type SkillUpsertData,
    type SkillSettingField,
  } from '$lib/api/admin';

  let {
    open,
    editingSkill,
    draftData,
    onsaved,
    onclose,
  }: {
    open: boolean;
    editingSkill: SkillInfo | null;
    draftData?: Record<string, unknown> | null;
    onsaved: () => void;
    onclose: () => void;
  } = $props();

  type Tab = 'general' | 'prompt' | 'template' | 'api' | 'settings' | 'preview';

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
  let activeTab = $state<Tab>('general');
  let saving = $state(false);

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

  let _prevOpen = false;
  $effect(() => {
    if (open && !_prevOpen) {
      if (editingSkill) {
        form = {
          id: editingSkill.id,
          name: editingSkill.name,
          description: editingSkill.description,
          category: editingSkill.category,
          icon: editingSkill.icon,
          type: editingSkill.type,
          enabled: editingSkill.enabled,
          prompt_instructions: editingSkill.prompt_instructions,
          data_schema: editingSkill.data_schema,
          template_html: editingSkill.template_html,
          template_css: editingSkill.template_css,
          api_config: editingSkill.api_config,
          settings_schema: editingSkill.settings_schema,
          settings: editingSkill.settings || {},
        };
      } else if (draftData) {
        form = {
          id: (draftData.id as string) || '',
          name: (draftData.name as string) || '',
          description: (draftData.description as string) || '',
          category: (draftData.category as string) || 'widget',
          icon: null,
          type: (draftData.type as string) || 'content',
          enabled: true,
          prompt_instructions: (draftData.prompt_instructions as string) || '',
          data_schema: (draftData.data_schema as Record<string, unknown>) || null,
          template_html: (draftData.template_html as string) || null,
          template_css: (draftData.template_css as string) || null,
          api_config: (draftData.api_config as Record<string, unknown>) || null,
          settings_schema: (draftData.settings_schema as SkillSettingField[]) || null,
          settings: {},
        };
        activeTab = 'preview';
        return;
      } else {
        form = emptyForm();
      }
      activeTab = 'general';
    }
    _prevOpen = open;
  });

  async function save() {
    saving = true;
    if (editingSkill) {
      const { id: _id, settings_schema: _ss, ...updateData } = form;
      const ok = await updateSkill(editingSkill.id, updateData);
      if (ok) {
        toast.success($t('admin.skills.saved'));
        onsaved();
      } else {
        toast.error($t('common.error'));
      }
    } else {
      const ok = await createSkill(form);
      if (ok) {
        toast.success($t('admin.skills.created'));
        onsaved();
      } else {
        toast.error($t('common.error'));
      }
    }
    saving = false;
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

  function setSetting(key: string, value: unknown) {
    form.settings = { ...(form.settings || {}), [key]: value };
  }

  function getSetting(key: string, def: unknown): unknown {
    const cur = (form.settings || {})[key];
    return cur === undefined ? def : cur;
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
    <div
      class="card w-full max-w-3xl max-h-[92vh] flex flex-col"
      onclick={(e) => e.stopPropagation()}
    >
      <div class="p-4 border-b border-surface-500/20 flex items-center justify-between">
        <h2 class="text-lg font-semibold">
          {editingSkill ? $t('admin.skills.edit') : $t('admin.skills.add')}
        </h2>
        <button class="btn btn-sm preset-outlined" onclick={() => onclose()}>✕</button>
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
              placeholder={'{"url": "https://api.example.com/...", "method": "GET", ...}'}
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
        <button class="btn preset-outlined" onclick={() => onclose()}>{$t('common.cancel')}</button>
        <button class="btn preset-filled-primary-500" onclick={save} disabled={saving || !form.name || !form.id}>
          {saving ? '...' : $t('common.save')}
        </button>
      </div>
    </div>
  </div>
{/if}
