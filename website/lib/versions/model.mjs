import {canonicalPath, documentMetadata, readSource, requireValue, routeFor, sha256} from '../repository.mjs';
import {resolveExample} from '../../plugins/examples/resolve.mjs';
import {parseDocument} from '../repository.mjs';
import {requestsFromTree} from '../../plugins/examples/remark.mjs';

export function versionId(value) {
  requireValue(typeof value === 'string' && /^[0-9][a-zA-Z0-9._-]{0,79}$/.test(value), 'Invalid snapshot version');
  return value;
}
export function snapshotHash(manifest) {
  const {snapshotIdentity, ...content} = manifest;
  return sha256(JSON.stringify(content));
}
export function documentBytes(index, source) {
  return readSource(index.root, index.documentFiles?.[source] ?? source);
}
export function fileSource(index, filename) {
  const normalized = filename.replaceAll('\\', '/');
  const root = index.root.replaceAll('\\', '/');
  const prefix = index.documentPrefix ? `${root}/${index.documentPrefix}/` : `${root}/`;
  requireValue(normalized.startsWith(prefix), 'Document is outside its selected version');
  return (index.documentPrefix ? 'docs/' : '') + normalized.slice(prefix.length);
}
export function snapshotIndex(root, manifest, documents, currentPaths = []) {
  const version = versionId(manifest.version);
  const prefix = `website/versioned_docs/version-${version}`;
  const documentFiles = {};
  const pages = documents.map(({source, bytes}) => {
    canonicalPath(source);
    requireValue(source.startsWith('docs/') && !source.startsWith('docs/wiki/') && /\.mdx?$/.test(source), 'Unapproved snapshot document');
    const metadata = documentMetadata(bytes.toString('utf8'), source);
    const route = routeFor(source, metadata.frontMatter).replace('/docs/', `/docs/${version}/`);
    const sourceId = source.slice(5).replace(/\.mdx?$/, '');
    requireValue(metadata.frontMatter.id === undefined, 'Snapshot custom document IDs require explicit migration');
    documentFiles[source] = `${prefix}/${source.slice(5)}`;
    return {source, route, id: sourceId, sha256: sha256(bytes), title: metadata.title, anchors: metadata.anchors,
      channel: version, revision: manifest.documentationSource};
  });
  requireValue(new Set(pages.map(page => page.route.toLowerCase())).size === pages.length, 'Snapshot route collision');
  const paths = manifest.repositoryPaths;
  requireValue(Array.isArray(paths) && paths.length > 0 && paths.length <= 20000, 'Snapshot path inventory limit');
  const directories = new Set();
  for (const source of paths) {
    canonicalPath(source);
    const segments = source.split('/');
    for (let length = 1; length < segments.length; length++) directories.add(segments.slice(0, length).join('/'));
  }
  return {schema: 1, snapshot: true, channel: version, revision: manifest.documentationSource,
    root, paths, directories: [...directories].sort(), pages, documentFiles, documentPrefix: prefix,
    componentPaths: currentPaths, linkMetadata: manifest.linkMetadata};
}
export function validateBundle(bundle, manifest, documents) {
  requireValue(bundle.schema === 1 && bundle.documentVersion === manifest.version
    && bundle.documentationRevision === manifest.documentationSource && bundle.sourceRevision === manifest.exampleSource
    && /^[a-f0-9]{64}$/.test(bundle.inputDigest) && Array.isArray(bundle.examples) && bundle.examples.length <= 64,
  'Snapshot example identity mismatch');
  for (const example of bundle.examples) for (const region of example.regions) for (const variant of region.variants) {
    requireValue(variant.source.revision === manifest.exampleSource && variant.source.matchesRevision === true
      && variant.snippet.sha256 === sha256(variant.snippet.code)
      && variant.source.url?.includes(`/blob/${manifest.exampleSource}/`), 'Snapshot example source or snippet mismatch');
  }
  for (const {source, bytes} of documents) {
    const requests = requestsFromTree(parseDocument(bytes.toString('utf8'), source));
    for (const request of requests) resolveExample(bundle, {...request, documentVersion: manifest.version});
  }
}
