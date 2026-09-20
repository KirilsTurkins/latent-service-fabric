import {canonicalPath, createReader, digest, LIMITS, requireValue, revision, sourceUrl} from './io.mjs';
import {parseMetadata, readSchema} from './schema.mjs';
import {extractRegions} from './regions.mjs';

export const LANGUAGES = Object.freeze(['rust', 'typescript', 'go', 'c', 'java', 'csharp']);
const extensions = {rust: ['rs'], typescript: ['ts', 'tsx'], go: ['go'], c: ['c', 'h'], java: ['java'], csharp: ['cs']};
const audiences = {client: 'client-developer', browser: 'browser-developer', guest: 'guest-author'};
const registrySchema = readSchema('registry');
const scenarioSchema = readSchema('scenario');
const evidenceSchema = readSchema('evidence');
export const registryPath = 'examples/guides/registry.json';

function sourcePath(relative, language) {
  canonicalPath(relative);
  requireValue(/^(sdk\/|examples\/(?!guides\/)|tools\/toolchain-smoke\/examples\/)/.test(relative), 'Unapproved example source root');
  requireValue(extensions[language].includes(relative.split('.').at(-1)), 'Example language/source type mismatch');
  return relative;
}
function referencePath(relative) {
  canonicalPath(relative);
  requireValue(relative === 'website/scripts/test-examples.mjs'
    || /^(docs|sdk|examples|tools)\/.+\.(md|mdx|py|sh|rs|ts|go|c|java|cs|toml|json|kts)$/.test(relative), 'Unapproved validation reference');
  return relative;
}
function evidencePath(relative) {
  canonicalPath(relative);
  requireValue(/^(docs\/evidence|examples\/guides\/evidence|sdk\/[A-Za-z0-9_-]+\/evidence)\/[A-Za-z0-9_-]+\.json$/.test(relative), 'Unapproved example evidence path');
  return relative;
}
function verification(reader, scenario, variant, source, target, matchesRevision) {
  const fallback = reason => ({level: 'source-extracted', reason});
  if (!matchesRevision) return fallback('working-copy');
  if (!variant.validation.evidence) return fallback('no-evidence');
  const reference = variant.validation.evidence;
  evidencePath(reference.path);
  const raw = reader.read(reference.path, LIMITS.metadataBytes, true);
  if (!raw) return fallback('evidence-unavailable');
  if (raw.sha256 !== reference.sha256) return fallback('evidence-digest-mismatch');
  let record;
  try { record = parseMetadata(raw.text, evidenceSchema); } catch { return fallback('invalid-evidence'); }
  if (!record.passed) return fallback('evidence-not-passed');
  if (record.scenario !== scenario.id || record.language !== variant.language
    || record.sourceSha256 !== source.sha256 || record.validationSha256 !== target.sha256
    || !reader.matches(record.sourceRevision, variant.source, source.blob)
    || !reader.matches(record.sourceRevision, variant.validation.target, target.blob)) return fallback('evidence-source-mismatch');
  if (variant.kind === 'synthetic' || (record.level === 'real-node'
    && (record.execution !== 'real-node' || variant.kind !== 'maintained'))
    || (record.level === 'compile-unit' && record.execution === 'real-node')) return fallback('evidence-scope-mismatch');
  return {level: record.level, execution: record.execution, basis: 'reviewed-record',
    sourceRevision: record.sourceRevision, evidenceSha256: raw.sha256,
    toolchain: record.toolchain, run: record.run, scope: record.scope};
}

/** Read only the registry's explicit allowlist. Requests come from parsed public
 * documents, not a glob over code. The returned bundle is the snapshot/UI API;
 * input identities remain private and never include source bodies. */
