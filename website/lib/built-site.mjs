import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {parse, parseFragment} from 'parse5';
import {visit} from 'unist-util-visit';
import {assetRoute, createRepositoryIndex, git, htmlElements, parseDocument, readSource, repositoryRoot, repositoryUrl, requireValue, resolveLink, sha256} from './repository.mjs';
import {transformDocument} from '../plugins/repository-links.mjs';
import {validateExampleBuild} from '../plugins/examples/built.mjs';
import {loadSnapshots} from './versions/storage.mjs';
import {documentBytes} from './versions/model.mjs';

function expectedSourceLinks(index, page, manifest) {
  const options = {baseUrl: manifest.baseUrl, assets: manifest.assets.filter(asset => (asset.channel ?? 'development') === index.channel)};
  const tree = transformDocument(parseDocument(documentBytes(index, page.source).toString('utf8'), page.source), index, page.source, options);
  const links = new Set();
  function collect(url) {
    if (url?.startsWith(`${repositoryUrl}/blob/`) || url?.startsWith(`${repositoryUrl}/tree/`)) links.add(url);
  }
  visit(tree, node => {
    if (node.type === 'link') collect(node.url);
    for (const attribute of node.attributes ?? []) if (attribute.name === 'href') collect(attribute.value);
    if (node.type === 'html') htmlElements(parseFragment(node.value), element => {
      for (const attribute of element.attrs ?? []) if (attribute.name === 'href') collect(resolveLink(index, page.source, attribute.value, options));
    });
  });
  return links;
}

export function validatePublicJavaScript(output) {
  const directory = path.join(output, 'assets/js');
  let bytes = 0;
  const files = fs.readdirSync(directory).filter(filename => filename.endsWith('.js'));
  requireValue(files.length > 0 && files.length <= 2000, 'Invalid public JavaScript inventory');
  for (const filename of files) {
    const target = path.join(directory, filename);
    requireValue(fs.statSync(target).size <= 8 * 1024 * 1024, 'Public JavaScript file size limit');
    const content = fs.readFileSync(target, 'utf8');
    bytes += Buffer.byteLength(content);
    requireValue(bytes <= 64 * 1024 * 1024, 'Public JavaScript corpus size limit');
    const privateRoots = [repositoryRoot, repositoryRoot.split(path.sep).join('/')];
    requireValue(!privateRoots.some(root => content.includes(JSON.stringify(root).slice(1, -1))), `Private build path leaked into public JavaScript: ${filename}`);
  }
  return {files: files.length, bytes};
}

function outputPath(output, pathname, baseUrl) {
  requireValue(pathname.startsWith(baseUrl), `Built URL escaped its base path: ${pathname}`);
  const decoded = decodeURIComponent(pathname.slice(baseUrl.length));
  requireValue(!decoded.includes('\\') && !decoded.split('/').includes('..'), 'Unsafe built path');
  const target = path.join(output, ...decoded.split('/').filter(Boolean));
  const relative = path.relative(output, target);
  requireValue(!relative.startsWith('..') && !path.isAbsolute(relative), 'Built path escape');
  return pathname.endsWith('/') ? path.join(target, 'index.html') : target;
}

