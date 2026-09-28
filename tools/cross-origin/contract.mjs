// Executable design probe for ADR-0049, not a native ingress implementation.
import assert from 'node:assert/strict';

export const vary = 'Origin, Sec-Fetch-Site, Sec-Fetch-Mode, Sec-Fetch-Dest, Access-Control-Request-Method, Access-Control-Request-Headers';
const conditional = new Set(['if-none-match', 'if-modified-since']);
const destinations = new Set(['empty', 'script', 'style', 'font', 'image', 'manifest']);

export function canonicalOrigin(value) {
  if (typeof value !== 'string' || value.length > 512 || value.includes('*')
      || !/^https:\/\/[!-~]+$/.test(value)) return false;
  try { return new URL(value).origin === value; } catch { return false; }
}

export function configuration(rows) {
  assert.ok(Array.isArray(rows) && rows.length <= 32, 'at most 32 publication grants');
  const keys = new Set();
  for (const row of rows) {
    assert.ok(row && typeof row === 'object' && !Array.isArray(row));
    assert.equal(Object.keys(row).sort().join(','), 'authority,credentials,origins,publication,tenant');
    assert.equal(typeof row.authority, 'string');
    assert.ok(canonicalOrigin('https://' + row.authority));
    assert.match(row.tenant, /^[a-z][a-z0-9-]{0,127}$/);
    assert.match(row.publication, /^publication:sha256:[a-f0-9]{64}$/);
    assert.ok(['omit', 'include'].includes(row.credentials));
    assert.ok(Array.isArray(row.origins) && row.origins.length >= 1 && row.origins.length <= 16);
    assert.equal(new Set(row.origins).size, row.origins.length);
    assert.ok(row.origins.every(canonicalOrigin));
    assert.ok(row.origins.every(origin => origin !== 'https://' + row.authority));
    const key = JSON.stringify([row.authority, row.tenant, row.publication]);
    assert.ok(!keys.has(key), 'one policy per selected publication and authority');
    keys.add(key);
  }
  assert.ok(Buffer.byteLength(JSON.stringify(rows)) <= 65536, 'configuration byte ceiling');
  return structuredClone(rows);
}

export function decide(rows, request) {
  const headers = {'vary': vary, 'cache-control': 'no-store',
    'cross-origin-resource-policy': 'same-origin', 'x-content-type-options': 'nosniff'};
  const deny = () => ({status: 403, headers});
  const h = request.headers, origin = h.origin;
  if (!canonicalOrigin(origin) || h.authorization || h['proxy-authorization']
      || h['transfer-encoding'] !== undefined || (h['content-length'] !== undefined && h['content-length'] !== '0')
      || h['sec-fetch-mode'] !== 'cors' || !['cross-site', 'same-site'].includes(h['sec-fetch-site'])
      || !destinations.has(h['sec-fetch-dest']) || h['sec-fetch-user'] !== undefined) return deny();
  const grant = rows.find(row => row.authority === request.authority && row.tenant === request.tenant
    && row.publication === request.publication && row.origins.includes(origin));
  if (!grant || !request.eligible || request.document || request.application) return deny();
  if (h.cookie && (grant.credentials === 'omit' || typeof h.cookie !== 'string'
      || h.cookie.length > 4096 || h.cookie.split(';').length > 16)) return deny();
  if (request.method === 'OPTIONS') {
    if (!['GET', 'HEAD'].includes(h['access-control-request-method']) || h.cookie
        || h['sec-fetch-dest'] !== 'empty') return deny();
    const raw = h['access-control-request-headers'] ?? '';
    if (typeof raw !== 'string' || raw.length > 64) return deny();
    const names = raw === '' ? [] : raw.split(',').map(name => name.trim());
    if (names.length > 2 || new Set(names).size !== names.length
        || names.some(name => !conditional.has(name))) return deny();
    headers['access-control-allow-methods'] = 'GET, HEAD';
    if (names.length) headers['access-control-allow-headers'] = names.join(', ');
    headers['access-control-max-age'] = '0';
  } else if (!['GET', 'HEAD'].includes(request.method)
      || h['access-control-request-method'] !== undefined || h['access-control-request-headers'] !== undefined) {
    return deny();
  }
  headers['access-control-allow-origin'] = origin;
  if (grant.credentials === 'include') headers['access-control-allow-credentials'] = 'true';
  headers['access-control-expose-headers'] = 'ETag';
  headers['cross-origin-resource-policy'] = 'cross-origin';
  headers['cache-control'] = 'private, no-cache';
  return {status: request.method === 'OPTIONS' ? 204 : 200, headers};
}
