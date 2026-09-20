import fs from 'node:fs';
import path from 'node:path';
import {parse} from 'parse5';
import MiniSearch from 'minisearch';
import {SEARCH_LIMITS, searchOptions} from './search.mjs';
import {htmlElements, requireValue} from './repository.mjs';

const attribute = (node, name) => node.attrs?.find(item => item.name === name)?.value;
function text(node) {
  if (['script', 'style', 'button', 'nav'].includes(node.tagName) || attribute(node, 'aria-hidden') === 'true') return '';
  if (node.nodeName === '#text') return node.value;
  return (node.childNodes ?? []).map(text).join(' ');
}
const normalize = value => value.replace(/\s+/g, ' ').trim();

export function pageRecords(html, page, profile) {
  const tree = parse(html);
  let content;
  let excluded = false;
  htmlElements(tree, node => {
    if (node.tagName === 'meta' && attribute(node, 'name')?.toLowerCase() === 'robots'
      && /(?:^|,)\s*noindex\b/i.test(attribute(node, 'content') ?? '')) excluded = true;
    if (attribute(node, 'class')?.split(' ').includes('theme-doc-markdown')) content = node;
  });
  if (excluded) return [];
  requireValue(content, `Missing rendered search content: ${page.route}`);
  const sections = [{heading: page.title, anchor: '', text: ''}];
  for (const node of content.childNodes ?? []) {
    if (/^h[2-6]$/.test(node.tagName ?? '')) sections.push({heading: normalize(text(node)), anchor: attribute(node, 'id') ?? '', text: ''});
    else sections.at(-1).text += ` ${text(node)}`;
  }
  const records = [];
  for (const section of sections) {
    const value = normalize(section.text);
    requireValue(value.length <= 256 * 1024, `Search section exceeds its reviewed limit: ${page.route}`);
    for (let start = 0; start < Math.max(value.length, 1); start += 6000) {
      const chunk = value.slice(start, start + 6000);
      records.push({title: page.title, heading: section.heading, route: page.route + (section.anchor ? `#${encodeURIComponent(section.anchor)}` : ''),
        version: page.channel ?? 'development', profile, text: chunk, excerpt: chunk.slice(0, 180)});
    }
  }
  return records;
}

export function searchDocument(output, manifest) {
  const profiles = new Map([['development', 'Development; Phase 3 work in progress'], ...manifest.versions.map(version => [version.version, `${version.runtimeVersion} / ${version.profile}`])]);
  const records = [];
  let indexedPages = 0;
  for (const page of manifest.pages) {
    const filename = path.join(output, ...decodeURIComponent(page.route).split('/').filter(Boolean), 'index.html');
    requireValue(fs.statSync(filename).size <= 4 * 1024 * 1024, 'Oversized search HTML input');
    const selected = pageRecords(fs.readFileSync(filename, 'utf8'), page, profiles.get(page.channel ?? 'development'));
    if (selected.length) indexedPages++;
    records.push(...selected);
    requireValue(records.length <= SEARCH_LIMITS.records, 'Search record budget exceeded');
  }
  const index = new MiniSearch(searchOptions);
  index.addAll(records.map((record, id) => ({id, ...record})));
  const document = {schema: 1, sourceRevision: manifest.revision, baseUrl: manifest.baseUrl,
    channels: [...profiles.keys()], indexedPages, records: records.length, index: JSON.stringify(index)};
  const json = JSON.stringify(document);
  requireValue(Buffer.byteLength(json) <= SEARCH_LIMITS.bytes, 'Search index exceeds its reviewed byte budget');
  return {json, indexedPages, records: records.length, bytes: Buffer.byteLength(json)};
}

export function buildSearch(output, manifest) {
  const {json, ...receipt} = searchDocument(output, manifest);
  fs.writeFileSync(path.join(output, 'search-index.json'), json + '\n');
  return receipt;
}

export function validateSearch(output, manifest) {
  const filename = path.join(output, 'search-index.json');
  requireValue(fs.statSync(filename).size <= SEARCH_LIMITS.bytes, 'Search index exceeds its reviewed byte budget');
  const {json, ...receipt} = searchDocument(output, manifest);
  requireValue(fs.readFileSync(filename, 'utf8') === json + '\n', 'Search index differs from the actual built pages or publication identity');
  return receipt;
}
