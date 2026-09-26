import {parseDocument, readSource} from '../../lib/repository.mjs';
import {extractExamples} from './extract.mjs';
import {digest, writeSnapshot} from './io.mjs';
import {requestsFromTree} from './remark.mjs';

export function prepareExamples(index, {persist = true} = {}) {
  const requests = index.pages.flatMap(page => requestsFromTree(parseDocument(readSource(index.root, page.source).toString('utf8'), page.source)));
  const result = extractExamples(index.root, requests, {documentVersion: index.channel,
    documentationRevision: index.revision, sourceRevision: index.revision});
  if (persist) writeSnapshot(index.root, result.bundle);
  return {...result, identity: {inputDigest: result.bundle.inputDigest, bundleSha256: digest(JSON.stringify(result.bundle))}};
}
