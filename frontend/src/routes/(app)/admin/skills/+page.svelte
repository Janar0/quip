<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import {
    getSkills,
    updateSkill,
    deleteSkill,
    type SkillInfo,
  } from '$lib/api/admin';
  import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
  import SkillCard from '$lib/components/admin/SkillCard.svelte';
  import SkillFormModal from '$lib/components/admin/SkillFormModal.svelte';
  import AiGeneratorModal from '$lib/components/admin/AiGeneratorModal.svelte';

  let skills = $state<SkillInfo[]>([]);
  let loading = $state(true);

  // Modal state
  let skillModalOpen = $state(false);
  let editingSkill = $state<SkillInfo | null>(null);
  let skillDraft = $state<Record<string, unknown> | null>(null);

  let aiModalOpen = $state(false);

  // Delete state
  let deleteConfirmOpen = $state(false);
  let skillToDelete = $state<SkillInfo | null>(null);

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
    skillDraft = null;
    skillModalOpen = true;
  }

  function openEdit(skill: SkillInfo) {
    editingSkill = skill;
    skillDraft = null;
    skillModalOpen = true;
  }

  function handleSaved() {
    skillModalOpen = false;
    editingSkill = null;
    skillDraft = null;
    reload();
  }

  function handleCloseSkillModal() {
    skillModalOpen = false;
    editingSkill = null;
    skillDraft = null;
  }

  function handleAiGenerated(draft: SkillInfo) {
    aiModalOpen = false;
    editingSkill = null;
    skillDraft = draft as unknown as Record<string, unknown>;
    skillModalOpen = true;
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
</script>

<div class="p-8 max-w-6xl mx-auto space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-bold">{$t('admin.skills.title')}</h1>
    <div class="flex gap-2">
      <button class="btn preset-outlined" onclick={() => { aiModalOpen = true; }}>
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
        <SkillCard {skill} onedit={openEdit} ontoggle={toggleEnabled} ondelete={confirmDelete} />
      {/each}
    </div>
  {/if}
</div>

<SkillFormModal
  open={skillModalOpen}
  editingSkill={editingSkill}
  draftData={skillDraft}
  onsaved={handleSaved}
  onclose={handleCloseSkillModal}
/>

<AiGeneratorModal
  open={aiModalOpen}
  ongenerated={handleAiGenerated}
  onclose={() => { aiModalOpen = false; }}
/>

<ConfirmDialog
  open={deleteConfirmOpen}
  title={$t('admin.skills.delete')}
  message={$t('admin.skills.deleteConfirm')}
  onConfirm={performDelete}
  onCancel={() => { deleteConfirmOpen = false; skillToDelete = null; }}
/>
