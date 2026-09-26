/** The Unicode White_Space set used by the other maintained tutorial capsules. */
export function whitespace(value: string): boolean {
  return /^[\u0009-\u000D\u0020\u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]$/u.test(value);
}
export function trim(value: string): string {
  const scalars = [...value];
  let start = 0, end = scalars.length;
  while (start < end && whitespace(scalars[start]!)) start++;
  while (end > start && whitespace(scalars[end - 1]!)) end--;
  return scalars.slice(start, end).join('');
}
export function utf8Length(value: string): number {
  let bytes = 0;
  for (const scalar of value) {
    const code = scalar.codePointAt(0)!;
    if (code >= 0xD800 && code <= 0xDFFF) throw new TypeError('unpaired UTF-16 surrogate');
    bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
  }
  return bytes;
}
