import type { ChatInfo, MessageInfo } from '$lib/stores/chat';

function download(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function exportAsJSON(chat: ChatInfo, messages: MessageInfo[]): void {
  const data = {
    id: chat.id,
    title: chat.title,
    model: chat.model,
    created_at: chat.created_at,
    updated_at: chat.updated_at,
    messages: messages.map((m) => ({
      role: m.role,
      content: m.content,
      model: m.model,
      created_at: m.created_at,
    })),
  };
  const filename = `${chat.title.replace(/[^a-zA-Z0-9]/g, '_').slice(0, 50)}.json`;
  download(filename, JSON.stringify(data, null, 2), 'application/json');
}

export function exportAsMarkdown(chat: ChatInfo, messages: MessageInfo[]): void {
  let md = `# ${chat.title}\n\n`;
  for (const m of messages) {
    const label = m.role === 'user' ? '**User**' : `**Assistant** (${m.model || 'unknown'})`;
    md += `### ${label}\n\n${m.content}\n\n---\n\n`;
  }
  const filename = `${chat.title.replace(/[^a-zA-Z0-9]/g, '_').slice(0, 50)}.md`;
  download(filename, md, 'text/markdown');
}
