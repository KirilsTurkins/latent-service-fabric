import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {emptyErrorNavigation} from './empty-error-navigation.mjs';

// This controlled server qualifies the browser oracle. The following maintained
// signed-site workflow independently exercises the actual LSF node responses.
export async function qualifyEmptyErrorOracle(browser) {
  const cases = [
    {name: 'empty-not-found', status: 404, accepted: true},
    {name: 'empty-denied', status: 403, accepted: true},
    {name: 'nonempty-not-found', status: 404, body: '<title>Origin error</title>', reason: /origin error representation/},
    {name: 'nonempty-denied', status: 403, body: '<title>Origin denial</title>', reason: /origin error representation/},
    {name: 'wrong-status', status: 200, expected: 404, reason: /200 !== 404/},
    {name: 'cacheable-error', status: 404, cache: 'public, max-age=3600', reason: /no-store/},
    {name: 'missing-length', status: 404, missingLength: true, reason: /origin error representation/},
  ];
  let requests = 0;
  const server = createServer({requestTimeout: 5000, headersTimeout: 5000}, (request, response) => {
    if (++requests > 32) { response.writeHead(429).end(); return; }
    const selected = cases.find(value => '/' + value.name === request.url);
    if (!selected) { response.writeHead(404, {'Content-Length': '0'}).end(); return; }
    const fields = {'Content-Type': 'text/html', 'Cache-Control': selected.cache ?? 'private, no-store'};
    if (!selected.missingLength) fields['Content-Length'] = String(Buffer.byteLength(selected.body ?? ''));
    response.writeHead(selected.status, fields);
    response.end(selected.body ?? '');
  });
  server.maxConnections = 8;
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const watchdog = setTimeout(() => { process.exitCode = 1; browser?.close(); server.closeAllConnections(); }, 45000);
  try {
    const observations = [];
    for (const selected of cases) {
      const page = await browser.newPage();
      try {
        const target = `http://127.0.0.1:${server.address().port}/${selected.name}`;
        const action = () => emptyErrorNavigation(page, target, selected.expected ?? selected.status);
        if (selected.accepted) observations.push({name: selected.name, ...await action()});
        else {
          await assert.rejects(action, selected.reason);
          observations.push({name: selected.name, refused: true});
        }
      } finally { await page.close(); }
    }
    assert.equal(observations.length, 7);
    return {schemaVersion: 'latent.static.empty-error-oracle.v1',
      browser: browser.version(), node: process.version, observations};
  } finally {
    clearTimeout(watchdog);
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
}
