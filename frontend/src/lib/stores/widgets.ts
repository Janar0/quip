import { writable } from 'svelte/store';
import { api } from '$lib/api/client';

export interface WidgetTemplate {
  id: string;
  name: string;
  template_html: string;
  template_css: string;
}

export const widgetTemplates = writable<Record<string, WidgetTemplate>>({});
export const widgetTemplatesLoaded = writable(false);

export async function loadWidgetTemplates(): Promise<void> {
  try {
    const res = await api('/api/skills/templates');
    if (res.ok) {
      const templates: WidgetTemplate[] = await res.json();
      const map: Record<string, WidgetTemplate> = {};
      for (const t of templates) {
        map[t.id] = t;
      }
      widgetTemplates.set(map);
      widgetTemplatesLoaded.set(true);
    }
  } catch {
    // silent fail — widgets just won't render if server unavailable
  }
}
