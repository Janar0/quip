import { writable, get } from 'svelte/store';
import { api } from '$lib/api/client';

export interface ModelItem {
  id: string;
  name: string;
  display_name?: string;
  provider: string;
  context_length: number;
  pricing: { prompt: string; completion: string };
}

const CACHE_KEY = 'cached_models_v2';
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

interface ModelsCache {
  models: ModelItem[];
  default_model: string | null;
  ts: number;
}

function loadCached(): ModelsCache {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return { models: [], default_model: null, ts: 0 };
    const parsed: ModelsCache = JSON.parse(raw);
    if (Date.now() - parsed.ts < CACHE_TTL) return parsed;
  } catch { /* ignore */ }
  return { models: [], default_model: null, ts: 0 };
}

const _cached = loadCached();
export const modelList = writable<ModelItem[]>(_cached.models);
export const adminDefaultModel = writable<string | null>(_cached.default_model);
// If fresh cache exists, mark loaded immediately — no spinner on repeat visits
export const modelsLoaded = writable<boolean>(_cached.models.length > 0);

async function _doFetch(): Promise<ModelItem[]> {
  const res = await api('/api/models');
  if (res.ok) {
    const data = await res.json();
    const models: ModelItem[] = data.models ?? [];
    const defaultModel: string | null = data.default_model ?? null;
    modelList.set(models);
    adminDefaultModel.set(defaultModel);
    modelsLoaded.set(true);
    try {
      const cache: ModelsCache = { models, default_model: defaultModel, ts: Date.now() };
      localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
    } catch { /* quota exceeded */ }
    return models;
  }
  return get(modelList);
}

export async function fetchModels(): Promise<ModelItem[]> {
  const cached = loadCached();
  if (cached.models.length > 0) {
    return cached.models; // Cache fresh — no API call needed
  }
  return _doFetch(); // Cache miss or expired — fetch and wait
}
