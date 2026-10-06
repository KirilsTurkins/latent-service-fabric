import assert from 'node:assert/strict';
import {test} from 'node:test';
import {DraftClient} from './transaction-client.ts';

// These are unit transport fixtures. Real browser qualification uses the node
// conductor and records its actual responses; no unit receipt is runtime proof.
const routes = {command: '/draft/edit', query: '/draft/query', result: '/draft/result'};
const commandId = 'a'.repeat(64), attemptId = 'b'.repeat(64);
const view = Buffer.concat([Buffer.from([78, 86, 2]), Buffer.alloc(64)]).toString('base64');
function response(disposition, {error, revision = '1', units = 3} = {}) {
  const draft = '{"draft-id":"demo","revision":' + revision + ',"units":' + units
    + ',"namespace-view":[78,86,2],"key-version":{"some":[83,86,2]}}';
  const result = error ? '[{"err":' + JSON.stringify(error) + '}]' : '[{"ok":' + draft + '}]';
  const envelope = {profile: 'transaction-http-v1', disposition, representation: 'application-result',
    'command-id': disposition === 'query' ? null : commandId, 'attempt-id': disposition === 'query' ? null : attemptId,
    'state-view': view, 'effect-ids': ['event-original', 'http-original'],
    result: {'media-type': 'application/vnd.latent.wit-values.v1+json', 'body-base64': Buffer.from(result).toString('base64')}};
  if (disposition === 'aborted') {
    envelope.result = null;
    envelope['abort-fence'] = {'command-id': commandId, 'attempt-id': attemptId, 'transaction-id': 'c'.repeat(64), 'owner-fence': Buffer.alloc(32, 7).toString('base64')};
  }
  return new Response(JSON.stringify(envelope), {status: error ? 422 : disposition === 'aborted' ? 409 : 200});
}
function client(fetcher) { return new DraftClient(routes, {origin: 'https://node.example', fetcher}); }

test('uncertain delivery retains the original body, precondition and key and only recovery is sent', async () => {
  const requests = [];
  const app = client(async (url, options) => {
    requests.push({url, ...options});
    if (requests.length === 1) throw new Error('lost terminal reply');
    return response('committed');
  });
  const key = app.prepare('demo', '0', 3, false, '"absent"');
  const original = app.pending;
  await assert.rejects(app.submit(), /lost terminal reply/);
  assert.equal(app.status, 'uncertain');
  await assert.rejects(app.submit(), /explicitly-prepared/);
  assert.throws(() => app.prepare('demo', '1', 9), /original-command/);
  const recovered = await app.recover();
  assert.equal(recovered.disposition, 'committed');
  assert.equal(requests.length, 2);
  assert.equal(requests[1].method, 'GET');
  assert.equal(requests[1].headers.get('idempotency-key'), key);
  assert.equal(requests[0].headers.get('if-match'), '"absent"');
  assert.equal(app.pending, original);
  assert.equal(requests[0].body, original.body);
});

test('fresh query after acknowledgement uses the committed view without replacing terminal rejection history', async () => {
  const requests = [];
  const app = client(async (url, options) => { requests.push(options); return response(url.includes('/query') ? 'query' : 'committed'); });
  app.prepare('demo', '0', 3); await app.submit();
  const original = app.last;
  await app.query('demo');
  assert.equal(requests[1].headers.get('if-state-view'), view);
  assert.equal(app.last, original);
  assert.equal(app.status, 'committed');
  app.finishOriginal();
  assert.equal(app.pending, undefined);
});

test('business rejection recovery does not refresh expected revision or retry a changed business value', async () => {
  let calls = 0;
  const app = client(async () => { calls++; return response('rejected', {error: 'stale-edit'}); });
  app.prepare('demo', '0', 3, false);
  const original = app.pending;
  assert.equal((await app.submit()).value.error, 'stale-edit');
  assert.equal((await app.recover()).value.error, 'stale-edit');
  assert.equal(app.pending, original);
  await assert.rejects(app.retryAborted(), /abort-proof-required/);
  assert.equal(calls, 2);
});

test('explicit technical-abort retry retains the original command and fences further retry after an uncertain response', async () => {
  const requests = [];
  const app = client(async (url, options) => {
    requests.push(options);
    if (requests.length === 1) return response('aborted');
    throw new Error('retry reply lost');
  });
  const key = app.prepare('demo', '0', 3); await app.submit();
  await assert.rejects(app.retryAborted(), /retry reply lost/);
  assert.equal(requests[1].headers.get('idempotency-key'), key);
  assert.equal(requests[1].body, requests[0].body);
  assert.ok(requests[1].headers.get('command-retry-key'));
  assert.ok(requests[1].headers.get('command-abort-fence'));
  await assert.rejects(app.retryAborted(), /abort-proof-required/);
  assert.equal(requests.length, 2);
});

test('u64 business revisions retain every original bit in requests and decoded results', async () => {
  let body;
  const maximum = '18446744073709551615';
  const app = client(async (url, options) => { body = options.body; return response('committed', {revision: maximum}); });
  app.prepare('demo', maximum, 3);
  const result = await app.submit();
  assert.ok(body.includes('"expected-revision":' + maximum));
  assert.equal(result.value.revision, maximum);
  assert.throws(() => revisionOverflow(), /invalid-business-revision/);
  function revisionOverflow() { client(async () => response('query')).prepare('demo', '18446744073709551616', 3); }
});

test('current authority refusal clears private observations and cross-origin routes are rejected', async () => {
  const app = client(async () => new Response('', {status: 403}));
  app.view = {private: 'prior user'}; app.last = {private: 'prior user'}; app.minimumView = 'prior-token';
  app.prepare('demo', '0', 3);
  await assert.rejects(app.submit(), /permission-denied/);
  assert.equal(app.view, undefined); assert.equal(app.last, undefined); assert.equal(app.minimumView, undefined);
  assert.equal(app.status, 'permission-denied');
  assert.throws(() => new DraftClient({...routes, result: 'https://other.example/result'}, {origin: 'https://node.example'}), /invalid-application-route/);
});

test('a response for another draft cannot replace the authorized projection', async () => {
  const app = client(async () => response('query'));
  const original = {draftId: 'private', revision: '0', units: 0};
  app.view = original;
  await assert.rejects(app.query('private'), /foreign-draft-response/);
  assert.equal(app.view, original);
});

test('malformed observation and excess effect identities fail before retaining a terminal result', async () => {
  for (const mutation of [value => { value['state-view'] = 'TlYC'; },
    value => { value['effect-ids'] = ['one', 'two', 'three']; }]) {
    const app = client(async () => {
      const value = await response('committed').json(); mutation(value);
      return new Response(JSON.stringify(value));
    });
    const key = app.prepare('demo', '0', 3);
    await assert.rejects(app.submit(), /invalid-(minimum-view|effect-identities)/);
    assert.equal(app.status, 'uncertain');
    assert.equal(app.pending.key, key);
    assert.equal(app.last, undefined);
  }
});

test('a later response with another command identity cannot replace the original terminal result', async () => {
  let calls = 0;
  const app = client(async () => {
    const value = await response('committed').json();
    if (++calls === 2) value['command-id'] = 'd'.repeat(64);
    return new Response(JSON.stringify(value));
  });
  app.prepare('demo', '0', 3); await app.submit();
  const original = app.last;
  await assert.rejects(app.recover(), /foreign-command-response/);
  assert.equal(app.last, original); assert.equal(app.status, 'committed');
});
