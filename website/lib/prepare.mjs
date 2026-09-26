import fs from 'node:fs';
import path from 'node:path';
import {assetRoute, basePath, createRepositoryIndex, git, parseDocument, readSource, repositoryRoot, requireValue, sha256, validateAssets, websiteRoot} from './repository.mjs';
import {validateCoverage} from './coverage.mjs';
import {transformDocument} from '../plugins/repository-links.mjs';
import {prepareExamples} from '../plugins/examples/site.mjs';
import {loadSnapshots} from './versions/storage.mjs';
import {documentBytes} from './versions/model.mjs';

let cached;

export function generatedDirectory(relative) {
  requireValue(/^\.generated\/[A-Za-z0-9._/-]+$/.test(relative)
    && relative.split('/').slice(1).every(segment => segment && segment !== '.' && segment !== '..'), 'Invalid generated directory');
  let current = fs.realpathSync(websiteRoot);
  for (const segment of relative.split('/')) {
    current = path.join(current, segment);
    if (fs.existsSync(current)) requireValue(fs.lstatSync(current).isDirectory() && !fs.lstatSync(current).isSymbolicLink(), 'Linked/non-directory generated path');
    else fs.mkdirSync(current);
  }
  return current;
}

export function prepare({baseUrl = process.env.LSF_SITE_BASE_URL ?? '/latent-service-fabric/', acceptance = false} = {}) {
  basePath(baseUrl);
  if (cached && cached.baseUrl === baseUrl && !acceptance) return cached;
  const index = createRepositoryIndex();
  const policy = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/assets.json'), 'utf8'));
  const currentAssets = validateAssets(repositoryRoot, policy, index);
  const snapshots = loadSnapshots(repositoryRoot, index.paths);
  const assets = [...currentAssets, ...snapshots.flatMap(snapshot => snapshot.assets)];
  const coverage = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/coverage.json'), 'utf8'));
  const coverageResult = validateCoverage(coverage, index, {acceptance});
  for (const page of index.pages) {
    const source = readSource(repositoryRoot, page.source).toString('utf8');
    try {
      transformDocument(parseDocument(source, page.source), index, page.source, {baseUrl, assets: currentAssets});
    } catch (error) {
      throw new Error(`${page.source}: ${error.message}`, {cause: error});
    }
  }
  const examples = prepareExamples(index);
  for (const snapshot of snapshots) for (const page of snapshot.index.pages) {
    transformDocument(parseDocument(documentBytes(snapshot.index, page.source).toString('utf8'), page.source), snapshot.index, page.source,
      {baseUrl, assets: snapshot.assets});
  }
  const assetIdentity = sha256(JSON.stringify(assets));
  const staticDirectory = generatedDirectory(`.generated/assets/${assetIdentity}`);
  for (const asset of assets) {
    const relative = `.generated/assets/${assetIdentity}${assetRoute(asset)}`;
    const parent = generatedDirectory(path.posix.dirname(relative));
    const destination = path.join(parent, path.posix.basename(relative));
    if (fs.existsSync(destination)) {
      requireValue(!fs.lstatSync(destination).isSymbolicLink() && sha256(fs.readFileSync(destination)) === asset.sha256, 'Generated asset collision or alteration');
    } else fs.writeFileSync(destination, readSource(repositoryRoot, asset.file ?? asset.path, asset.maxBytes), {flag: 'wx'});
  }
  const dirty = git(repositoryRoot, 'status', '--porcelain=v1', '--untracked-files=all').trim().length > 0;
  const versions = snapshots.map(({manifest: snapshot}) => ({version: snapshot.version, runtimeVersion: snapshot.runtimeVersion,
    runtimeSource: snapshot.runtimeSource, documentationSource: snapshot.documentationSource, exampleSource: snapshot.exampleSource,
    snapshotIdentity: snapshot.snapshotIdentity, profile: snapshot.profile, verification: snapshot.verification, examplesSha256: snapshot.examplesSha256}));
  const manifest = {schema: 1, channel: 'development', revision: index.revision, dirty, baseUrl,
    pages: [...index.pages, ...snapshots.flatMap(snapshot => snapshot.index.pages)], assets, examples: examples.identity, versions,
    coverage: coverageResult, excludedWikiPaths: index.paths.filter(source => source.startsWith('docs/wiki/')).length};
  cached = {index, assets, currentAssets, examples, snapshots, manifest, staticDirectory, baseUrl};
  return cached;
}
