export function publicRequestPath(raw, origin) {
  if (typeof raw !== 'string' || raw.length > 8192) return 'unmapped';
  try {
    const url = new URL(raw), expected = new URL(origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.origin !== expected.origin) return 'unmapped';
    // Inspect the original spelling before URL normalization can remove traversal.
    const match = /^https?:\/\/[^/?#\\]+(\/[^?#\\]*)?(?:[?#][^\r\n]*)?$/i.exec(raw);
    if (!match) return 'unmapped';
    const path = (match[1] || '/').slice(1), parts = path.split('/');
    if (path.length > 256 || !/^[A-Za-z0-9_~./-]*$/.test(path)
      || parts.some((part, index) => part.startsWith('.') || (!part && index < parts.length - 1))) return 'unmapped';
    return path;
  } catch {
    return 'unmapped';
  }
}
