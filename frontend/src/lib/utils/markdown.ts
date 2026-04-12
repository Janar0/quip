import { Marked } from 'marked';
import { writable } from 'svelte/store';

const marked = new Marked({
  breaks: true,
  gfm: true,
});

const renderer = new marked.Renderer();

// chatId used by the link renderer to resolve sandbox:/ URLs; set before each parse call
let _chatId = '';

// Lazy-loaded heavy libs — start fetching immediately but don't block initial render
let _hljs: any = null;
let _katex: any = null;

export const hljsLoaded = writable(false);
export const katexLoaded = writable(false);

if (typeof window !== 'undefined') {
  // Defer past first render so these chunks are off the initial critical path
  setTimeout(() => {
    import('highlight.js').then(m => { _hljs = m.default; hljsLoaded.set(true); });
    import('katex').then(m => { _katex = m.default; katexLoaded.set(true); });
  }, 0);
}

export function getHljs() { return _hljs; }

// Escape raw HTML tokens — prevents <style>/<script> injection from model output
// (html:false is broken in marked v17, so we override the renderer directly)
renderer.html = function ({ text }: { text: string }) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
};

// Intercept sandbox:/ links and turn them into real API download URLs
renderer.link = function ({ href, text }: { href: string; title?: string | null; text: string }) {
  if (href?.startsWith('sandbox:/')) {
    const filename = href.slice('sandbox:/'.length).replace(/^\/+/, '');
    const token = typeof localStorage !== 'undefined' ? (localStorage.getItem('access_token') ?? '') : '';
    const url = `/api/sandbox/${_chatId}/file/${encodeURIComponent(filename)}?token=${encodeURIComponent(token)}`;
    return `<a href="${url}" target="_blank" rel="noopener" class="prose-link">${text}</a>`;
  }
  const safe = href ? href.replace(/"/g, '&quot;') : '';
  return `<a href="${safe}" target="_blank" rel="noopener">${text}</a>`;
};

// Code blocks with syntax highlighting + copy button
renderer.code = function ({ text, lang }: { text: string; lang?: string }) {
  const escaped = lang ? lang.replace(/"/g, '&quot;') : '';
  const copyBtn = `<button class="copy-btn opacity-0 group-hover:opacity-100 transition-opacity" onclick="navigator.clipboard.writeText(this.closest('.code-block').querySelector('code').textContent)">copy</button>`;
  if (_hljs) {
    const language = lang && _hljs.getLanguage(lang) ? lang : 'plaintext';
    const highlighted = _hljs.highlight(text, { language }).value;
    return `<div class="code-block group relative">
    <div class="code-header flex items-center justify-between px-3 py-1 text-xs opacity-50">
      <span>${escaped}</span>
      ${copyBtn}
    </div>
    <pre><code class="hljs language-${language}">${highlighted}</code></pre>
  </div>`;
  }
  // hljs not loaded yet — plain text fallback (re-render triggered once loaded)
  const safe = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return `<div class="code-block group relative">
    <div class="code-header flex items-center justify-between px-3 py-1 text-xs opacity-50">
      <span>${escaped}</span>
      ${copyBtn}
    </div>
    <pre><code>${safe}</code></pre>
  </div>`;
};

// Inline code
renderer.codespan = function ({ text }: { text: string }) {
  return `<code class="inline-code">${text}</code>`;
};

marked.setOptions({ renderer });

/** Render KaTeX math expressions */
function renderMath(text: string): string {
  if (!_katex) return text; // katex not loaded yet — re-render triggered once loaded

  // Block math: $$...$$ or \[...\]
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
    try {
      return _katex.renderToString(math.trim(), { displayMode: true, throwOnError: false });
    } catch {
      return `$$${math}$$`;
    }
  });
  text = text.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => {
    try {
      return _katex.renderToString(math.trim(), { displayMode: true, throwOnError: false });
    } catch {
      return `\\[${math}\\]`;
    }
  });

  // Inline math: $...$ (not $$) or \(...\)
  text = text.replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => {
    try {
      return _katex.renderToString(math.trim(), { displayMode: false, throwOnError: false });
    } catch {
      return `\\(${math}\\)`;
    }
  });
  // $...$ — careful not to match $$ or currency like $100
  text = text.replace(/(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)/g, (_, math) => {
    // Skip if it looks like currency ($100, $5.00)
    if (/^\d/.test(math.trim())) return `$${math}$`;
    try {
      return _katex.renderToString(math.trim(), { displayMode: false, throwOnError: false });
    } catch {
      return `$${math}$`;
    }
  });

  return text;
}

