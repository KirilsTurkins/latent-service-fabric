import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {extractExamples} from '../plugins/examples/extract.mjs';
import {createReader, digest, LIMITS, writeSnapshot} from '../plugins/examples/io.mjs';
import {extractRegions} from '../plugins/examples/regions.mjs';
import {parseMetadata, readSchema, validate} from '../plugins/examples/schema.mjs';
import {fixture} from './example-fixtures.mjs';

const extract = f => extractExamples(f.root, f.requests, f.identity());
const variant = result => result.bundle.examples[0].regions[0].variants[0];

test('six syntaxes retain Unicode, whitespace and unsafe-looking code only as selected data', t => {
  const f = fixture(t);
  const result = extract(f);
  const variants = result.bundle.examples[0].regions[0].variants;
  assert.deepEqual(variants.map(item => item.language), ['rust', 'typescript', 'go', 'c', 'java', 'csharp']);
  for (const item of variants) {
    assert.match(item.snippet.code, /^  /);
    assert.match(item.snippet.code, /α 😀/);
    assert.ok(item.snippet.code.endsWith('\n'));
    assert.ok(item.snippet.code.includes("{import('node:fs')}"));
    assert.ok(item.snippet.code.includes('```'));
    assert.equal(item.snippet.sha256, digest(item.snippet.code));
    assert.equal(item.source.matchesRevision, true);
    assert.ok(item.source.url.includes(f.initialRevision));
    assert.equal(item.verification.level, 'source-extracted');
    assert.equal(item.environment, item.language === 'typescript' ? 'node' : 'native');
  }
  assert.doesNotMatch(JSON.stringify(result.bundle), /UNREFERENCED_SENTINEL|example.json|fixture.py.*DO NOT EXECUTE/);
  assert.ok(!JSON.stringify(result.bundle).includes(f.root));
  assert.equal(JSON.stringify(result), JSON.stringify(extract(f)));
});

test('registration, request and language order do not change deterministic output', t => {
  const f = fixture(t);
  f.requests.push({...f.requests[0]});
  const before = extract(f).bundle;
  f.scenario.variants.reverse(); f.save();
  const after = extract(f).bundle;
  // Input bytes changed, but displayed ordering and data are identical.
  assert.deepEqual(before.examples, after.examples);
  assert.notEqual(before.inputDigest, after.inputDigest);
  assert.deepEqual(extractExamples(f.root, [], f.identity()).bundle.examples, []);
});

test('changed source bytes change identities and suppress misleading source links', t => {
  const f = fixture(t, ['rust']);
  const before = extract(f);
  const source = f.scenario.variants[0].source;
  f.write(source, f.read(source).replace('alert(1)', 'alert(2)'));
  const after = extract(f);
  assert.notEqual(before.bundle.inputDigest, after.bundle.inputDigest);
  assert.notEqual(variant(before).snippet.sha256, variant(after).snippet.sha256);
  assert.equal(variant(after).source.url, null);
  assert.equal(variant(after).verification.reason, 'working-copy');
  f.commit();
  assert.equal(variant(extract(f)).source.matchesRevision, true);
});

for (const [name, change, error] of [
  ['duplicate scenario IDs', f => { f.write('examples/guides/other/example.json', f.scenario); f.write('examples/guides/registry.json', {schema: 1, scenarios: [f.registration, 'examples/guides/other/example.json']}); }, /Duplicate.*ID/],
  ['duplicate language IDs', f => { f.scenario.variants.push({...f.scenario.variants[0], regions: ['invoke']}); f.save(); }, /Duplicate.*language/],
  ['unknown variants', f => { f.scenario.variants[0].language = 'python'; f.save(); }, /Unknown/],
  ['unknown metadata', f => { f.scenario.shell = 'echo insecure'; f.save(); }, /Unknown/],
  ['wrong audience', f => { f.scenario.audience = 'guest-author'; f.save(); }, /audience/],
  ['wrong target', f => { f.scenario.target = 'guest'; f.save(); }, /target/],
  ['absent request', f => f.requests[0].example = 'client/missing', /Unknown requested/],
  ['absent requested region', f => f.requests[0].region = 'missing', /Missing requested/],
  ['absent registered region', f => { f.scenario.variants[0].regions.push('missing'); f.save(); }, /Missing registered/],
  ['invalid validation path', f => { f.scenario.variants[0].validation.target = '../credentials'; f.save(); }, /path/],
  ['invalid evidence path', f => { f.scenario.variants[0].validation.evidence = {path: '/etc/passwd', sha256: 'a'.repeat(64)}; f.save(); }, /path/],
]) test(`rejects ${name}`, t => { const f = fixture(t, ['rust']); change(f); assert.throws(() => extract(f), error); });

