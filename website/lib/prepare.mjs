import fs from 'node:fs';
import path from 'node:path';
import {assetRoute, basePath, createRepositoryIndex, git, parseDocument, readSource, repositoryRoot, requireValue, sha256, validateAssets, websiteRoot} from './repository.mjs';
import {validateCoverage} from './coverage.mjs';
import {transformDocument} from '../plugins/repository-links.mjs';
import {prepareExamples} from '../plugins/examples/site.mjs';

let cached;

export function generatedDirectory(relative) {
  requireValue(/^\.generated\/[A-Za-z0-9_/-]+$/.test(relative) && !relative.includes('..'), 'Invalid generated directory');
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
  const assets = validateAssets(repositoryRoot, policy, index);
  const coverage = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/coverage.json'), 'utf8'));
  const coverageResult = validateCoverage(coverage, index, {acceptance});
  for (const page of index.pages) {
    const source = readSource(repositoryRoot, page.source).toString('utf8');
    try {
      transformDocument(parseDocument(source, page.source), index, page.source, {baseUrl, assets});
    } catch (error) {
      throw new Error(`${page.source}: ${error.message}`, {cause: error});
    }
  }
  const examples = prepareExamples(index);
  const assetIdentity = sha256(JSON.stringify(assets));
  const staticDirectory = generatedDirectory(`.generated/assets/${assetIdentity}`);
  for (const asset of assets) {
    const relative = `.generated/assets/${assetIdentity}${assetRoute(asset)}`;
    const parent = generatedDirectory(path.posix.dirname(relative));
    const destination = path.join(parent, path.posix.basename(relative));
    if (fs.existsSync(destination)) {
      requireValue(!fs.lstatSync(destination).isSymbolicLink() && sha256(fs.readFileSync(destination)) === asset.sha256, 'Generated asset collision or alteration');
    } else fs.writeFileSync(destination, readSource(repositoryRoot, asset.path, asset.maxBytes), {flag: 'wx'});
  }
  const dirty = git(repositoryRoot, 'status', '--porcelain=v1', '--untracked-files=all').trim().length > 0;
  const manifest = {schema: 1, channel: 'development', revision: index.revision, dirty, baseUrl, pages: index.pages, assets, examples: examples.identity, coverage: coverageResult, excludedWikiPaths: index.paths.filter(source => source.startsWith('docs/wiki/')).length};
  cached = {index, assets, examples, manifest, staticDirectory, baseUrl};
  return cached;
}
