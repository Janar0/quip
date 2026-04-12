/**
 * Thread builder — converts flat messages with parent_id into a linear thread,
 * handling sibling branches from regeneration.
 *
 * Tree structure: each message can have multiple children (siblings).
 * The "thread" is the selected path through the tree.
 */
import type { MessageInfo } from '$lib/stores/chat';

export interface ThreadMessage extends MessageInfo {
  /** 1-based index among siblings */
  siblingIndex: number;
  /** total siblings at this branch point */
  siblingCount: number;
  /** IDs of all siblings (including self) in creation order */
  siblingIds: string[];
}

/**
 * Build a linear thread from flat messages.
 * @param messages - all messages in the chat (flat, from API)
 * @param selections - map of parent_id → selected child id (branch choices)
 * @returns ordered thread for display
 */
export function buildThread(
  messages: MessageInfo[],
  selections: Record<string, string>,
): ThreadMessage[] {
  if (messages.length === 0) return [];

  // Group children by parent_id
  const childrenOf = new Map<string, MessageInfo[]>();
  const roots: MessageInfo[] = [];

  for (const msg of messages) {
    const pid = msg.parent_id ?? '__root__';
    if (pid === '__root__' || !msg.parent_id) {
      roots.push(msg);
    } else {
      const siblings = childrenOf.get(pid) ?? [];
      siblings.push(msg);
      childrenOf.set(pid, siblings);
    }
  }

  // Sort each sibling group by created_at
  for (const [, siblings] of childrenOf) {
    siblings.sort((a, b) => a.created_at.localeCompare(b.created_at));
  }
  roots.sort((a, b) => a.created_at.localeCompare(b.created_at));

  // If no parent_ids exist (legacy chat), return flat list
  const hasTree = messages.some((m) => m.parent_id);
  if (!hasTree) {
    return messages.map((m) => ({
      ...m,
      siblingIndex: 1,
      siblingCount: 1,
      siblingIds: [m.id],
    }));
  }

  // Walk the tree following selections (or defaulting to latest sibling)
  const thread: ThreadMessage[] = [];

  // Start with roots — group them as siblings
  if (roots.length > 0) {
    const selectedRoot = selections['__root__']
      ? roots.find((r) => r.id === selections['__root__'])
      : roots[roots.length - 1];
    const root = selectedRoot ?? roots[roots.length - 1];
    const rootIds = roots.map((r) => r.id);

    thread.push({
      ...root,
      siblingIndex: rootIds.indexOf(root.id) + 1,
      siblingCount: roots.length,
      siblingIds: rootIds,
    });

    // Follow the chain from the selected root
    walkChain(root.id);
  }

  function walkChain(parentId: string) {
    const children = childrenOf.get(parentId);
    if (!children || children.length === 0) return;

    // Pick selected child or default to latest
    const selectedId = selections[parentId];
    const selected = selectedId
      ? children.find((c) => c.id === selectedId) ?? children[children.length - 1]
      : children[children.length - 1];

    const siblingIds = children.map((c) => c.id);

    thread.push({
      ...selected,
      siblingIndex: siblingIds.indexOf(selected.id) + 1,
      siblingCount: children.length,
      siblingIds,
    });

    // Continue down the chain
    walkChain(selected.id);
  }

  return thread;
}
