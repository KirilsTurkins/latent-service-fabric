import assert from 'node:assert/strict';
import {createServer} from 'node:http';

// Real network pages and browser-generated Fetch Metadata. The source server
// only hosts links/forms; every target response comes from the running LSF node.
export async function publicNavigation(browser, strictOrigin) {
  const destination = new URL(strictOrigin);
  destination.hostname = 'docs.lsf.localhost';
  const origin = destination.origin;
  let requests = 0;
  const server = createServer({requestTimeout: 5000, headersTimeout: 5000}, (request, response) => {
    if (++requests > 64) { response.writeHead(429).end(); return; }
    response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'});
    response.end(`<!doctype html><title>Link source</title>
      <a id="root" href="${origin}/guide">Public root</a>
      <a id="mounted" href="${origin}/docs/guide">Mounted guide</a>
      <a id="strict" href="${strictOrigin}/docs/guide">Strict origin</a>
      <form action="${origin}/guide" method="post"><button id="unsafe">Submit</button></form>`);
  });
  server.maxConnections = 8;
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const context = await browser.newContext();
  const observations = [];
  try {
    const page = await context.newPage();
    for (const [hostname, expectedSite] of [['127.0.0.1', 'cross-site'], ['links.lsf.localhost', 'same-site']]) {
      const source = `http://${hostname}:${server.address().port}/`;
      for (const [link, mount] of [['root', ''], ['mounted', '/docs']]) {
        await page.goto(source, {timeout: 10000});
        const [response] = await Promise.all([
          page.waitForResponse(value => value.url() === origin + mount + '/guide/', {timeout: 10000}),
          page.locator('#' + link).click(),
        ]);
        assert.equal(response.status(), 200);
        await page.waitForURL(origin + mount + '/guide/');
        assert.equal(await page.locator('#view').textContent(), 'Static guide');
        const redirect = response.request().redirectedFrom();
        assert.equal((await redirect.response()).status(), 308);
        for (const request of [redirect, response.request()]) {
          const metadata = await request.allHeaders();
          assert.equal(metadata['sec-fetch-site'], expectedSite);
          assert.equal(metadata['sec-fetch-mode'], 'navigate');
          assert.equal(metadata['sec-fetch-dest'], 'document');
          assert.equal(metadata.origin, undefined);
        }
        assert.equal(response.headers()['access-control-allow-origin'], undefined);
        assert.match(response.headers()['content-security-policy'], /frame-ancestors 'none'/);
        observations.push({site: expectedSite, mount: mount || '/', status: 200, redirect: 308});
      }
      // Cross-origin read, script, frame, unsafe form and a non-opted-in origin
      // must remain rejected by LSF even after ordinary public links work.
      for (const action of ['read', 'script', 'frame', 'unsafe', 'strict']) {
        await page.goto(source, {timeout: 10000});
        const target = action === 'strict' ? strictOrigin + '/docs/guide' : origin + '/guide';
        const denied = page.waitForResponse(value => value.url() === target, {timeout: 10000});
        if (action === 'read') {
          assert.equal(await page.evaluate(async url => {
            try { await fetch(url); return 'read'; } catch (error) { return error.name; }
          }, target), 'TypeError');
        } else if (action === 'script' || action === 'frame') {
          await page.evaluate(({target, action}) => {
            const element = document.createElement(action === 'script' ? 'script' : 'iframe');
            element.src = target; document.body.append(element);
          }, {target, action});
        } else {
          await page.locator('#' + action).click({noWaitAfter: true});
        }
        assert.equal((await denied).status(), 403, action);
      }
    }
    const addressBar = await context.newPage();
    const response = await addressBar.goto(origin + '/guide/', {timeout: 10000});
    assert.equal(response.status(), 200);
    assert.equal((await response.request().allHeaders())['sec-fetch-site'], 'none');
    return {observations, addressBar: true, crossOriginReadsFramesScriptsAndUnsafeFormsDenied: true, strictOriginDenied: true};
  } finally {
    await context.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
}
