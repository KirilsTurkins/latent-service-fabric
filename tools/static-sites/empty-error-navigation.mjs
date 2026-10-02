import assert from 'node:assert/strict';

// Chromium substitutes its privileged error document for an empty HTTP error.
// In that case Playwright's response.body() exposes the generated document,
// rather than the zero-length origin representation. Check the network framing
// and actual document identity separately; the node workflow also checks the
// origin bytes through its bounded HTTP client.
export async function emptyErrorNavigation(page, target, expected) {
  assert.ok(expected === 403 || expected === 404);
  const received = page.waitForResponse(response => response.url() === target, {timeout: 15000});
  let navigationFailed = false;
  const [response] = await Promise.all([received,
    page.goto(target, {waitUntil: 'networkidle', timeout: 15000}).catch(error => {
      assert.match(error.message, /net::ERR_HTTP_RESPONSE_CODE_FAILURE/);
      navigationFailed = true;
    })]);
  assert.equal(response.status(), expected);
  assert.equal(response.headers()['content-length'], '0', 'origin error representation must be empty');
  assert.match(response.headers()['cache-control'], /(?:^|,\s*)no-store(?:,|$)/);
  // The failed network navigation can finish before Chromium commits its error
  // document. Playwright's polling survives that execution-context transition.
  await page.waitForFunction(target => document.documentURI === target ||
    document.documentURI === 'chrome-error://chromewebdata/', target, {timeout: 15000});
  const documentURI = await page.evaluate(() => document.documentURI);
  let documentSource;
  if (documentURI === 'chrome-error://chromewebdata/') {
    assert.equal(navigationFailed, true, 'browser error document requires its navigation failure');
    documentSource = 'browser-error';
  } else {
    assert.equal(documentURI, target, 'unexpected error document origin');
    assert.equal(navigationFailed, false);
    assert.equal((await response.body()).length, 0);
    documentSource = 'origin';
  }
  return {status: expected, originContentLength: 0, documentSource};
}
