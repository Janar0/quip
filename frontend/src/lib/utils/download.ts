/** Download content as a file. */
export function downloadFile(filename: string, content: string, mime = 'text/plain'): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const EXT_MAP: Record<string, string> = {
  html: '.html',
  svg: '.svg',
  mermaid: '.mmd',
  python: '.py',
  javascript: '.js',
  typescript: '.ts',
  rust: '.rs',
  go: '.go',
  java: '.java',
  cpp: '.cpp',
  c: '.c',
  css: '.css',
  json: '.json',
  yaml: '.yaml',
  sql: '.sql',
  shell: '.sh',
  bash: '.sh',
  markdown: '.md',
};

export function getExtension(language?: string): string {
  if (!language) return '.txt';
  return EXT_MAP[language.toLowerCase()] ?? `.${language.toLowerCase()}`;
}