/** Render raw LaTeX commands outside of $ delimiters (e.g. \frac{a}{b}) */
function renderBareLaTeX(text: string): string {
  if (!_katex) return text; // katex not loaded yet

  // Match common LaTeX commands not already inside KaTeX spans
  // Only process if there are bare LaTeX commands
  if (!text.includes('\\frac') && !text.includes('\\dfrac') && !text.includes('\\sqrt') &&
      !text.includes('\\times') && !text.includes('\\div') && !text.includes('\\sum') &&
      !text.includes('\\int') && !text.includes('\\alpha') && !text.includes('\\beta') &&
      !text.includes('\\pi') && !text.includes('\\infty')) {
    return text;
  }

  // Don't process inside existing katex spans or code blocks
  const parts: string[] = [];
  const protectedPattern = /(<span class="katex.*?<\/span>|<code[\s\S]*?<\/code>|<pre[\s\S]*?<\/pre>)/g;
  let lastIndex = 0;

  for (const match of text.matchAll(protectedPattern)) {
    if (match.index! > lastIndex) {
      parts.push(processBareLaTeX(text.slice(lastIndex, match.index)));
    }
    parts.push(match[0]); // Keep protected content as-is
    lastIndex = match.index! + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(processBareLaTeX(text.slice(lastIndex)));
  }

  return parts.join('');
}

function processBareLaTeX(text: string): string {
  // Match LaTeX expressions like \frac{a}{b}, \times, \sqrt{x}, etc.
  return text.replace(
    /(?:\\(?:d?frac|sqrt|sum|prod|int|lim|log|ln|sin|cos|tan)\{[^}]*\}(?:\{[^}]*\})?|\\(?:times|div|pm|mp|cdot|ldots|cdots|leq|geq|neq|approx|equiv|alpha|beta|gamma|delta|epsilon|theta|lambda|mu|pi|sigma|phi|omega|infty|partial|nabla))/g,
    (match) => {
      try {
        return _katex.renderToString(match, { displayMode: false, throwOnError: false });
      } catch {
        return match;
      }
    },
  );
}

function isSafeUrl(url: string): boolean {
  try {
    const u = new URL(url);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/** Primary source info — one authoritative link pinned at the top of a search answer. */
export interface PrimarySourceInfo {
  title: string;
  url: string;
  summary: string;
}

/** Where the model placed search-result images in its answer. */
export type ImageMode = 'top' | 'inline' | 'none';

/** Extracts a leading `> **Primary source:** [Title](URL) — summary` blockquote
 *  from a search answer. Returns the parsed info + the content with the line stripped.
 *  Matches both English and Russian labels. Streaming-safe: only matches complete lines. */
const PRIMARY_SOURCE_RE = /^(?:>\s*)?(?:\*\*)?(?:Primary source|Основной источник|Official link|Официальный сайт)(?:\*\*)?\s*:?\s*\[([^\]]+)\]\(([^)]+)\)(?:\s*[—–:-]\s*(.+))?$/m;

export function extractPrimarySource(text: string): { primarySource: PrimarySourceInfo | null; stripped: string } {
  if (!text) return { primarySource: null, stripped: text };
  const match = text.match(PRIMARY_SOURCE_RE);
  if (!match || match.index === undefined) return { primarySource: null, stripped: text };
  // Skip if the match is inside a fenced code block — avoid XSS via code-fenced markup.
  const fenceStart = text.indexOf('```');
  if (fenceStart >= 0 && match.index > fenceStart) return { primarySource: null, stripped: text };
  const [fullLine, title, url, summary = ''] = match;
  if (!isSafeUrl(url)) return { primarySource: null, stripped: text };
  const stripped = text.replace(fullLine, '').replace(/^\n+/, '');
  return {
    primarySource: { title: title.trim(), url, summary: summary.trim() },
    stripped,
  };
}

