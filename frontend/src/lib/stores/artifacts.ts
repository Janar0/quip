import { writable, derived } from 'svelte/store';
import { messages } from './chat';
import type { Artifact } from './chat';

export const selectedArtifactId = writable<string | null>(null);
export const artifactPanelOpen = writable<boolean>(false);

export const allArtifacts = derived(messages, ($msgs) => {
  const all: Artifact[] = [];
  for (const msg of $msgs) {
    if (msg.artifacts) all.push(...msg.artifacts);
  }
  return all;
});

export const artifactVersions = derived(allArtifacts, ($all) => {
  const chains = new Map<string, Artifact[]>();
  for (const a of $all) {
    const chain = chains.get(a.identifier);
    if (chain) chain.push(a);
    else chains.set(a.identifier, [a]);
  }
  for (const chain of chains.values()) {
    chain.sort((a, b) => a.version - b.version);
  }
  return chains;
});

export function selectArtifact(id: string) {
  selectedArtifactId.set(id);
  artifactPanelOpen.set(true);
}

export function closeArtifactPanel() {
  artifactPanelOpen.set(false);
}
