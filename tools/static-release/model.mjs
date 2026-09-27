import {createHash, randomUUID} from 'node:crypto';

export function requireValue(condition, code) { if (!condition) throw new Error(code); }
export function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
export function digest(value) { return createHash('sha256').update(canonical(value)).digest('hex'); }
export function equal(left, right) { return canonical(left) === canonical(right); }
function closed(value, names) {
  requireValue(value && typeof value === 'object' && !Array.isArray(value) && equal(Object.keys(value).sort(), names.slice().sort()), 'closed-input-required');
}
const id = value => typeof value === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(value);
export function counter(value) {
  requireValue(typeof value === 'string' && /^(0|[1-9][0-9]{0,19})$/.test(value) && BigInt(value) <= 18446744073709551615n, 'invalid-generation');
  return value;
}
export function manifests(intent) {
  closed(intent, ['schemaVersion', 'tenant', 'publication', 'routes']);
  requireValue(intent.schemaVersion === 'latent.static.route-set.v1' && id(intent.tenant), 'invalid-route-set');
  requireValue(typeof intent.publication === 'string' && /^publication:sha256:[0-9a-f]{64}$/.test(intent.publication), 'immutable-publication-required');
  requireValue(Array.isArray(intent.routes) && intent.routes.length >= 1 && intent.routes.length <= 8, 'route-pair-bound');
  const identifiers = new Set(), bindings = new Set(), result = [];
  for (const row of intent.routes) {
    closed(row, ['get', 'head', 'scheme', 'host', 'path', 'pathMatch']);
    requireValue(['http', 'https'].includes(row.scheme) && ['exact', 'prefix'].includes(row.pathMatch), 'invalid-route-profile');
    requireValue(typeof row.host === 'string' && row.host.length <= 255 && typeof row.path === 'string' && row.path.length <= 240, 'invalid-route-address');
    const url = new URL(row.scheme + '://' + row.host + row.path);
    requireValue(url.host === row.host && url.pathname === row.path && !url.search && !url.hash && !url.username && !url.password
      && /^\/(?:[A-Za-z0-9._~-]+(?:\/[A-Za-z0-9._~-]+)*)?$/.test(row.path)
      && !row.path.split('/').some(part => part === '.' || part === '..')
      && !row.path.startsWith('/_lsf'), 'canonical-route-required');
    const binding = canonical([row.scheme, row.host, row.path, row.pathMatch]);
    requireValue(!bindings.has(binding), 'duplicate-route-binding'); bindings.add(binding);
    for (const method of ['GET', 'HEAD']) {
      const name = row[method.toLowerCase()];
      requireValue(id(name) && !identifiers.has(name), 'unique-trigger-id-required'); identifiers.add(name);
      result.push({apiVersion: 'latent.dev/v1alpha1', kind: 'HttpTrigger', metadata: {name, tenant: intent.tenant},
        spec: {target: {kind: 'static-web', publication: intent.publication}, configuration: {
          profile: 'static-site-v1', scheme: row.scheme, host: row.host, path: row.path, pathMatch: row.pathMatch, method}}});
    }
  }
  return result;
}
export function normalized(manifest) {
  // The native codec emits omitted, empty and null optional metadata uniformly.
  const value = structuredClone(manifest);
  for (const name of ['labels', 'annotations']) {
    if (value.metadata[name] == null || equal(value.metadata[name], {})) delete value.metadata[name];
  }
  return value;
}
export function sameManifest(left, right) { return equal(normalized(left), normalized(right)); }
export async function eligible(client, intent) {
  const result = await client.call(['web', 'get', '--publication', intent.publication]);
  requireValue(result.category === 'success' && result.outcomeKnown === true, 'publication-observation-unavailable');
  const data = result.data;
  requireValue(equal(data.record?.publication, {id: intent.publication, tenant: intent.tenant})
    && data.eligibility === 'RELEASE_LIVE_ELIGIBILITY_ELIGIBLE'
    && data.eligibilityReason === 'RELEASE_ELIGIBILITY_REASON_VERIFIED', 'publication-not-currently-eligible');
  return data.record;
}
export async function observe(client, name, tenant) {
  const result = await client.call(['trigger', 'get', name]);
  requireValue(['success', 'not-found'].includes(result.category) && result.outcomeKnown === true
    && result.data?.durability === 'confirmed', 'route-observation-unavailable');
  const row = result.data.trigger;
  requireValue((result.category === 'not-found') === (row === null), 'invalid-route-observation');
  if (row) requireValue(row.manifest?.metadata?.name === name && row.manifest.metadata.tenant === tenant, 'route-scope-mismatch');
  return {manifest: row ? normalized(row.manifest) : null, generation: row ? counter(row.generation) : '0', stateVersion: counter(result.data.stateVersion)};
}
export async function plan(client, intent, binding) {
  const desired = manifests(intent);
  const publication = await eligible(client, intent);
  for (let attempt = 0; attempt < 3; attempt++) {
    const rows = [];
    for (const manifest of desired) {
      const baseline = await observe(client, manifest.metadata.name, intent.tenant);
      if (baseline.manifest) {
        requireValue(baseline.manifest.kind === 'HttpTrigger' && baseline.manifest.spec.target.kind === 'static-web'
          && equal(baseline.manifest.spec.configuration, manifest.spec.configuration), 'route-ownership-changed');
        manifest.metadata = structuredClone(baseline.manifest.metadata);
      }
      rows.push({desired: structuredClone(manifest), baseline, attempts: []});
    }
    if (new Set(rows.map(row => row.baseline.stateVersion)).size === 1) {
      return {schemaVersion: 'latent.static.route-journal.v1', id: randomUUID(), binding, intent,
        intentDigest: digest(intent), publication, rows, status: 'planned'};
    }
  }
  throw new Error('catalog-changing-plan-not-created');
}

export function validateJournal(journal, binding) {
  requireValue(journal.schemaVersion === 'latent.static.route-journal.v1' && journal.binding === binding
    && journal.intentDigest === digest(journal.intent), 'journal-identity-mismatch');
  const desired = manifests(journal.intent);
  requireValue(journal.rows.length === desired.length, 'journal-route-count');
  journal.rows.forEach((row, index) => {
    requireValue(equal(row.desired.spec, desired[index].spec)
      && row.desired.metadata.name === desired[index].metadata.name
      && row.desired.metadata.tenant === journal.intent.tenant && row.attempts.length <= 4, 'journal-route-identity');
    counter(row.baseline.generation); counter(row.baseline.stateVersion);
    for (const attempt of row.attempts) {
      requireValue(id(attempt.id) && ['pending', 'confirmed', 'rejected'].includes(attempt.status), 'journal-operation-identity');
      counter(attempt.generation); counter(attempt.stateVersion);
    }
  });
}
