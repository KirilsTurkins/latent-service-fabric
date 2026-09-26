import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {fixture} from './example-fixtures.mjs';
import {createSnapshot} from '../lib/versions/snapshot.mjs';
import {loadSnapshots, publishedVersions, storeSnapshot} from '../lib/versions/storage.mjs';
import {resolveExample} from '../plugins/examples/resolve.mjs';
import {resolveLink, sha256} from '../lib/repository.mjs';

const policy = {schema: 1, assets: [{path: 'docs/assets/specimen.svg', kind: 'illustration', maxBytes: 65536}]};
function setup(t) {
  const f = fixture(t, ['rust', 'go']);
  f.write('docs/guide.mdx', 'import CodeExample from "@site/src/components/CodeExample";\n\n# Versioned guide\n\n<CodeExample example="client/specimen" region="invoke" />\n\n[Owner](fixture.md#fixture-owner-instructions)\n\n![Version asset](assets/specimen.svg)\n');
  f.write('docs/assets/specimen.svg', '<svg xmlns="http://www.w3.org/2000/svg"><text>version one</text></svg>');
  f.write('website/src/components/CodeExample/index.tsx', '// Reviewed component fixture, never executed\n');
  f.write('.gitignore', 'website/.generated/\n');
  const first = f.commit();
  function snapshot(version, documentationSource = f.git('rev-parse', 'HEAD'), exampleSource = documentationSource) {
    return createSnapshot(f.root, {version, runtimeVersion: '0.1.0-alpha.1', runtimeSource: first,
      documentationSource, exampleSource, profile: 'synthetic-fixture'}, policy);
  }
  return {...f, first, snapshot};
}
const snippet = snapshot => snapshot.bundle.examples[0].regions[0].variants[0].snippet.code;

test('two immutable versions retain their own snippets, assets, links and absent languages', t => {
  const f = setup(t);
  const first = f.snapshot('0.1.0-alpha.1'); storeSnapshot(f.root, first);
  f.write('sdk/fixture/example.rs', f.read('sdk/fixture/example.rs').replace('alert(1)', 'alert(2)'));
  f.scenario.variants = f.scenario.variants.filter(variant => variant.language === 'rust'); f.save();
  f.write('docs/assets/specimen.svg', '<svg xmlns="http://www.w3.org/2000/svg"><text>version two</text></svg>');
  f.commit();
  const second = f.snapshot('0.1.0-alpha.2'); storeSnapshot(f.root, second);
  const snapshots = loadSnapshots(f.root);
  assert.deepEqual(snapshots.map(item => item.index.channel), ['0.1.0-alpha.2', '0.1.0-alpha.1']);
  assert.match(snippet(first), /alert\(1\)/); assert.match(snippet(second), /alert\(2\)/);
  assert.notEqual(first.assets[0].sha256, second.assets[0].sha256);
  for (const snapshot of snapshots) {
    const version = snapshot.index.channel;
    const value = resolveExample(snapshot.examples.bundle, {documentVersion: version, example: 'client/specimen', region: 'invoke'});
    assert.equal(value.variants.length, version.endsWith('1') ? 2 : 1);
    assert.equal(resolveLink(snapshot.index, 'docs/guide.mdx', 'fixture.md#fixture-owner-instructions'),
      `/latent-service-fabric/docs/${version}/fixture/#fixture-owner-instructions`);
    assert.match(resolveLink(snapshot.index, 'docs/guide.mdx', 'assets/specimen.svg', {assets: snapshot.assets, image: true}),
      new RegExp(`/content-assets/${version}/${snapshot.assets[0].sha256}/`));
  }
  assert.throws(() => resolveExample(first.bundle, {documentVersion: '0.1.0-alpha.2', example: 'client/specimen', region: 'invoke'}), /identity mismatch/);
  assert.equal(storeSnapshot(f.root, first), first.manifest.snapshotIdentity);
  assert.throws(() => storeSnapshot(f.root, {...second, manifest: {...second.manifest, version: first.manifest.version}}), /different bytes/);
});

test('documentation corrections keep the original runtime and example revisions explicit', t => {
  const f = setup(t);
  f.write('docs/guide.mdx', f.read('docs/guide.mdx').replace('# Versioned guide', '# Corrected versioned guide'));
  const correction = f.commit();
  const snapshot = f.snapshot('0.1.0-alpha.1-docs.2', correction, f.first);
  assert.equal(snapshot.manifest.runtimeSource, f.first);
  assert.equal(snapshot.manifest.documentationSource, correction);
  assert.equal(snapshot.manifest.exampleSource, f.first);
  assert.equal(snapshot.bundle.examples[0].regions[0].variants[0].verification.level, 'source-extracted');
  assert.equal(snapshot.manifest.documents.find(doc => doc.source === 'docs/guide.mdx').sha256, sha256(f.read('docs/guide.mdx')));
});

