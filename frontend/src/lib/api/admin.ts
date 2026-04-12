import { api } from '$lib/api/client';

export async function getSettings(): Promise<{ openrouter_api_key_set: boolean; openrouter_key_info: Record<string, unknown> | null; ollama_url?: string; system_prompt?: string; gismeteo_api_key_set?: boolean; model_whitelist?: string[]; model_aliases?: Record<string, string>; artifacts_enabled?: boolean; sandbox_enabled?: boolean; sandbox_memory_limit?: string; sandbox_cpu_limit?: string; sandbox_idle_timeout?: number; sandbox_exec_timeout?: number; rag_enabled?: boolean; embedding_provider?: string; embedding_model?: string; rag_chunk_size?: number; rag_chunk_overlap?: number; rag_top_k?: number; search_enabled?: boolean; research_enabled?: boolean; search_provider?: string; tavily_api_key_set?: boolean; searxng_url?: string; search_model?: string; research_model?: string; title_model?: string; default_model?: string | null; image_model?: string | null }> {
  const res = await api('/api/admin/settings');
  if (res.ok) return res.json();
  return { openrouter_api_key_set: false, openrouter_key_info: null };
}

export async function updateSettings(data: { openrouter_api_key?: string; ollama_url?: string; system_prompt?: string; gismeteo_api_key?: string; model_whitelist?: string[]; model_aliases?: Record<string, string>; artifacts_enabled?: boolean; sandbox_enabled?: boolean; sandbox_memory_limit?: string; sandbox_cpu_limit?: string; sandbox_idle_timeout?: number; sandbox_exec_timeout?: number; rag_enabled?: boolean; embedding_provider?: string; embedding_model?: string; rag_chunk_size?: number; rag_chunk_overlap?: number; rag_top_k?: number; search_enabled?: boolean; research_enabled?: boolean; search_provider?: string; tavily_api_key?: string; searxng_url?: string; search_model?: string; research_model?: string; title_model?: string; default_model?: string | null; image_model?: string | null }): Promise<boolean> {
  const res = await api('/api/admin/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
  return res.ok;
}

export interface AdminUser {
  id: string;
  email: string;
  username: string;
  name: string;
  role: string;
  is_active: boolean;
  last_active_at: string | null;
}

export async function getUsers(): Promise<AdminUser[]> {
  const res = await api('/api/admin/users');
  if (res.ok) return res.json();
  return [];
}

export async function updateUserRole(userId: string, role: string): Promise<boolean> {
  const res = await api(`/api/admin/users/${userId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
  return res.ok;
}

export async function updateUserStatus(userId: string, isActive: boolean): Promise<boolean> {
  const res = await api(`/api/admin/users/${userId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ is_active: isActive }),
  });
  return res.ok;
}

export async function deleteUser(userId: string): Promise<boolean> {
  const res = await api(`/api/admin/users/${userId}`, { method: 'DELETE' });
  return res.ok;
}

export async function changeUserPassword(userId: string, password: string): Promise<boolean> {
  const res = await api(`/api/admin/users/${userId}/password`, {
    method: 'PATCH',
    body: JSON.stringify({ password }),
  });
  return res.ok;
}

export interface UsageData {
  period_days: number;
  totals: {
    requests: number;
    cost: number;
    prompt_tokens: number;
    completion_tokens: number;
    cached_tokens: number;
  };
  by_model: { model: string; display_name: string; requests: number; cost: number; tokens: number }[];
  by_user: { name: string; email: string; requests: number; cost: number }[];
  by_day: { day: string; requests: number; cost: number }[];
}

const _usageCache = new Map<number, { ts: number; data: UsageData }>();
const USAGE_TTL = 5 * 60 * 1000;

export async function getUsage(days: number = 30): Promise<UsageData | null> {
  const hit = _usageCache.get(days);
  if (hit && Date.now() - hit.ts < USAGE_TTL) return hit.data;
  const res = await api(`/api/admin/usage?days=${days}`);
  if (res.ok) {
    const data: UsageData = await res.json();
    _usageCache.set(days, { ts: Date.now(), data });
    return data;
  }
  return null;
}

// --- Budgets ---

export interface BudgetItem {
  id: string;
  user_id: string | null;
  user_name: string | null;
  period: string;
  limit_usd: number;
}

export async function getBudgets(): Promise<BudgetItem[]> {
  const res = await api('/api/admin/budgets');
  if (res.ok) return res.json();
  return [];
}

export async function upsertBudget(data: { user_id?: string | null; period: string; limit_usd: number }): Promise<boolean> {
  const res = await api('/api/admin/budgets', { method: 'PUT', body: JSON.stringify(data) });
  return res.ok;
}

export async function deleteBudget(budgetId: string): Promise<boolean> {
  const res = await api(`/api/admin/budgets/${budgetId}`, { method: 'DELETE' });
  return res.ok;
}

// --- Models ---

export async function getModels(): Promise<{ id: string; name: string; provider: string; context_length: number; pricing: { prompt: string; completion: string } }[]> {
  const res = await api('/api/models');
  if (res.ok) {
    const data = await res.json();
    return data.models ?? [];
  }
  return [];
}

// --- Skills ---

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string | null;
  type: string;
  enabled: boolean;
  is_builtin: boolean;
  is_internal: boolean;
  prompt_instructions: string;
  data_schema: Record<string, unknown> | null;
  template_html: string | null;
  template_css: string | null;
  api_config: Record<string, unknown> | null;
  created_at: string | null;
}

export interface SkillUpsertData {
  id?: string;
  name: string;
  description: string;
  category?: string;
  icon?: string | null;
  type?: string;
  enabled?: boolean;
  prompt_instructions?: string;
  data_schema?: Record<string, unknown> | null;
  template_html?: string | null;
  template_css?: string | null;
  api_config?: Record<string, unknown> | null;
}

export async function getSkills(): Promise<SkillInfo[]> {
  const res = await api('/api/skills');
  if (res.ok) return res.json();
  return [];
}

export async function createSkill(data: SkillUpsertData & { id: string }): Promise<boolean> {
  const res = await api('/api/skills', {
    method: 'POST',
    body: JSON.stringify(data),
  });
  return res.ok;
}

export async function updateSkill(id: string, data: Partial<SkillUpsertData>): Promise<boolean> {
  const res = await api(`/api/skills/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
  return res.ok;
}

export async function deleteSkill(id: string): Promise<boolean> {
  const res = await api(`/api/skills/${id}`, { method: 'DELETE' });
  return res.ok;
}

export async function getAdminModels(): Promise<{ id: string; name: string; provider?: string; context_length?: number }[]> {
  const res = await api('/api/admin/models');
  if (res.ok) {
    const data = await res.json();
    return data.models ?? [];
  }
  return [];
}
