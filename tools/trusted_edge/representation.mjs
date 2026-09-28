import {createHash} from 'node:crypto';
import {gzip} from 'node:zlib';
import {requireEdge, LIMITS} from './config.mjs';

// These parsers have a separate work bound below the HTTP header byte limit.
export function encoding(value) {
  if (value === undefined || value.trim() === '') return 'identity';
  requireEdge(typeof value === 'string' && value.length <= 512, 'edge-encoding-bound');
  const parts = value.split(',');
  requireEdge(parts.length <= 16, 'edge-encoding-count');
  const values = new Map();
  for (const part of parts) {
    const match = /^\s*([!#$%&'*+.^_`|~0-9a-z-]+)(?:\s*;\s*q=(0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?))?\s*$/i.exec(part);
    requireEdge(match !== null, 'edge-encoding-syntax');
    const name = match[1].toLowerCase();
    requireEdge(!values.has(name), 'edge-encoding-duplicate');
    values.set(name, Math.round(Number(match[2] ?? '1') * 1000));
  }
  const identity = values.get('identity') ?? (values.get('*') === 0 ? 0 : 1000);
  const compressed = values.get('gzip') ?? values.get('*') ?? 0;
  if (compressed > 0 && compressed >= identity) return 'gzip';
  return identity > 0 ? 'identity' : null;
}

export function tags(value) {
  if (value === undefined) return null;
  requireEdge(typeof value === 'string' && value.length <= 2048, 'edge-validator-bound');
  if (value.trim() === '*') return '*';
  // Opaque entity tags can contain commas. Consume quoted tokens before lists.
  const result = []; let remaining = value.trim();
  while (remaining) {
    const match = /^(W\/)?("[!#-~]{0,128}")(?=\s*(?:,|$))/.exec(remaining);
    requireEdge(match !== null && result.length < 16, 'edge-validator-syntax-or-count');
    result.push({weak: Boolean(match[1]), tag: match[2]});
    remaining = remaining.slice(match[0].length).trim();
    if (remaining) {
      requireEdge(remaining.startsWith(',') && remaining.slice(1).trim() !== '', 'edge-validator-separator');
      remaining = remaining.slice(1).trim();
    }
  }
  requireEdge(result.length > 0, 'edge-validator-empty');
  return result;
}

export function conditions(headers) {
  requireEdge(!['range', 'if-range', 'if-modified-since', 'if-unmodified-since'].some(name => name in headers),
    'edge-unsupported-range-or-date-condition');
  return {match: tags(headers['if-match']), none: tags(headers['if-none-match'])};
}

export function conditionalCode(selected, condition) {
  if (condition.match !== null && condition.match !== '*'
      && !condition.match.some(value => !value.weak && value.tag === selected)) return 412;
  if (condition.none === '*' || condition.none?.some(value => value.tag === selected)) return 304;
  return 200;
}

export function vary(headers) {
  const tokens = (headers.vary ?? '').split(',').map(value => value.trim()).filter(Boolean);
  if (!tokens.some(value => value.toLowerCase() === 'accept-encoding') && !tokens.includes('*')) tokens.push('Accept-Encoding');
  return {...headers, vary: tokens.join(', ')};
}

export async function transform(body, media) {
  requireEdge(body.length <= LIMITS.responseBytes && typeof media === 'string' && media.length <= 256, 'edge-transform-bound');
  // Four admitted exchanges at most; one job each, no retry. Cancellation keeps
  // its exchange occupied until the accepted zlib callback has actually settled.
  const bytes = await new Promise((resolve, reject) => gzip(body,
    {level: 6, maxOutputLength: LIMITS.responseBytes + 65536}, (error, value) => error ? reject(error) : resolve(value)));
  const digest = createHash('sha256').update('latent.edge.gzip.v1\0').update(media).update('\0').update(bytes).digest('hex');
  return {bytes, etag: '"edge-gzip-sha256-' + digest + '"'};
}