test('installer documentation anchors remain pinned to the selected release source', t => {
  const f = setup(t);
  const installer = '# Native bundle\n\n## Rootless evaluation\n\nUse the verified bundle.\n';
  f.write('packaging/linux/INSTALL.md', installer);
  f.write('docs/guide.mdx', f.read('docs/guide.mdx') + '\n[Install](../packaging/linux/INSTALL.md#rootless-evaluation)\n');
  const source = f.commit();
  const snapshot = f.snapshot('0.1.0-alpha.1');
  storeSnapshot(f.root, snapshot);
  f.write('packaging/linux/INSTALL.md', '# New installation contract\n');
  f.commit();
  const [loaded] = loadSnapshots(f.root);
  assert.equal(loaded.manifest.linkMetadata['packaging/linux/INSTALL.md'].sha256, sha256(installer));
  assert.equal(resolveLink(loaded.index, 'docs/guide.mdx', '../packaging/linux/INSTALL.md#rootless-evaluation'),
    `https://github.com/KirilsTurkins/latent-service-fabric/blob/${source}/packaging/linux/INSTALL.md#rootless-evaluation`);
  assert.throws(() => f.snapshot('0.1.0-alpha.2'), /Missing repository Markdown anchor/);
});

test('installer documentation support does not admit executable packaging inputs', t => {
  const f = setup(t);
  f.write('packaging/linux/install.py', 'raise RuntimeError("never execute snapshot input")\n');
  f.write('docs/guide.mdx', f.read('docs/guide.mdx') + '\n[Installer source](../packaging/linux/install.py#L1)\n');
  f.commit();
  assert.throws(() => f.snapshot('0.1.0-alpha.1'), /Unapproved snapshot content root/);
});

test('missing regions and non-commit identities cannot produce a snapshot', t => {
  const f = setup(t);
  f.write('docs/guide.mdx', f.read('docs/guide.mdx').replace('region="invoke"', 'region="missing"')); f.commit();
  assert.throws(() => f.snapshot('0.1.0-alpha.1'), /Missing requested/);
  assert.throws(() => f.snapshot('0.1.0-alpha.1', 'development'), /exact local Git revision/);
});

test('a linked source in the Git tree is rejected without following or executing it', t => {
  const f = setup(t);
  const blob = f.git('hash-object', '-w', 'tools/fixture.py');
  f.git('update-index', '--cacheinfo', `120000,${blob},sdk/fixture/example.rs`);
  f.git('commit', '--quiet', '-m', 'linked fixture');
  assert.throws(() => f.snapshot('0.1.0-alpha.1'), /linked or nonregular/);
});

for (const [name, relative, change] of [
  ['document', 'versioned_docs/version-0.1.0-alpha.1/guide.mdx', value => value + '\nChanged\n'],
  ['asset', 'versioned_assets/version-0.1.0-alpha.1/docs/assets/specimen.svg', value => value.replace('one', 'other')],
  ['example source identity', 'versioned_examples/version-0.1.0-alpha.1.json', value => value.replace(/"sourceRevision": "[a-f0-9]+"/, '"sourceRevision": "' + '0'.repeat(40) + '"')],
  ['sidebar', 'versioned_sidebars/version-0.1.0-alpha.1-sidebars.json', value => value.replace('"type": "doc"', '"type": "html"')],
]) test(`altered snapshot ${name} fails closed`, t => {
  const f = setup(t); storeSnapshot(f.root, f.snapshot('0.1.0-alpha.1'));
  f.write(`website/${relative}`, change(f.read(`website/${relative}`)));
  assert.throws(() => loadSnapshots(f.root), /altered/);
});

test('an interrupted install resumes identical bytes before publishing the version', t => {
  const f = setup(t); const snapshot = f.snapshot('0.1.0-alpha.1');
  const first = snapshot.documents[0];
  f.write(`website/versioned_docs/version-0.1.0-alpha.1/${first.source.slice(5)}`, first.bytes);
  assert.deepEqual(publishedVersions(f.root), []);
  storeSnapshot(f.root, snapshot);
  assert.equal(loadSnapshots(f.root).length, 1);
  fs.unlinkSync(path.join(f.root, 'website/versioned_examples/version-0.1.0-alpha.1.json'));
  assert.throws(() => loadSnapshots(f.root), /Missing/);
});

test('unregistered extra historical pages cannot bypass either snapshot or link review', t => {
  const f = setup(t); storeSnapshot(f.root, f.snapshot('0.1.0-alpha.1'));
  f.write('website/versioned_docs/version-0.1.0-alpha.1/hidden.md', '# Unregistered\n');
  assert.throws(() => loadSnapshots(f.root), /Unregistered or missing snapshot file/);
});
