import fs from 'node:fs';
import path from 'node:path';
import {canonicalPath, readSource, requireValue, sha256, trackedPaths} from '../repository.mjs';
import {SNAPSHOT_LIMITS} from './git-source.mjs';
import {snapshotHash, snapshotIndex, validateBundle, versionId} from './model.mjs';

const json = value => Buffer.from(JSON.stringify(value, null, 2) + '\n');
function directory(root, relative) {
  canonicalPath(relative);
  let current = fs.realpathSync(root);
  for (const part of relative.split('/')) {
    current = path.join(current, part);
    if (!fs.existsSync(current)) fs.mkdirSync(current);
    requireValue(fs.lstatSync(current).isDirectory() && !fs.lstatSync(current).isSymbolicLink(), 'Linked or non-directory snapshot output');
  }
  return current;
}
function immutableWrite(root, relative, bytes) {
  const parent = directory(root, path.posix.dirname(relative));
  const destination = path.join(parent, path.posix.basename(relative));
  try { fs.writeFileSync(destination, bytes, {flag: 'wx'}); }
  catch (error) {
    if (error.code !== 'EEXIST') throw error;
    requireValue(fs.lstatSync(destination).isFile() && !fs.lstatSync(destination).isSymbolicLink()
      && readSource(root, relative, SNAPSHOT_LIMITS.bytes).equals(bytes), 'Snapshot exists with different bytes; choose a new documentation snapshot version');
  }
}
export function publishedVersions(root) {
  const filename = path.join(root, 'website/versions.json');
  if (!fs.existsSync(filename)) return [];
  const versions = JSON.parse(readSource(root, 'website/versions.json', 1024).toString());
  requireValue(Array.isArray(versions) && versions.length <= SNAPSHOT_LIMITS.versions && new Set(versions).size === versions.length, 'Invalid maintained-version inventory');
  versions.forEach(versionId);
  return versions;
}
export function storeSnapshot(root, snapshot) {
  const {manifest, documents, assets, bundle} = snapshot;
  const version = versionId(manifest.version);
  const versions = publishedVersions(root);
  requireValue(versions.includes(version) || versions.length < SNAPSHOT_LIMITS.versions, 'Maintained-version limit; review retirement before adding a version');
  const files = documents.map(({source, bytes}) => [`versioned_docs/version-${version}/${source.slice(5)}`, bytes]);
  files.push(...assets.map(({path: source, bytes}) => [`versioned_assets/version-${version}/${source}`, bytes]));
  files.push([`versioned_examples/version-${version}.json`, json(bundle)],
    [`versioned_sidebars/version-${version}-sidebars.json`, json(manifest.sidebars)],
    [`versioned_manifests/version-${version}.json`, json(manifest)]);
  requireValue(files.length <= SNAPSHOT_LIMITS.files + 103
    && files.reduce((sum, [, bytes]) => sum + bytes.length, 0) <= SNAPSHOT_LIMITS.bytes, 'Snapshot output budget');
  // Stage all deterministic bytes before installing them. Interrupted installs
  // can only resume with identical bytes; the publication inventory is last.
  for (const [relative, bytes] of files) immutableWrite(root, `website/.generated/version-staging/${version}/${relative}`, bytes);
  for (const [relative, bytes] of files) immutableWrite(root, `website/${relative}`, bytes);
  if (!versions.includes(version)) {
    const temporary = `website/.generated/version-staging/${version}/versions-${manifest.snapshotIdentity}.json`;
    immutableWrite(root, temporary, json([version, ...versions]));
    // Existing inventory was read through safeFile above; never follow a link.
    requireValue(JSON.stringify(publishedVersions(root)) === JSON.stringify(versions), 'Snapshot publication inventory changed concurrently');
    fs.renameSync(path.join(root, temporary), path.join(root, 'website/versions.json'));
  }
  return manifest.snapshotIdentity;
}
export function loadSnapshots(root, currentPaths = trackedPaths(root)) {
  const expectedFiles = new Set();
  const snapshots = publishedVersions(root).map(version => {
    for (const file of [`versioned_examples/version-${version}.json`, `versioned_sidebars/version-${version}-sidebars.json`,
      `versioned_manifests/version-${version}.json`]) expectedFiles.add(`website/${file}`);
    const manifest = JSON.parse(readSource(root, `website/versioned_manifests/version-${version}.json`).toString());
    requireValue(manifest.schema === 1 && manifest.version === version && manifest.snapshotIdentity === snapshotHash(manifest)
      && [manifest.runtimeSource, manifest.documentationSource, manifest.exampleSource].every(value => /^[a-f0-9]{40}$/.test(value)), 'Snapshot manifest identity mismatch');
    requireValue(Array.isArray(manifest.documents) && manifest.documents.length > 0 && manifest.documents.length <= SNAPSHOT_LIMITS.files, 'Snapshot document budget');
    let bytesRead = 0;
    const documents = manifest.documents.map(document => {
      canonicalPath(document.source);
      requireValue(/^docs\/(?!wiki\/).+\.mdx?$/.test(document.source), 'Unapproved snapshot document');
      const file = `website/versioned_docs/version-${version}/${document.source.slice(5)}`;
      requireValue(!expectedFiles.has(file), 'Duplicate snapshot document');
      expectedFiles.add(file);
      const bytes = readSource(root, file);
      bytesRead += bytes.length;
      requireValue(bytesRead <= SNAPSHOT_LIMITS.bytes && sha256(bytes) === document.sha256, 'Snapshot document altered or over budget');
      return {source: document.source, bytes};
    });
    const bundle = JSON.parse(readSource(root, `website/versioned_examples/version-${version}.json`, 1024 * 1024).toString());
    requireValue(sha256(JSON.stringify(bundle)) === manifest.examplesSha256, 'Snapshot example bundle altered');
    validateBundle(bundle, manifest, documents);
    requireValue(JSON.stringify(JSON.parse(readSource(root, `website/versioned_sidebars/version-${version}-sidebars.json`).toString())) === JSON.stringify(manifest.sidebars), 'Snapshot sidebar altered');
    requireValue(Array.isArray(manifest.assets) && manifest.assets.length <= 100, 'Snapshot asset budget');
    const assets = manifest.assets.map(asset => {
      const file = `website/versioned_assets/version-${version}/${canonicalPath(asset.path)}`;
      requireValue(!expectedFiles.has(file), 'Duplicate snapshot asset');
      expectedFiles.add(file);
      requireValue(asset.maxBytes <= 65536 && sha256(readSource(root, file, asset.maxBytes)) === asset.sha256, 'Snapshot asset altered');
      return {...asset, channel: version, file};
    });
    const index = snapshotIndex(root, manifest, documents, currentPaths);
    return {manifest, index, assets, examples: {bundle, identity: {inputDigest: bundle.inputDigest, bundleSha256: manifest.examplesSha256}}};
  });
  const actualFiles = currentPaths.filter(file => /^website\/versioned_(docs|examples|assets|sidebars|manifests)\//.test(file));
  requireValue(actualFiles.length === expectedFiles.size && actualFiles.every(file => expectedFiles.has(file)), 'Unregistered or missing snapshot file');
  return snapshots;
}
