import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {parse} from 'parse5';
import {assetRoute, htmlElements, repositoryUrl, requireValue, sha256} from './repository.mjs';

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
  const documents = new Map();
  const requiredRoutes = ['/', ...manifest.pages.map(page => page.route)];
  for (const route of requiredRoutes) {
    const target = outputPath(output, `${manifest.baseUrl.slice(0, -1)}${route}`, manifest.baseUrl);
    requireValue(fs.statSync(target).size <= 4 * 1024 * 1024, 'Built page size limit');
    const html = fs.readFileSync(target, 'utf8');
    const identifiers = new Set();
    const links = [];
    htmlElements(parse(html), element => {
      for (const attribute of element.attrs ?? []) {
        if (attribute.name === 'id') identifiers.add(attribute.value);
        if (['href', 'src'].includes(attribute.name)) links.push(attribute.value);
      }
    });
    documents.set(route, {identifiers, links});
    const page = manifest.pages.find(entry => entry.route === route);
    if (page) requireValue(links.includes(`${repositoryUrl}/edit/${manifest.revision}/${page.source}`), `Missing exact-revision edit link: ${page.source}`);
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
    const target = path.join(output, ...assetRoute(asset, manifest.channel).split('/').filter(Boolean));
    requireValue(sha256(fs.readFileSync(target)) === asset.sha256, `Copied asset changed bytes: ${asset.path}`);
  }
  return {manifest, pages: documents.size, checkedLinks};
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
