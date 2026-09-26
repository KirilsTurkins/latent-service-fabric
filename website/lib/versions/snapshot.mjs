import {documentMetadata, parseDocument, requireValue, sha256, trackedPaths} from '../repository.mjs';
import {extractExamples, registryPath} from '../../plugins/examples/extract.mjs';
import {requestsFromTree} from '../../plugins/examples/remark.mjs';
import {transformDocument} from '../../plugins/repository-links.mjs';
import {revision} from '../../plugins/examples/io.mjs';
import {sourceReader, SNAPSHOT_LIMITS} from './git-source.mjs';
import {snapshotHash, snapshotIndex, validateBundle, versionId} from './model.mjs';
import {buildSidebars} from '../navigation.mjs';

export function createSnapshot(root, options, approvedAssets) {
  const {version, runtimeVersion, runtimeSource, documentationSource, exampleSource, profile} = options;
  versionId(version); versionId(runtimeVersion);
  for (const value of [runtimeSource, documentationSource, exampleSource]) revision(value);
  requireValue(typeof profile === 'string' && /^[a-z][a-z0-9-]{0,63}$/.test(profile), 'Invalid snapshot support profile');
  const reader = sourceReader(root, documentationSource, exampleSource);
  reader.tree(runtimeSource);
  const tree = reader.tree(documentationSource);
  const paths = [...tree.keys()].sort();
  const documents = paths.filter(name => /^docs\/(?!wiki\/).+\.mdx?$/.test(name)).map(source => ({source,
    bytes: reader.readAt(documentationSource, source).bytes}));
  requireValue(documents.length > 0 && documents.length <= SNAPSHOT_LIMITS.files, 'Snapshot document count limit');
  const requests = documents.flatMap(({source, bytes}) => requestsFromTree(parseDocument(bytes.toString('utf8'), source)));
  const bundle = reader.tree(exampleSource).has(registryPath)
    ? extractExamples(root, requests, {documentVersion: version, documentationRevision: documentationSource, sourceRevision: exampleSource}, {reader}).bundle
    : {schema: 1, documentVersion: version, documentationRevision: documentationSource, sourceRevision: exampleSource,
      inputDigest: sha256('[]'), examples: []};
  requireValue(approvedAssets.schema === 1 && Array.isArray(approvedAssets.assets) && approvedAssets.assets.length <= 100, 'Invalid snapshot asset allowlist');
  const assets = approvedAssets.assets.filter(asset => tree.has(asset.path)).map(asset => {
    requireValue(/^docs\/assets\/[a-zA-Z0-9_-]+\.svg$/.test(asset.path) && asset.kind === 'illustration'
      && Number.isSafeInteger(asset.maxBytes) && asset.maxBytes > 0 && asset.maxBytes <= 65536, 'Unapproved historical asset');
    const source = reader.readAt(documentationSource, asset.path, asset.maxBytes);
    requireValue(source.text.includes('<svg') && !/<(?:[A-Za-z0-9_-]+:)?(?:script|foreignObject|iframe|image|object|embed)\b|\bon[a-z]+\s*=|(?:href|src)\s*=\s*["'](?!#)|url\(\s*["']?(?!#)[a-z]|@import|<!ENTITY|<!DOCTYPE/i.test(source.text), 'Active historical SVG');
    return {...asset, sha256: source.sha256, bytes: source.bytes};
  });
  const manifest = {schema: 1, version, runtimeVersion, runtimeSource, documentationSource, exampleSource, profile,
    verification: 'Historical source snapshot; runtime evidence retains its original scope. Site checks do not qualify runtime behavior.',
    repositoryPaths: paths, linkMetadata: {}, documents: documents.map(({source, bytes}) => ({source, sha256: sha256(bytes)})),
    assets: assets.map(({bytes, ...asset}) => asset), examplesSha256: sha256(JSON.stringify(bundle)),
    sidebars: {}};
  const index = snapshotIndex(root, manifest, documents, trackedPaths(root));
  manifest.sidebars = buildSidebars(index.pages);
  index.inspectSource = source => {
    const input = reader.readAt(documentationSource, source);
    const metadata = {sha256: input.sha256, lines: input.text.trimEnd().split('\n').length,
      ...(/\.mdx?$/.test(source) ? {anchors: documentMetadata(input.text, source).anchors} : {})};
    manifest.linkMetadata[source] = metadata;
    return metadata;
  };
  for (const {source, bytes} of documents) transformDocument(parseDocument(bytes.toString('utf8'), source), index, source,
    {baseUrl: '/latent-service-fabric/', assets: assets.map(({bytes, ...asset}) => ({...asset, channel: version}))});
  validateBundle(bundle, manifest, documents);
  manifest.snapshotIdentity = snapshotHash(manifest);
  return {manifest, bundle, documents, assets};
}
