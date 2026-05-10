import { describe, it, expect } from 'vitest';
import { buildThread } from './thread.ts';
import type { MessageInfo } from '../stores/chat.ts';

function msg(id: string, parent_id?: string | null, role: MessageInfo['role'] = 'user'): MessageInfo {
  return {
    id,
    chat_id: 'chat-1',
    parent_id: parent_id ?? null,
    role,
    content: `msg-${id}`,
    created_at: new Date().toISOString(),
  };
}

describe('buildThread', () => {
  it('returns flat list for messages without parent_id', () => {
    const messages = [msg('a'), msg('b'), msg('c')];
    const thread = buildThread(messages, {});
    expect(thread).toHaveLength(3);
    expect(thread[0].branchDepth).toBe(0);
  });

  it('follows parent chain', () => {
    const messages = [
      msg('root', null),
      msg('child', 'root', 'assistant'),
      msg('grandchild', 'child'),
    ];
    const thread = buildThread(messages, {});
    expect(thread).toHaveLength(3);
    expect(thread.map((m) => m.id)).toEqual(['root', 'child', 'grandchild']);
  });

  it('picks selected sibling from branchSelections', () => {
    const messages = [
      msg('root', null),
      msg('branch1', 'root'),
      msg('branch2', 'root'),
    ];
    const thread = buildThread(messages, { root: 'branch1' });
    expect(thread).toHaveLength(2);
    expect(thread[1].id).toBe('branch1');
    expect(thread[1].siblingIndex).toBe(1);
    expect(thread[1].siblingCount).toBe(2);
  });

  it('computes branchDepth correctly', () => {
    const messages = [
      msg('root', null),
      msg('b1', 'root'),
      msg('b2', 'root'),
      msg('child', 'b2'),
    ];
    const thread = buildThread(messages, { root: 'b2' });
    expect(thread[2].branchDepth).toBe(1); // child of a branch
  });

  it('defaults to latest sibling when no selection', () => {
    const messages = [
      msg('root', null),
      msg('older', 'root'),
      msg('newer', 'root'),
    ];
    const thread = buildThread(messages, {});
    expect(thread[1].id).toBe('newer');
  });

  it('handles empty messages', () => {
    expect(buildThread([], {})).toEqual([]);
  });
});