export function validateBuiltSite(output) {
  const manifest = JSON.parse(fs.readFileSync(path.join(output, 'site-manifest.json'), 'utf8'));
  const current = createRepositoryIndex();
  const snapshots = loadSnapshots(repositoryRoot, current.paths);
  const dirty = git(repositoryRoot, 'status', '--porcelain=v1', '--untracked-files=all').trim().length > 0;
  requireValue(manifest.revision === current.revision && manifest.dirty === dirty, 'Built source identity is stale; rebuild this checkout');
  const pages = [...current.pages, ...snapshots.flatMap(snapshot => snapshot.index.pages)];
  requireValue(JSON.stringify(manifest.pages) === JSON.stringify(pages), 'Built document bytes/routes are stale; rebuild this checkout');
  requireValue(JSON.stringify(manifest.versions?.map(version => version.snapshotIdentity) ?? [])
    === JSON.stringify(snapshots.map(snapshot => snapshot.manifest.snapshotIdentity)), 'Built publication identities are stale');
  let checkedExamples = validateExampleBuild(output, current, manifest);
  for (const snapshot of snapshots) checkedExamples += validateExampleBuild(output, snapshot.index, {examples: snapshot.examples.identity}, snapshot.examples);
  const publicJavaScript = validatePublicJavaScript(output);
  const documents = new Map();
  let checkedSourceLinks = 0;
  const requiredRoutes = ['/', ...manifest.pages.map(page => page.route)];
  for (const route of requiredRoutes) {
    const target = outputPath(output, `${manifest.baseUrl.slice(0, -1)}${route}`, manifest.baseUrl);
    requireValue(fs.statSync(target).size <= 4 * 1024 * 1024, 'Built page size limit');
    const html = fs.readFileSync(target, 'utf8');
    const identifiers = new Set();
    const links = [];
    htmlElements(parse(html), element => {
      for (const attribute of element.attrs ?? []) {
        if (attribute.name === 'id' || (element.tagName === 'a' && attribute.name === 'name')) identifiers.add(attribute.value);
        if (['href', 'src'].includes(attribute.name)) links.push(attribute.value);
      }
    });
    documents.set(route, {identifiers, links});
    const page = manifest.pages.find(entry => entry.route === route);
    if (page) {
      const index = page.channel ? snapshots.find(snapshot => snapshot.index.channel === page.channel)?.index : current;
      requireValue(index, 'Missing built document version');
      requireValue(links.includes(`${repositoryUrl}/edit/${index.revision}/${page.source}`), `Missing exact-revision edit link: ${page.source}`);
      for (const expected of expectedSourceLinks(index, page, manifest)) {
        requireValue(links.includes(expected), `Missing or stale commit-bound source link: ${page.source}`);
        checkedSourceLinks += 1;
      }
    }
  }
  let checkedLinks = 0;
  for (const [route, document] of documents) {
    const location = new URL(`${manifest.baseUrl.slice(0, -1)}${route}`, 'http://127.0.0.1');
    for (const link of document.links) {
      if (!link || /^(https?:|mailto:|data:)/.test(link)) continue;
      const targetUrl = new URL(link, location);
      requireValue(targetUrl.origin === location.origin, 'Unexpected built URL scheme');
      const target = outputPath(output, targetUrl.pathname, manifest.baseUrl);
      requireValue(fs.existsSync(target), `Missing built target from ${route}: ${targetUrl.pathname}`);
      if (targetUrl.hash && target.endsWith('index.html')) {
        const targetRoute = `/${targetUrl.pathname.slice(manifest.baseUrl.length)}`;
        requireValue(documents.get(targetRoute)?.identifiers.has(decodeURIComponent(targetUrl.hash.slice(1))), `Missing built anchor from ${route}: ${targetUrl.pathname}${targetUrl.hash}`);
      }
      checkedLinks += 1;
    }
  }
  for (const asset of manifest.assets) {
    const target = path.join(output, ...assetRoute(asset).split('/').filter(Boolean));
    requireValue(sha256(fs.readFileSync(target)) === asset.sha256, `Copied asset changed bytes: ${asset.path}`);
    requireValue(sha256(readSource(repositoryRoot, asset.file ?? asset.path, asset.maxBytes)) === asset.sha256, `Built asset input is stale: ${asset.path}`);
  }
  return {manifest, pages: documents.size, checkedLinks, checkedSourceLinks, checkedExamples, publicJavaScript};
}

export async function serveBuiltSite(output, baseUrl) {
  const types = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.json': 'application/json', '.woff2': 'font/woff2', '.png': 'image/png', '.txt': 'text/plain'};
  const server = http.createServer((request, response) => {
    try {
      if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405).end(); return; }
      const url = new URL(request.url, 'http://127.0.0.1');
      const target = outputPath(output, url.pathname, baseUrl);
      if (!fs.existsSync(target) || !fs.lstatSync(target).isFile() || fs.lstatSync(target).isSymbolicLink()) { response.writeHead(404).end(); return; }
      response.writeHead(200, {'Content-Type': types[path.extname(target)] ?? 'application/octet-stream', 'X-Content-Type-Options': 'nosniff'});
      if (request.method === 'HEAD') response.end();
      else fs.createReadStream(target).pipe(response);
    } catch { response.writeHead(404).end(); }
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 5000;
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {origin: `http://127.0.0.1:${server.address().port}`, close: async () => {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }};
}
