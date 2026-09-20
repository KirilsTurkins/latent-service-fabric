import fs from 'node:fs';
import path from 'node:path';
import {parse} from 'parse5';
import {htmlElements, parseDocument, readSource, requireValue} from '../../lib/repository.mjs';
import {prepareExamples} from './site.mjs';
import {requestsFromTree} from './remark.mjs';
import {resolveExample} from './resolve.mjs';
import {documentBytes} from '../../lib/versions/model.mjs';

function nodeText(node) {
  if (node.nodeName === '#text') return node.value;
  // Docusaurus 3.10 renders highlighted code as token divs ending in <br>.
  // Preserve those rendered line boundaries as well as literal text newlines.
  if (node.tagName === 'br') return '\n';
  return (node.childNodes ?? []).map(nodeText).join('');
}
const displayed = code => code.replace(/\r\n/g, '\n').replace(/\n+$/, '');
export function verifyExampleHtml(html, bundle, requests) {
  const code = [], links = new Set();
  htmlElements(parse(html), element => {
    if (element.tagName === 'pre') code.push(displayed(nodeText(element)));
    for (const attribute of element.attrs ?? []) if (attribute.name === 'href') links.add(attribute.value);
  });
  let checked = 0;
  for (const request of requests) {
    const result = resolveExample(bundle, {...request, documentVersion: bundle.documentVersion});
    for (const variant of result.variants) {
      requireValue(code.includes(displayed(variant.snippet.code)), 'Missing or changed built example code');
      for (const url of [variant.source.url, variant.validation.target, variant.validation.instructions].filter(Boolean)) {
        requireValue(links.has(url), 'Missing commit-bound example source/validation link');
      }
      checked += 1;
    }
  }
  return checked;
}
export function validateExampleBuild(output, index, manifest, snapshotExamples) {
  const current = snapshotExamples ?? prepareExamples(index, {persist: false});
  requireValue(JSON.stringify(current.identity) === JSON.stringify(manifest.examples), 'Built example inputs are stale; rebuild this checkout');
  let checked = 0;
  for (const page of index.pages) {
    const requests = requestsFromTree(parseDocument(documentBytes(index, page.source).toString('utf8'), page.source));
    if (!requests.length) continue;
    const filename = path.join(output, ...decodeURIComponent(page.route).split('/').filter(Boolean), 'index.html');
    requireValue(fs.statSync(filename).size <= 4 * 1024 * 1024, 'Built example page size limit');
    checked += verifyExampleHtml(fs.readFileSync(filename, 'utf8'), current.bundle, requests);
  }
  return checked;
}