interface SearchImageLike {
  img_src: string;
  source_url: string;
  title: string;
}

/** Replace `![](search-image:all)` and `![](search-image:K)` placeholders in
 *  markdown with real image URLs (or the top-grid sentinel). The model emits
 *  these so it — not the frontend — decides whether images go above the answer
 *  or float right of a specific paragraph. */
export function resolveSearchImagePlaceholders(
  text: string,
  searchImages: SearchImageLike[] | undefined,
): { text: string; imageMode: ImageMode } {
  if (!text) return { text, imageMode: 'none' };
  const placeholderAny = /!\[[^\]]*\]\(search-image:(?:all|\d+)\)/;
  if (!placeholderAny.test(text)) return { text, imageMode: 'none' };

  if (!searchImages?.length) {
    // Placeholders exist but image data hasn't arrived yet (or won't) — strip
    // them so we don't render broken image markdown.
    return {
      text: text.replace(/!\[[^\]]*\]\(search-image:(?:all|\d+)\)\n?/g, ''),
      imageMode: 'none',
    };
  }

  // Top grid: first image marker is `search-image:all`.
  if (/!\[[^\]]*\]\(search-image:all\)/.test(text)) {
    return {
      text: text.replace(/!\[[^\]]*\]\(search-image:all\)\n?/g, ''),
      imageMode: 'top',
    };
  }

  // Inline: each `search-image:K` becomes a floating <figure>.
  let mode: ImageMode = 'none';
  const resolved = text.replace(/!\[[^\]]*\]\(search-image:(\d+)\)/g, (_, kStr: string) => {
    const k = parseInt(kStr, 10) - 1;
    const img = searchImages[k];
    if (!img || !isSafeUrl(img.img_src)) return '';
    mode = 'inline';
    const safeAlt = escapeHtml(img.title || '');
    const safeSrc = escapeHtml(img.img_src);
    const safeSource = isSafeUrl(img.source_url) ? escapeHtml(img.source_url) : safeSrc;
    return `<figure class="search-float-right"><a href="${safeSource}" target="_blank" rel="noopener"><img src="${safeSrc}" alt="${safeAlt}" loading="lazy" /></a></figure>`;
  });
  return { text: resolved, imageMode: mode };
}

/** Source info extracted from the Sources section */
export interface SourceInfo {
  num: number;
  title: string;
  url: string;
  domain: string;
}

/** Parse a block of `[N] Title - URL` lines into SourceInfo[]. Unparseable
 *  lines are skipped silently — keeps streaming robust when the URL is still
 *  coming in. */
function parseSourcesBlock(block: string): SourceInfo[] {
  const sources: SourceInfo[] = [];
  for (const line of block.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    let num: number | undefined;
    let title = '';
    let url = '';

    // Format: [N] [Title](URL)
    const mdLink = trimmed.match(/^\[(\d{1,2})\]\s*\[([^\]]+)\]\(([^)]+)\)/);
    if (mdLink) {
      num = parseInt(mdLink[1]);
      title = mdLink[2];
      url = mdLink[3];
    }

    // Format: [N] Title - URL
    if (!num) {
      const dashUrl = trimmed.match(/^\[(\d{1,2})\]\s*(.+?)\s*[-–—]\s*(https?:\/\/\S+)/);
      if (dashUrl) {
        num = parseInt(dashUrl[1]);
        title = dashUrl[2];
        url = dashUrl[3];
      }
    }

    // Format: [N] Title URL (URL at end)
    if (!num) {
      const spaceUrl = trimmed.match(/^\[(\d{1,2})\]\s*(.+?)\s+(https?:\/\/\S+)/);
      if (spaceUrl) {
        num = parseInt(spaceUrl[1]);
        title = spaceUrl[2];
        url = spaceUrl[3];
      }
    }

    if (num && url) {
      let domain = '';
      try {
        domain = new URL(url).hostname.replace(/^www\./, '');
        const parts = domain.split('.');
        if (parts.length > 2) domain = parts.slice(-2).join('.');
      } catch { /* keep empty */ }
      sources.push({ num, title: title.trim(), url, domain });
    }
  }
  return sources;
}