for (const source of ['../secret.rs', '/etc/secret.rs', 'sdk/../secret.rs', 'sdk//secret.rs', 'sdk\\secret.rs',
  'sdk/%2e%2e/secret.rs', 'sdk/.private/secret.rs', 'sdk/CON.rs', 'sdk/trailing./secret.rs',
  'sdk/secret.rs:stream', 'docs/secret.rs', 'examples/guides/specimen/secret.rs', 'sdk/secret.json']) {
  test(`rejects non-source or ambiguous path ${source}`, t => {
    const f = fixture(t, ['rust']); f.scenario.variants[0].source = source; f.save();
    assert.throws(() => extract(f), /path|root|type/);
  });
}

test('wrong case, nonregular inputs and malformed UTF-8 are rejected', t => {
  const f = fixture(t, ['rust']); const relative = f.scenario.variants[0].source;
  const original = f.read(relative); const absolute = path.join(f.root, relative);
  fs.unlinkSync(absolute); fs.mkdirSync(absolute);
  assert.throws(() => extract(f), /Nonregular/);
  fs.rmdirSync(absolute); f.write(relative, Buffer.from([0xC3, 0x28]));
  assert.throws(() => extract(f), /encoded data|encoding/);
  f.write(relative, original); f.scenario.variants[0].source = relative.replace('example', 'EXAMPLE'); f.save();
  assert.throws(() => extract(f), /cased/);
});

function fileLink(t, target, link) {
  try { fs.symlinkSync(target, link); return true; }
  catch (error) {
    if (process.platform !== 'win32' || error.code !== 'EPERM') throw error;
    t.skip('This Windows host cannot create file symlinks; Linux runs the negative fixture.');
    return false;
  }
}

test('registered source file symlinks are rejected', t => {
  const f = fixture(t, ['rust']);
  const absolute = path.join(f.root, f.scenario.variants[0].source);
  fs.unlinkSync(absolute);
  if (!fileLink(t, path.join(f.root, 'tools/fixture.py'), absolute)) return;
  assert.throws(() => extract(f), /Linked/);
});

