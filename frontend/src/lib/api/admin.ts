import { api, apiJson, apiOk } from '$lib/api/client';

export interface SettingsPayload {
  openrouter_api_key?: string;
  ollama_url?: string;
  system_prompt?: string;
  model_whitelist?: string[];
  model_aliases?: Record<string, string>;
  rag_enabled?: boolean;
  embedding_provider?: string;
  embedding_model?: string;
  rag_chunk_size?: number;
  rag_chunk_overlap?: number;
  rag_top_k?: number;
  search_enabled?: boolean;
  research_enabled?: boolean;
  search_model?: string;
  research_model?: string;
  title_model?: string;
  default_model?: string | null;
}

export interface SettingsResponse extends SettingsPayload {
  openrouter_api_key_set: boolean;
  openrouter_key_info: Record<string, unknown> | null;
}

export const getSettings = (): Promise<SettingsResponse> =>
  apiJson('/api/admin/settings', { openrouter_api_key_set: false, openrouter_key_info: null });

export const updateSettings = (data: SettingsPayload): Promise<boolean> =>
  apiOk('/api/admin/settings', 'PUT', data);

export interface AdminUser {
  id: string;
  email: string;
  username: string;
  name: string;
  role: string;
  is_active: boolean;
  last_active_at: string | null;
}

export const getUsers = (): Promise<AdminUser[]> => apiJson('/api/admin/users', []);

export const updateUserRole = (userId: string, role: string) =>
  apiOk(`/api/admin/users/${userId}/role`, 'PATCH', { role });

export const updateUserStatus = (userId: string, isActive: boolean) =>
  apiOk(`/api/admin/users/${userId}/status`, 'PATCH', { is_active: isActive });

export const deleteUser = (userId: string) =>
  apiOk(`/api/admin/users/${userId}`, 'DELETE');

export const changeUserPassword = (userId: string, password: string) =>
  apiOk(`/api/admin/users/${userId}/password`, 'PATCH', { password });

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
  if (!res.ok) return null;
  const data: UsageData = await res.json();
  _usageCache.set(days, { ts: Date.now(), data });
  return data;
}

// --- Budgets ---

export interface BudgetItem {
  id: string;
  user_id: string | null;
  user_name: string | null;
  period: string;
  limit_usd: number;
}

export const getBudgets = (): Promise<BudgetItem[]> => apiJson('/api/admin/budgets', []);

export const upsertBudget = (data: { user_id?: string | null; period: string; limit_usd: number }) =>
  apiOk('/api/admin/budgets', 'PUT', data);

export const deleteBudget = (budgetId: string) =>
  apiOk(`/api/admin/budgets/${budgetId}`, 'DELETE');

// --- Models ---

export interface ModelInfo {
  id: string;
  name: string;
  provider?: string;
  context_length?: number;
  pricing?: { prompt: string; completion: string };
}

export async function getModels(): Promise<ModelInfo[]> {
  const data = await apiJson<{ models?: ModelInfo[] }>('/api/models', {});
  return data.models ?? [];
}

export async function getAdminModels(): Promise<ModelInfo[]> {
  const data = await apiJson<{ models?: ModelInfo[] }>('/api/admin/models', {});
  return data.models ?? [];
}

// --- Skills ---

export interface SkillSettingField {
  key: string;
  label: string;
  type: 'text' | 'password' | 'number' | 'boolean' | 'select';
  default?: unknown;
  options?: string[];
  help?: string;
}

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
  settings_schema: SkillSettingField[] | null;
  settings: Record<string, unknown> | null;
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
  settings_schema?: SkillSettingField[] | null;
  settings?: Record<string, unknown> | null;
}

export const getSkills = (): Promise<SkillInfo[]> => apiJson('/api/skills', []);

export const createSkill = (data: SkillUpsertData & { id: string }) =>
  apiOk('/api/skills', 'POST', data);

export const updateSkill = (id: string, data: Partial<SkillUpsertData>) =>
  apiOk(`/api/skills/${id}`, 'PUT', data);

export const deleteSkill = (id: string) =>
  apiOk(`/api/skills/${id}`, 'DELETE');

export async function generateSkillDraft(prompt: string, model?: string): Promise<SkillInfo | null> {
  const res = await api('/api/skills/generate', {
    method: 'POST',
    body: JSON.stringify({ prompt, model }),
  });
  if (!res.ok) return null;
  const data = await res.json();
  return (data && data.draft) || null;
}
