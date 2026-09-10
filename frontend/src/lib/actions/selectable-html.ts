/** Keep the selected DOM nodes alive while a streamed Markdown block changes. */
export function hasSelectionWithin(node: Node): boolean {
  const selection = node.ownerDocument?.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) return false;
  return selection.getRangeAt(0).intersectsNode(node);
}

/** Accept only HTML produced by the application's Markdown renderer. */
export function selectableHtml(node: HTMLElement, initialHtml: string) {
  let pending = initialHtml;
  let rendered: string | undefined;
  function flush() {
    if (pending === rendered || hasSelectionWithin(node)) return;
    node.innerHTML = pending;
    rendered = pending;
  }
  async function copyCode(event: MouseEvent) {
    const button = (event.target as Element).closest<HTMLButtonElement>('[data-copy-code]');
    if (!button || !node.contains(button)) return;
    const code = button.closest('.code-block')?.querySelector('code');
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code.textContent ?? '');
      button.textContent = 'Copied';
    } catch {
      button.textContent = 'Copy failed';
    }
  }
  node.addEventListener('click', copyCode);
  flush();
  node.ownerDocument.addEventListener('selectionchange', flush);
  return {
    update(html: string) { pending = html; flush(); },
    destroy() {
      node.ownerDocument.removeEventListener('selectionchange', flush);
      node.removeEventListener('click', copyCode);
    },
  };
}
