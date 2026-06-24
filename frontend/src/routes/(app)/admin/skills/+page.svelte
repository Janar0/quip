<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import { fly } from 'svelte/transition';
  import { D2 } from '$lib/motion';
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
  import AdminPageHeader from '$lib/components/admin/AdminPageHeader.svelte';

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

<div class="admin-page" in:fly={{ y: 8, duration: D2 }}>
 <div class="max-w-6xl mx-auto space-y-5">
  <AdminPageHeader icon="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" title={$t('admin.skills.title')}>
    {#snippet actions()}
      <button class="btn btn-sm preset-outlined" onclick={() => { aiModalOpen = true; }}>
        ✨ <span class="hidden sm:inline">{$t('admin.skills.generateAi')}</span>
      </button>
      <button class="btn btn-sm preset-filled-primary-500" onclick={openCreate}>
        + <span class="hidden sm:inline">{$t('admin.skills.add')}</span>
      </button>
    {/snippet}
  </AdminPageHeader>

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