test('source ancestor symlinks and Windows junctions are rejected', t => {
  const f = fixture(t, ['rust']);
  f.scenario.variants[0].source = 'sdk/linked/example.rs'; f.save();
  fs.symlinkSync(path.join(f.root, 'sdk/fixture'), path.join(f.root, 'sdk/linked'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => extract(f), /Linked/);
});

test('region grammar rejects duplicate, nested, empty, malformed and unbalanced markers', () => {
  const wrap = code => `// lsf-example-begin: one\n${code}// lsf-example-end: one\n`;
  for (const source of [wrap('x\n') + wrap('y\n'), wrap(wrap('x\n')), wrap(' \t\n'),
    '// lsf-example-begin: one\nx\n', '// lsf-example-end: one\n',
    '// lsf-example-begin: one!\nx\n', wrap('x\n').replace('end: one', 'end: two')]) assert.throws(() => extractRegions(source), /region/);
  const crlf = '// lsf-example-begin: one\r\n\tx\r\n// lsf-example-end: one\r\n';
  assert.equal(extractRegions(crlf).get('one').code, '\tx\r\n');
  assert.deepEqual([...extractRegions('no markers').keys()], []);
});

test('file, metadata, region, request and registration budgets fail before output', t => {
  const f = fixture(t, ['rust']); const relative = f.scenario.variants[0].source;
  const original = f.read(relative);
  f.write(relative, ' '.repeat(LIMITS.fileBytes + 1)); assert.throws(() => extract(f), /oversized/);
  f.write(relative, original.replace('  let', ' '.repeat(LIMITS.regionBytes) + 'let')); assert.throws(() => extract(f), /region byte/);
  f.write(relative, original);
  assert.throws(() => extractExamples(f.root, Array(257).fill(f.requests[0]), f.identity()), /request count/);
  f.write(f.registration, ' '.repeat(LIMITS.metadataBytes + 1)); assert.throws(() => extract(f), /oversized/);
  f.save();
  f.write('examples/guides/registry.json', {schema: 1, scenarios: Array.from({length: 65}, (_, i) => `examples/guides/s${i}/example.json`)});
  assert.throws(() => extract(f), /array limit/);
});

test('evidence must match exact source and target bytes at an available local checkpoint', t => {
  const f = fixture(t, ['rust']); f.evidence(); f.commit();
  const result = variant(extract(f));
  assert.equal(result.verification.level, 'real-node');
  assert.equal(result.verification.sourceRevision, f.initialRevision);
  assert.notEqual(result.verification.sourceRevision, f.identity().documentationRevision);
  f.write(f.scenario.variants[0].source, f.read(f.scenario.variants[0].source).replace('alert(1)', 'alert(2)')); f.commit();
  assert.equal(variant(extract(f)).verification.reason, 'evidence-source-mismatch');
});

for (const [name, update, reason] of [
  ['failure', {passed: false}, 'evidence-not-passed'],
  ['test-double cannot assert real-node', {execution: 'test-double'}, 'evidence-scope-mismatch'],
  ['compile-unit cannot assert real-node', {execution: 'compile-unit'}, 'evidence-scope-mismatch'],
  ['source bytes', {sourceSha256: '0'.repeat(64)}, 'evidence-source-mismatch'],
  ['target bytes', {validationSha256: '0'.repeat(64)}, 'evidence-source-mismatch'],
  ['unavailable revision', {sourceRevision: '0'.repeat(40)}, 'evidence-source-mismatch'],
  ['wrong language', {language: 'go'}, 'evidence-source-mismatch'],
  ['wrong scenario', {scenario: 'client/elsewhere'}, 'evidence-source-mismatch'],
  ['missing toolchain', {toolchain: ''}, 'invalid-evidence'],
]) test(`evidence mismatch: ${name}`, t => {
  const f = fixture(t, ['rust']); f.evidence(update); assert.equal(variant(extract(f)).verification.reason, reason);
});

test('absent, altered and synthetic evidence cannot grant a passing badge', t => {
  const f = fixture(t, ['rust']); f.evidence();
  const reference = f.scenario.variants[0].validation.evidence;
  f.scenario.variants[0].kind = 'synthetic'; f.save();
  assert.equal(variant(extract(f)).verification.reason, 'evidence-scope-mismatch');
  f.scenario.variants[0].kind = 'maintained'; f.save();
  f.write(reference.path, '{}'); assert.equal(variant(extract(f)).verification.reason, 'evidence-digest-mismatch');
  fs.unlinkSync(path.join(f.root, reference.path)); assert.equal(variant(extract(f)).verification.reason, 'evidence-unavailable');
});

test('linked evidence cannot grant a passing badge', t => {
  const f = fixture(t, ['rust']); f.evidence();
  const evidence = path.join(f.root, f.scenario.variants[0].validation.evidence.path);
  fs.unlinkSync(evidence);
  if (!fileLink(t, path.join(f.root, 'tools/fixture.py'), evidence)) return;
  assert.throws(() => extract(f), /Linked/);
});

test('compilation and local doubles stay distinct from real-node qualification', t => {
  const f = fixture(t, ['rust']); f.evidence({level: 'compile-unit', execution: 'test-double'});
  f.scenario.variants[0].kind = 'test-double'; f.save();
  const result = variant(extract(f)).verification;
  assert.equal(result.level, 'compile-unit'); assert.equal(result.execution, 'test-double');
});

test('schema rejects duplicate JSON keys including escaped aliases and unsupported revisions', t => {
  const schema = readSchema('registry');
  for (const json of ['{"schema":1,"schema":1,"scenarios":[]}', '{"schema":1,"\\u0073chema":1,"scenarios":[]}', '{not json}']) assert.throws(() => parseMetadata(json, schema), /JSON/);
  assert.throws(() => validate({type: 'object', remoteReference: 'https://invalid'}, {}), /Unsupported/);
  const f = fixture(t, ['rust']);
  for (const sourceRevision of ['development', '--help', 'x'.repeat(40)]) assert.throws(() => extractExamples(f.root, f.requests, {...f.identity(), sourceRevision}), /revision/);
});

test('content-addressed snapshots are idempotent, private and refuse corrupted outputs', t => {
  const f = fixture(t, ['rust']); const bundle = extract(f).bundle;
  const output = writeSnapshot(f.root, bundle);
  assert.match(output, /website[/\\]\.generated[/\\]examples[/\\][a-f0-9]{64}\.json$/);
  assert.equal(output, writeSnapshot(f.root, bundle));
  assert.deepEqual(JSON.parse(fs.readFileSync(output)), bundle);
  fs.writeFileSync(output, '{}'); assert.throws(() => writeSnapshot(f.root, bundle), /collision/);
  fs.unlinkSync(output); assert.equal(writeSnapshot(f.root, bundle), output);
});

test('content-addressed snapshots refuse linked outputs', t => {
  const f = fixture(t, ['rust']); const bundle = extract(f).bundle;
  const output = writeSnapshot(f.root, bundle);
  fs.unlinkSync(output);
  if (!fileLink(t, path.join(f.root, 'tools/fixture.py'), output)) return;
  assert.throws(() => writeSnapshot(f.root, bundle), /collision/);
});

test('aggregate read and file count budgets are independently bounded', t => {
  const f = fixture(t, ['rust']); let reader = createReader(f.root);
  for (let i = 0; i < 33; i++) f.write(`sdk/fixture/f${i}.rs`, 'x'.repeat(LIMITS.fileBytes));
  for (let i = 0; i < 32; i++) reader.read(`sdk/fixture/f${i}.rs`);
  assert.throws(() => reader.read('sdk/fixture/f32.rs'), /aggregate/);
  reader = createReader(f.root);
  for (let i = 0; i < 513; i++) f.write(`sdk/fixture/s${i}.rs`, 'x');
  for (let i = 0; i < 512; i++) reader.read(`sdk/fixture/s${i}.rs`);
  assert.throws(() => reader.read('sdk/fixture/s512.rs'), /count/);
});

test('non-development extraction refuses a changed source rather than snapshotting current code as an old version', t => {
  const f = fixture(t, ['rust']);
  const identity = {...f.identity(), documentVersion: 'alpha.1'};
  f.write(f.scenario.variants[0].source, f.read(f.scenario.variants[0].source).replace('alert(1)', 'alert(2)'));
  assert.throws(() => extractExamples(f.root, f.requests, identity), /identity mismatch/);
});

test('missing evidence directories are unavailable, not an implicit passing record', t => {
  const f = fixture(t, ['rust']);
  f.scenario.variants[0].validation.evidence = {path: 'examples/guides/evidence/missing.json', sha256: '0'.repeat(64)}; f.save();
  assert.equal(variant(extract(f)).verification.reason, 'evidence-unavailable');
});

test('region count, output bytes, NUL and BOM are bounded independently', t => {
  const f = fixture(t, ['rust']);
  const source = f.scenario.variants[0].source;
  for (const invalid of ['\0', '\uFEFF']) {
    f.write(source, invalid + '// example\n'); assert.throws(() => extract(f), /NUL or BOM/);
  }
  const regions = Array.from({length: 33}, (_, i) => `// lsf-example-begin: r${i}\nx\n// lsf-example-end: r${i}\n`).join('');
  assert.throws(() => extractRegions(regions), /region count/);
  const multi = fixture(t);
  for (const variant of multi.scenario.variants) {
    variant.regions = Array.from({length: 7}, (_, i) => `r${i}`);
    multi.write(variant.source, variant.regions.map(name => `// lsf-example-begin: ${name}\n${'x'.repeat(30000)}\n// lsf-example-end: ${name}\n`).join(''));
  }
  multi.save();
  multi.requests.splice(0, 1, ...Array.from({length: 7}, (_, i) => ({example: multi.scenario.id, region: `r${i}`})));
  assert.throws(() => extract(multi), /output byte/);
});

test('JSON schemas and runtime limits agree on registry and region capacity', () => {
  assert.equal(readSchema('registry').properties.scenarios.maxItems, LIMITS.registrations);
  const variants = readSchema('scenario').properties.variants;
  assert.equal(variants.maxItems, LIMITS.variants);
  assert.equal(variants.items.properties.regions.maxItems, LIMITS.regions);
});

test('schema string limits count Unicode code points rather than UTF-16 code units', () => {
  assert.equal(validate({type: 'string', minLength: 1, maxLength: 1}, '😀'), '😀');
  assert.throws(() => validate({type: 'string', maxLength: 1}, '😀α'), /limit/);
});
