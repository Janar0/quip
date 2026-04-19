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

const CACHE_KEY = 'cached_models_v3';

interface ModelsCache {
  models: ModelItem[];
  default_model: string | null;
  etag: string | null;
}

function loadCached(): ModelsCache {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (raw) return JSON.parse(raw) as ModelsCache;
  } catch { /* ignore */ }
  return { models: [], default_model: null, etag: null };
}

function saveCached(c: ModelsCache): void {
  try { localStorage.setItem(CACHE_KEY, JSON.stringify(c)); }
  catch { /* quota exceeded */ }
}

const _cached = loadCached();
export const modelList = writable<ModelItem[]>(_cached.models);
export const adminDefaultModel = writable<string | null>(_cached.default_model);
export const modelsLoaded = writable<boolean>(_cached.models.length > 0);

/**
 * Revalidate against the server using ETag. If cache exists, send its ETag as
 * `If-None-Match`; server replies 304 when unchanged (few bytes over the wire)
 * or 200 with the fresh payload + new ETag when the list has actually changed.
 */
export async function fetchModels(): Promise<ModelItem[]> {
  const cached = loadCached();
  const headers: Record<string, string> = {};
  if (cached.etag) headers['If-None-Match'] = `"${cached.etag}"`;

  const res = await api('/api/models', { headers });

  if (res.status === 304) {
    // Cache still fresh — ensure stores reflect it (first-load case already has it).
    modelList.set(cached.models);
    adminDefaultModel.set(cached.default_model);
    modelsLoaded.set(true);
    return cached.models;
  }

  if (res.ok) {
    const data = await res.json();
    const models: ModelItem[] = data.models ?? [];
    const defaultModel: string | null = data.default_model ?? null;
    const etag = (res.headers.get('ETag') ?? '').replace(/^"|"$/g, '') || null;
    modelList.set(models);
    adminDefaultModel.set(defaultModel);
    modelsLoaded.set(true);
    saveCached({ models, default_model: defaultModel, etag });
    return models;
  }

  return get(modelList);
}