export function extractExamples(root, requests, identity) {
  const {documentVersion, documentationRevision, sourceRevision} = identity;
  requireValue(typeof documentVersion === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$/.test(documentVersion), 'Invalid example document version');
  revision(documentationRevision); revision(sourceRevision);
  requireValue(Array.isArray(requests) && requests.length <= LIMITS.requests, 'Example request count limit');
  const requested = new Set();
  for (const request of requests) {
    requireValue(/^(client|browser|guest)\/[a-z][a-z0-9-]{0,119}$/.test(request.example)
      && /^[a-z][a-z0-9-]{0,63}$/.test(request.region), 'Invalid example request');
    requested.add(`${request.example}:${request.region}`);
  }
  const reader = createReader(root);
  const registry = parseMetadata(reader.read(registryPath, LIMITS.metadataBytes).text, registrySchema);
  const spellings = new Map();
  function uniqueSpelling(relative) {
    const previous = spellings.get(relative.toLowerCase());
    requireValue(!previous || previous === relative, 'Case-colliding example paths');
    spellings.set(relative.toLowerCase(), relative);
  }
  const ids = new Set();
  const scenarios = [];
  for (const registration of [...registry.scenarios].sort()) {
    canonicalPath(registration); uniqueSpelling(registration);
    requireValue(/^examples\/guides\/[a-z][a-z0-9-]*\/example\.json$/.test(registration), 'Unapproved example registration path');
    const scenario = parseMetadata(reader.read(registration, LIMITS.metadataBytes).text, scenarioSchema);
    requireValue(!ids.has(scenario.id), 'Duplicate example scenario ID'); ids.add(scenario.id);
    requireValue(scenario.id.startsWith(`${scenario.target}/`) && scenario.audience === audiences[scenario.target], 'Example audience/target mismatch');
    const languages = new Set();
    const variants = [];
    for (const variant of scenario.variants) {
      requireValue(!languages.has(variant.language), 'Duplicate example language variant'); languages.add(variant.language);
      requireValue(scenario.target !== 'browser' || variant.language === 'typescript', 'Unsupported browser example variant');
      sourcePath(variant.source, variant.language); uniqueSpelling(variant.source);
      referencePath(variant.validation.target); referencePath(variant.validation.instructions);
      if (variant.validation.evidence) evidencePath(variant.validation.evidence.path);
      const source = reader.read(variant.source);
      const target = reader.read(variant.validation.target);
      const instructions = reader.read(variant.validation.instructions);
      const regions = extractRegions(source.text);
      for (const name of variant.regions) requireValue(regions.has(name), 'Missing registered example region');
      const committed = reader.matches(sourceRevision, variant.source, source.blob);
      const targetCommitted = reader.matches(sourceRevision, variant.validation.target, target.blob);
      const instructionsCommitted = reader.matches(documentationRevision, variant.validation.instructions, instructions.blob);
      requireValue(documentVersion === 'development' || (committed && targetCommitted && instructionsCommitted), 'Versioned example source/reference identity mismatch');
      variants.push({language: variant.language, kind: variant.kind,
        environment: scenario.target === 'client' ? (variant.language === 'typescript' ? 'node' : 'native') : scenario.target === 'guest' ? 'component' : 'browser',
        source: {path: variant.source, revision: sourceRevision, sha256: source.sha256,
          matchesRevision: committed, url: committed ? sourceUrl(sourceRevision, variant.source) : null},
        validation: {target: targetCommitted ? sourceUrl(sourceRevision, variant.validation.target) : null, instructions: instructionsCommitted ? sourceUrl(documentationRevision, variant.validation.instructions) : null},
        verification: verification(reader, scenario, variant, source, target, committed),
        regions: Object.fromEntries([...variant.regions].sort().map(name => [name, regions.get(name)]))});
    }
    scenarios.push({...scenario, variants});
  }
  const examples = [];
  let publicBytes = 0;
  for (const scenario of scenarios.sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0)) {
    const regions = [];
    for (const key of [...requested].sort()) {
      const [id, name] = key.split(':');
      if (id !== scenario.id) continue;
      const variants = scenario.variants.filter(variant => Object.hasOwn(variant.regions, name))
        .sort((left, right) => LANGUAGES.indexOf(left.language) - LANGUAGES.indexOf(right.language))
        .map(({regions, ...variant}) => ({...variant, snippet: regions[name]}));
      requireValue(variants.length > 0, 'Missing requested example region');
      publicBytes += Buffer.byteLength(JSON.stringify(variants));
      requireValue(publicBytes <= LIMITS.outputBytes, 'Example output byte limit');
      regions.push({id: name, variants}); requested.delete(key);
    }
    if (regions.length) examples.push({id: scenario.id, title: scenario.title, audience: scenario.audience, target: scenario.target, regions});
  }
  requireValue(requested.size === 0, 'Unknown requested example scenario');
  const inputs = [...reader.inputs].map(([path, input]) => ({path, sha256: input.sha256})).sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  const bundle = {schema: 1, documentVersion, documentationRevision, sourceRevision, inputDigest: digest(JSON.stringify(inputs)), examples};
  requireValue(Buffer.byteLength(JSON.stringify(bundle, null, 2)) + 1 <= LIMITS.outputBytes, 'Example output byte limit');
  return {bundle, inputs};
}
