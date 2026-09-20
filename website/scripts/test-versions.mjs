// Build the real component with two different immutable snapshots in an owned,
// isolated Git checkout. Its artifact is never the publication build directory.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fixture} from '../tests/example-fixtures.mjs';
import {createSnapshot} from '../lib/versions/snapshot.mjs';
import {storeSnapshot} from '../lib/versions/storage.mjs';
import {generatedDirectory} from '../lib/prepare.mjs';
import {git, repositoryRoot, websiteRoot} from '../lib/repository.mjs';

assert.equal(process.argv.length, 2);
assert.equal(git(repositoryRoot, 'status', '--porcelain=v1', '--untracked-files=all').trim(), '', 'Commit the reviewed source before the isolated fixture build');
const revision = git(repositoryRoot, 'rev-parse', 'HEAD').trim();
const output = generatedDirectory('.generated/version-review');
function run(program, args, cwd, timeout = 180000) {
  console.log(`[versions] start ${path.basename(program)} ${args.at(-1)}`);
  const started = Date.now();
  const result = execFileSync(program, args, {cwd, timeout, maxBuffer: 8 * 1024 * 1024, stdio: 'inherit',
    env: {...process.env, GIT_TERMINAL_PROMPT: '0', GIT_NO_REPLACE_OBJECTS: '1', GIT_NO_LAZY_FETCH: '1',
      PLAYWRIGHT_BROWSERS_PATH: path.join(websiteRoot, '.generated/browsers')}});
  console.log(`[versions] completed in ${Date.now() - started}ms`);
  return result;
}
run(process.execPath, [path.join(websiteRoot, 'scripts/test-version-pages.mjs')], repositoryRoot);
const owner = fs.mkdtempSync(path.join(generatedDirectory('.generated/version-browser'), 'run-'));
const checkout = path.join(owner, 'repository');
const cleanups = [];
try {
  run('git', ['clone', '--quiet', '--shared', '--no-checkout', '-c', 'core.longpaths=true', repositoryRoot, checkout], repositoryRoot);
  run('git', ['checkout', '--quiet', '--detach', revision], checkout);
  const f = fixture({after: callback => cleanups.push(callback)}, ['rust', 'go']);
  f.write('.gitignore', 'website/.generated/\n');
  f.write('docs/fixture.md', '# Synthetic fixture owner\n\n## Fixture owner instructions\n\nUI regression only; no runtime support or execution claim.\n');
  f.write('website/src/components/CodeExample/index.tsx', '// Reviewed authoring import; the actual component is supplied by the site.\n');
  for (const name of ['development/standalone-quickstart', 'learn/fixture', 'operations/fixture', 'reference/fixture', 'architecture/overview'])
    f.write(`docs/${name}.md`, '# Synthetic version navigation fixture\n\nUI regression only; no runtime support or execution claim.\n');
  f.write('docs/development/website-code-examples.mdx', 'import CodeExample from "@site/src/components/CodeExample";\n\n# Synthetic version browser fixture\n\nNo runtime qualification.\n\n<CodeExample example="client/specimen" region="invoke" />\n\n![Synthetic version asset](../assets/specimen.svg)\n\n[Owner](../fixture.md#fixture-owner-instructions)\n');
  const policy = {schema: 1, assets: [{path: 'docs/assets/specimen.svg', kind: 'illustration', maxBytes: 65536}]};
  const versions = [];
  for (const ordinal of [1, 2]) {
    if (ordinal === 2) {
      f.write('sdk/fixture/example.rs', f.read('sdk/fixture/example.rs').replace('alert(1)', 'alert(2)'));
      f.scenario.variants = f.scenario.variants.filter(variant => variant.language === 'rust');
      f.save();
    }
    const assetText = `version-${ordinal}-asset`;
    f.write('docs/assets/specimen.svg', `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="40" viewBox="0 0 240 40"><title>${assetText}</title><text x="10" y="24">${assetText}</text></svg>`);
    const source = f.commit();
    const version = `0.0.0-fixture.${ordinal}`;
    const snapshot = createSnapshot(f.root, {version, runtimeVersion: version, runtimeSource: source,
      documentationSource: source, exampleSource: source, profile: 'synthetic-fixture'}, policy);
    storeSnapshot(checkout, snapshot);
    versions.push({version, source, snapshotIdentity: snapshot.manifest.snapshotIdentity, assetSha256: snapshot.assets[0].sha256,
      assetText, snippet: snapshot.bundle.examples[0].regions[0].variants[0].snippet.code, languages: ordinal === 1 ? 2 : 1});
  }
  fs.mkdirSync(path.join(checkout, 'website/.generated'), {recursive: true});
  fs.writeFileSync(path.join(checkout, 'website/.generated/version-fixture-expectations.json'), JSON.stringify({revision, versions}));
  run('git', ['add', 'website/versioned_docs', 'website/versioned_assets', 'website/versioned_examples', 'website/versioned_manifests', 'website/versioned_sidebars', 'website/versions.json'], checkout);
  run('git', ['-c', 'user.name=Version browser fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--quiet', '-m', 'Synthetic site fixtures only; never publish'], checkout);
  const npm = path.join(websiteRoot, 'toolchain/node_modules/npm/bin/npm-cli.js');
  assert.ok(fs.existsSync(npm), 'Install the reviewed website/toolchain graph first');
  run(process.execPath, [npm, 'ci', '--prefix', 'website', '--ignore-scripts', '--no-audit', '--no-fund'], checkout);
  for (const command of ['build', 'build-root'])
    run(process.execPath, [path.join(checkout, 'website/scripts/site.mjs'), command], checkout, 600000);
  run(process.execPath, [path.join(checkout, 'website/scripts/test-version-pages.mjs'), '--fixtures'], checkout, 300000);
  fs.copyFileSync(path.join(checkout, 'website/.generated/version-review/fixtures.json'), path.join(output, 'fixtures.json'));
  const publication = JSON.parse(fs.readFileSync(path.join(output, 'publication.json'), 'utf8'));
  const fixtures = JSON.parse(fs.readFileSync(path.join(output, 'fixtures.json'), 'utf8'));
  fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify({schema: 1, sourceRevision: revision,
    fixtureBuildIsPublishable: false, publication, fixtures}, null, 2) + '\n');
} catch (error) {
  // Retain the failing stage before potentially slow Windows dependency cleanup.
  console.error(error);
  throw error;
} finally {
  for (const cleanup of cleanups.reverse()) cleanup();
  // Only the directory minted above belongs to this test; never remove the
  // maintained checkout, its dependencies, publication artifact or receipts.
  assert.equal(path.dirname(fs.realpathSync(owner)), fs.realpathSync(path.join(websiteRoot, '.generated/version-browser')));
  assert.match(path.basename(owner), /^run-[A-Za-z0-9]+$/);
  fs.rmSync(owner, {recursive: true, force: true});
}