/** Extract sources from markdown content and return cleaned content + source list.
 *
 *  Supports two placements so users get clickable links as early as possible
 *  during streaming:
 *    1. TOP placement (new Perplexity-style prompt): `**Sources:**` block at the
 *       very start of the message, optionally followed by a `---` separator and
 *       then the prose. Extracted as soon as any `[N] Title - URL` line parses.
 *    2. BOTTOM placement (legacy fallback): `\n---\n**Sources:**` footer at end. */
export function extractSources(content: string): { cleanContent: string; sources: SourceInfo[] } {
  if (!content) return { cleanContent: content, sources: [] };

  // TOP placement. Match header + consecutive `[N] ...` lines (no terminator
  // required — works mid-stream before the `---` separator arrives).
  const topPattern = /^\s*\*{0,2}(?:Sources|Источники):?\*{0,2}\s*\n((?:\s*\[\d{1,2}\][^\n]*\n?)+)/i;
  const topMatch = content.match(topPattern);
  if (topMatch && (topMatch.index ?? -1) === 0) {
    const sources = parseSourcesBlock(topMatch[1]);
    if (sources.length > 0) {
      let rest = content.slice(topMatch[0].length);
      // Strip the optional `---` separator + any surrounding blank lines.
      rest = rest.replace(/^\s*---\s*\n?/, '').replace(/^\n+/, '');
      return { cleanContent: rest, sources };
    }
  }

  // BOTTOM placement (legacy). Kept so old messages still render correctly.
  const bottomPattern = /\n---\n\s*\*{0,2}(?:Sources|Источники):?\*{0,2}\s*\n([\s\S]*?)$/i;
  const bottomMatch = content.match(bottomPattern);
  if (!bottomMatch) return { cleanContent: content, sources: [] };

  const cleanContent = content.slice(0, bottomMatch.index!).trimEnd();
  const sources = parseSourcesBlock(bottomMatch[1]);
  return { cleanContent, sources };
}

/** Convert [N] or [N, M, K] citation markers to inline source badges.
 *  Handles both single-source (`[1]`) and multi-source (`[1, 2, 3]`)
 *  citations — a single grouped marker expands into N sequential badges. */
function renderCitations(html: string, sources: SourceInfo[]): string {
  const sourceMap = new Map(sources.map((s) => [s.num, s]));

  const renderOne = (n: number): string => {
    const src = sourceMap.get(n);
    if (!src) return `<sup class="citation">[${n}]</sup>`;
    const escaped = src.title.replace(/"/g, '&quot;');
    return `<a href="${src.url}" target="_blank" rel="noopener" class="source-badge" title="${escaped}"><img src="https://www.google.com/s2/favicons?domain=${src.domain}&amp;sz=32" alt="" /></a>`;
  };

  return html.replace(/\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\](?!\()/g, (_full, numsStr: string) => {
    const nums = numsStr
      .split(',')
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !Number.isNaN(n));
    return nums.map(renderOne).join('');
  });
}

export function renderMarkdown(text: string, sources?: SourceInfo[], chatId?: string): string {
  if (!text) return '';
  _chatId = chatId ?? '';
  // Render math before markdown to protect LaTeX from markdown parsing
  text = renderMath(text);
  let html = marked.parse(text) as string;
  // Catch any bare LaTeX that survived markdown parsing
  html = renderBareLaTeX(html);
  // Style citation markers (with source badges if available)
  html = renderCitations(html, sources ?? []);
  return html;
}
