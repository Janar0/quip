/**
 * Client-side artifact parser — mirrors backend logic for real-time streaming.
 */

export interface ParsedArtifact {
  identifier: string;
  type: string;
  title: string;
  language?: string;
  content: string;
  isComplete: boolean;
}

const ATTR_RE = /(\w+)="([^"]*)"/g;
const TAG_RE = /<artifact\s+([^>]*)>([\s\S]*?)<\/artifact>/g;
const OPEN_TAG_RE = /<artifact\s+([^>]*)>([\s\S]*)$/;

function parseAttrs(str: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  let m: RegExpExecArray | null;
  const re = new RegExp(ATTR_RE.source, 'g');
  while ((m = re.exec(str))) attrs[m[1]] = m[2];
  return attrs;
}

/** Extract completed and in-progress artifact tags from streaming content. */
export function extractStreamingArtifacts(content: string): ParsedArtifact[] {
  const artifacts: ParsedArtifact[] = [];

  // Find all complete tags
  let m: RegExpExecArray | null;
  const completeRe = new RegExp(TAG_RE.source, 'g');
  let lastCompleteEnd = 0;
  while ((m = completeRe.exec(content))) {
    const attrs = parseAttrs(m[1]);
    artifacts.push({
      identifier: attrs.identifier ?? '',
      type: attrs.type ?? 'code',
      title: attrs.title ?? 'Artifact',
      language: attrs.language,
      content: m[2].trim(),
      isComplete: true,
    });
    lastCompleteEnd = completeRe.lastIndex;
  }

  // Check for a trailing open tag (not yet closed — still streaming)
  const remainder = content.slice(lastCompleteEnd);
  const openMatch = OPEN_TAG_RE.exec(remainder);
  if (openMatch) {
    const attrs = parseAttrs(openMatch[1]);
    artifacts.push({
      identifier: attrs.identifier ?? '',
      type: attrs.type ?? 'code',
      title: attrs.title ?? 'Artifact',
      language: attrs.language,
      content: openMatch[2].trim(),
      isComplete: false,
    });
  }

  return artifacts;
}

/** Strip artifact tags from content for prose/markdown rendering. */
export function stripArtifactTags(content: string): string {
  // Remove complete tags
  let cleaned = content.replace(new RegExp(TAG_RE.source, 'g'), '');
  // Remove trailing open tag
  cleaned = cleaned.replace(OPEN_TAG_RE, '');
  // Collapse excessive blank lines
  cleaned = cleaned.replace(/\n{3,}/g, '\n\n');
  return cleaned.trim();
}
