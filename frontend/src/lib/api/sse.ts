/** Decode SSE independently of network chunk boundaries and UTF-8 characters. */
export async function* readSSE(response: Response): AsyncGenerator<{ event: string; data: string }> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('The server returned an empty response stream.');
  const decoder = new TextDecoder();
  let buffer = '';
  let event = '';
  let data: string[] = [];

  function consume(line: string) {
    if (line === '') {
      const message = data.length ? { event: event || 'message', data: data.join('\n') } : null;
      event = '';
      data = [];
      return message;
    }
    if (line.startsWith(':')) return null;
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
    if (field === 'event') event = value;
    if (field === 'data') data.push(value);
    return null;
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      // CRLF may itself be split across network chunks.
      let match: RegExpExecArray | null;
      while ((match = /\r\n|\r|\n/.exec(buffer))) {
        if (!done && match[0] === '\r' && match.index === buffer.length - 1) break;
        const line = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const message = consume(line);
        if (message) yield message;
      }
      if (done) break;
    }
    // A disconnected server may omit the final blank line.
    if (buffer) consume(buffer);
    const last = consume('');
    if (last) yield last;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
