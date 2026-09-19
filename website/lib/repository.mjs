import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {unified} from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkMdx from 'remark-mdx';
import {visit} from 'unist-util-visit';
import {toString} from 'mdast-util-to-string';
import GithubSlugger from 'github-slugger';
import {parseFragment} from 'parse5';
import {parse as parseYaml} from 'yaml';

export const websiteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const repositoryRoot = path.dirname(websiteRoot);
export const repositoryUrl = 'https://github.com/KirilsTurkins/latent-service-fabric';
export const maxSourceBytes = 2 * 1024 * 1024;

export function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

export function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

export function git(root, ...args) {
  return execFileSync('git', ['-c', 'gc.auto=0', ...args], {
    cwd: root, encoding: 'utf8', timeout: 15000, maxBuffer: 8 * 1024 * 1024,
    env: {...process.env, GIT_NO_REPLACE_OBJECTS: '1', GIT_NO_LAZY_FETCH: '1', GIT_TERMINAL_PROMPT: '0'},
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

export function trackedPaths(root) {
  const names = [...new Set(git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split('\0').filter(Boolean))].sort();
  requireValue(names.length > 0 && names.length <= 20000, 'Repository path count exceeds the finite inventory');
  return names;
}

export function canonicalPath(relative) {
  requireValue(typeof relative === 'string' && relative.length > 0 && relative.length <= 1024, 'Invalid repository path');
  requireValue(!/[\\:\x00-\x1f]/.test(relative) && !relative.startsWith('/'), 'Unsafe repository path');
  requireValue(relative.split('/').every(part => part && part !== '.' && part !== '..'), 'Noncanonical repository path');
  return relative;
}

export function safeFile(root, relative, limit = maxSourceBytes) {
  canonicalPath(relative);
  let current = fs.realpathSync(root);
  for (const segment of relative.split('/')) {
    requireValue(fs.readdirSync(current).includes(segment), `Missing or incorrectly cased path: ${relative}`);
    current = path.join(current, segment);
    const metadata = fs.lstatSync(current);
    requireValue(!metadata.isSymbolicLink(), `Linked input is not allowed: ${relative}`);
    const resolved = path.relative(fs.realpathSync(root), fs.realpathSync(current));
    requireValue(resolved !== '..' && !resolved.startsWith(`..${path.sep}`) && !path.isAbsolute(resolved), `Repository escape: ${relative}`);
  }
  const metadata = fs.statSync(current);
  requireValue(metadata.isFile() && metadata.size <= limit, `Nonregular or oversized input: ${relative}`);
  return current;
}

export function readSource(root, relative, limit = maxSourceBytes) {
  const bytes = fs.readFileSync(safeFile(root, relative, limit));
  requireValue(bytes.length <= limit, `Input grew beyond its limit: ${relative}`);
  return bytes;
}

export function parseDocument(text, source) {
  const processor = unified().use(remarkParse).use(remarkGfm);
  if (source.endsWith('.mdx')) processor.use(remarkMdx);
  const header = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(text);
  const frontMatter = header ? parseYaml(header[1], {uniqueKeys: true, maxAliasCount: 20}) : {};
  requireValue(frontMatter && typeof frontMatter === 'object' && !Array.isArray(frontMatter), `Invalid front matter: ${source}`);
  requireValue(frontMatter.format === undefined || frontMatter.format === 'detect' || frontMatter.format === (source.endsWith('.mdx') ? 'mdx' : 'md'), `Front matter cannot change the file execution mode: ${source}`);
  requireValue(!frontMatter.draft && !frontMatter.unlisted && frontMatter.custom_edit_url === undefined, `Draft/hidden/custom-edit overrides require a publication-contract review: ${source}`);
  const tree = processor.parse(header ? text.slice(header[0].length) : text);
  tree.frontMatter = frontMatter;
  return tree;
}

export function htmlElements(node, callback) {
  if (node.tagName) callback(node);
  for (const child of node.childNodes ?? []) htmlElements(child, callback);
}

export function documentMetadata(text, source) {
  const tree = parseDocument(text, source);
  const slugger = new GithubSlugger();
  const anchors = [];
  let title = '';
  visit(tree, node => {
    if (node.type === 'heading') {
      const label = toString(node);
      if (!title) title = label;
      anchors.push(slugger.slug(label));
    }
    if (node.type === 'html') {
      htmlElements(parseFragment(node.value), element => {
        for (const attribute of element.attrs ?? []) {
          if (attribute.name === 'id' || (element.tagName === 'a' && attribute.name === 'name')) anchors.push(attribute.value);
        }
      });
    }
  });
  return {title: tree.frontMatter.title || title || path.posix.basename(source), anchors: [...new Set(anchors)], frontMatter: tree.frontMatter};
}

export function routeFor(source, frontMatter = {}) {
  canonicalPath(source);
  const [root, ...parts] = source.split('/');
  requireValue((root === 'docs' || root === 'adr') && /\.mdx?$/.test(source) && parts[0] !== 'wiki', `Not a published document: ${source}`);
  const basename = parts.pop().replace(/\.mdx?$/, '');
  const category = parts.at(-1)?.toLowerCase();
  const index = ['readme', 'index', category].includes(basename.toLowerCase());
  let segments = [...parts, ...(index ? [] : [frontMatter.id ?? basename])];
  if (frontMatter.slug !== undefined) {
    requireValue(typeof frontMatter.slug === 'string', `Invalid slug in ${source}`);
    const override = frontMatter.slug.replace(/^\//, '').replace(/\/$/, '');
    if (override) canonicalPath(override);
    segments = [...(frontMatter.slug.startsWith('/') ? [] : parts), ...override.split('/').filter(Boolean)];
  }
  const slug = segments.map(encodeURIComponent).join('/');
  return `/${root === 'docs' ? 'docs' : 'decisions'}/${slug}${slug ? '/' : ''}`;
}

export function basePath(value = '/latent-service-fabric/') {
  requireValue(/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(value), 'Base path must be an absolute slash-terminated path without traversal');
  return value;
}

export function createRepositoryIndex(root = repositoryRoot, paths = trackedPaths(root), revision = git(root, 'rev-parse', 'HEAD').trim()) {
  requireValue(/^[a-f0-9]{40}$/.test(revision), 'An exact Git commit is required');
  const directories = new Set();
  const spellings = new Set();
  const pages = [];
  const routes = new Set();
  let bytesRead = 0;
  for (const source of paths) {
    canonicalPath(source);
    requireValue(!spellings.has(source.toLowerCase()), `Case-colliding repository input: ${source}`);
    spellings.add(source.toLowerCase());
    const parts = source.split('/');
    for (let length = 1; length < parts.length; length += 1) directories.add(parts.slice(0, length).join('/'));
    if (!/^(docs|adr)\/.+\.mdx?$/.test(source) || source.startsWith('docs/wiki/')) continue;
    const bytes = readSource(root, source);
    bytesRead += bytes.length;
    requireValue(bytesRead <= 32 * 1024 * 1024, 'Documentation corpus exceeds its build-input budget');
    const text = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
    const metadata = documentMetadata(text, source);
    const route = routeFor(source, metadata.frontMatter);
    requireValue(!routes.has(route.toLowerCase()), `Published route collision: ${route}`);
    routes.add(route.toLowerCase());
    const sourceId = source.replace(/^(docs|adr)\//, '').replace(/\.mdx?$/, '');
    const id = metadata.frontMatter.id === undefined ? sourceId : path.posix.join(path.posix.dirname(sourceId), metadata.frontMatter.id);
    requireValue(typeof id === 'string' && !id.includes('..'), `Invalid document id: ${source}`);
    pages.push({source, route, id, sha256: sha256(bytes), title: metadata.title, anchors: metadata.anchors});
  }
  requireValue(pages.length > 0 && pages.length <= 2000, 'Invalid published page count');
  return {schema: 1, channel: 'development', root, revision, paths, directories: [...directories].sort(), pages};
}

export function sourceUrl(index, source, directory = false) {
  canonicalPath(source);
  return `${repositoryUrl}/${directory ? 'tree' : 'blob'}/${index.revision}/${source.split('/').map(encodeURIComponent).join('/')}`;
}

export function assetRoute(asset, channel = 'development') {
  if (asset.kind === 'brand') return `/brand/${asset.sha256}/${encodeURIComponent(path.posix.basename(asset.path))}`;
  return `/content-assets/${channel}/${asset.sha256}/${encodeURIComponent(path.posix.basename(asset.path))}`;
}

export function resolveLink(index, source, url, {baseUrl = '/latent-service-fabric/', assets = [], image = false} = {}) {
  basePath(baseUrl);
  requireValue(typeof url === 'string' && !/[\\\x00-\x1f]/.test(url), `Unsafe URL in ${source}`);
  const sourcePrefix = `${repositoryUrl}/`;
  if (url.startsWith(sourcePrefix)) {
    const moving = /^(?:blob|tree)\/(?:development|release)\/(.+)$/.exec(url.slice(sourcePrefix.length));
    if (moving) return resolveLink(index, source, `/${moving[1]}`, {baseUrl, assets, image});
  }
  if (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(url) || url.startsWith('//')) {
    requireValue(!image && /^(https?:|mailto:)/.test(url) && !url.startsWith('//'), `Remote image or unsafe URL scheme in ${source}`);
    return url;
  }
  const match = /^([^?#]*)(\?[^#]*)?(#.*)?$/.exec(url);
  requireValue(match, `Malformed URL in ${source}`);
  const [, rawPath, query = '', fragment = ''] = match;
  const sitePage = index.pages.find(entry => `${baseUrl.slice(0, -1)}${entry.route}` === rawPath);
  if (sitePage) {
    requireValue(!image, `Documents are not approved image assets: ${source}`);
    if (fragment) requireValue(sitePage.anchors.includes(decodeURIComponent(fragment.slice(1))), `Missing site anchor: ${url}`);
    return url;
  }
  const siteAsset = assets.find(entry => `${baseUrl.slice(0, -1)}${assetRoute(entry)}` === rawPath);
  if (siteAsset) {
    requireValue(!image || siteAsset.kind !== 'download', `Download is not an approved image: ${source}`);
    return url;
  }
  requireValue(!/%(?:2f|5c|00)/i.test(rawPath), `Encoded path separator in ${source}`);
  const decoded = decodeURIComponent(rawPath);
  requireValue(!decoded.split('/').some(part => (part === '..' || part === '.') && /%2e/i.test(rawPath)), `Encoded traversal in ${source}`);
  const relative = (rawPath ? path.posix.normalize(decoded.startsWith('/') ? decoded.slice(1) : path.posix.join(path.posix.dirname(source), decoded)) : source).replace(/\/$/, '');
  if (relative === '.') {
    requireValue(!image, `Repository roots are not image assets: ${source}`);
    return `${repositoryUrl}/tree/${index.revision}${query}${fragment}`;
  }
  canonicalPath(relative);
  const page = index.pages.find(entry => entry.source === relative);
  const isDirectory = index.directories.includes(relative);
  requireValue(index.paths.includes(relative) || isDirectory, `Missing or incorrectly cased link from ${source}: ${relative}`);
  if (!isDirectory) safeFile(index.root, relative, Number.POSITIVE_INFINITY);
  if (fragment && page) requireValue(page.anchors.includes(decodeURIComponent(fragment.slice(1))), `Missing anchor from ${source}: ${relative}${fragment}`);
  const asset = assets.find(entry => entry.path === relative);
  if (fragment && !page && !asset && !isDirectory) {
    const anchor = decodeURIComponent(fragment.slice(1));
    if (/\.mdx?$/.test(relative)) {
      requireValue(documentMetadata(readSource(index.root, relative).toString('utf8'), relative).anchors.includes(anchor), `Missing repository Markdown anchor: ${relative}${fragment}`);
    } else {
      const lines = /^L([1-9][0-9]*)(?:-L([1-9][0-9]*))?$/.exec(anchor);
      requireValue(lines, `Unsupported source-file anchor: ${relative}${fragment}`);
      const count = readSource(index.root, relative).toString('utf8').trimEnd().split('\n').length;
      requireValue(Number(lines[1]) <= Number(lines[2] ?? lines[1]) && Number(lines[2] ?? lines[1]) <= count, `Missing source line: ${relative}${fragment}`);
    }
  }
  if (image) requireValue(asset && asset.kind !== 'download', `Image is not individually approved: ${relative}`);
  if (asset) return `${baseUrl.slice(0, -1)}${assetRoute(asset)}${query}${fragment}`;
  if (page) return `${baseUrl.slice(0, -1)}${page.route}${query}${fragment}`;
  return `${sourceUrl(index, relative, isDirectory)}${query}${fragment}`;
}

export function validateAssets(root, policy, index) {
  requireValue(policy.schema === 1 && Array.isArray(policy.assets) && policy.assets.length <= 100, 'Invalid approved asset inventory');
  const seen = new Set();
  return policy.assets.map(entry => {
    canonicalPath(entry.path);
    requireValue(!seen.has(entry.path) && index.paths.includes(entry.path), `Missing or duplicate approved asset: ${entry.path}`);
    seen.add(entry.path);
    const illustration = /^docs\/assets\/[a-z0-9-]+\.svg$/.test(entry.path) && entry.kind === 'illustration'
      || /^website\/static\/brand\/[a-z0-9-]+\.svg$/.test(entry.path) && entry.kind === 'brand';
    const download = /^docs\/assets\/[a-z0-9-]+\.(txt|json)$/.test(entry.path) && entry.kind === 'download';
    requireValue(illustration || download, `Unapproved asset root/type: ${entry.path}`);
    requireValue(Number.isInteger(entry.maxBytes) && entry.maxBytes > 0 && entry.maxBytes <= 262144, 'Invalid asset budget/kind');
    const bytes = readSource(root, entry.path, entry.maxBytes);
    const text = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
    if (illustration) requireValue(!/<(?:[A-Za-z0-9_-]+:)?(?:script|foreignObject|iframe|image|object|embed)\b|\bon[a-z]+\s*=|(?:href|src)\s*=\s*["'](?!#)|url\(\s*["']?(?!#)[a-z]|@import|<!ENTITY|<!DOCTYPE/i.test(text), `Active or external SVG content: ${entry.path}`);
    return {...entry, sha256: sha256(bytes), bytes: bytes.length};
  });
}
