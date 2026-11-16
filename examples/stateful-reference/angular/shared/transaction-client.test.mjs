import assert from 'node:assert/strict';
import {test} from 'node:test';
import {DraftClient} from './transaction-client.ts';

// These are unit transport fixtures. Real browser qualification uses the node
// conductor and records its actual responses; no unit receipt is runtime proof.
const routes = {command: '/draft/edit', query: '/draft/query', result: '/draft/result'};
const commandId = 'a'.repeat(64), attemptId = '1';
const namespaceToken = [78,86,2,...new Array(64).fill(0)], keyToken = [83,86,2,...new Array(64).fill(0)];
const view = Buffer.from(namespaceToken).toString('base64');
function response(disposition, {error, revision = '1', units = 3} = {}) {
  const draft = '{"draft-id":"demo","revision":' + revision + ',"units":' + units
    + ',"namespace-view":' + JSON.stringify(namespaceToken) + ',"key-version":{"some":' + JSON.stringify(keyToken) + '}}';
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

test('unavailable query is reported without discarding the original command', async () => {
  const app = client(async () => new Response(JSON.stringify({profile: 'transaction-http-v1',
    disposition: 'query', representation: 'receipt-only', result: null}), {status: 503}));
  const key = app.prepare('demo', '0', 3);
  await assert.rejects(app.query('demo'), /query-unavailable/);
  assert.equal(app.pending.key, key);
  assert.equal(app.status, 'prepared');
});

test('failed query cannot install an application body from an error response', async () => {
  const app = client(async () => {
    const body = await response('query').text();
    return new Response(body, {status: 503});
  });
  await assert.rejects(app.query('demo'), /query-unavailable/);
  assert.equal(app.view, undefined);
});

test('fragmented query bodies remain bounded and decode correctly', async () => {
  const payload = new TextEncoder().encode(await response('query').text());
  const app = client(async () => new Response(new ReadableStream({
    start(controller) {
      for (let index = 0; index < 100; index++) controller.enqueue(new Uint8Array());
      for (const byte of payload) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    },
  }), {status: 200}));
  const result = await app.query('demo');
  assert.equal(result.value.draftId, 'demo');
  const oversized = client(async () => new Response(new Uint8Array(192 * 1024 + 1), {status: 200}));
  await assert.rejects(oversized.query('demo'), /response-byte-limit/);
  const empty = client(async () => new Response(new ReadableStream({
    start(controller) {
      for (let index = 0; index < 1025; index++) controller.enqueue(new Uint8Array());
      controller.close();
    },
  }), {status: 200}));
  await assert.rejects(empty.query('demo'), /response-fragment-limit/);
});

test('a response started before permission denial cannot restore a private view', async () => {
  let release;
  let count = 0;
  const app = client(async () => {
    if (++count === 1) return new Promise(resolve => { release = resolve; });
    return new Response('', {status: 403});
  });
  const original = app.prepare('demo', '0', 3);
  const stale = app.query('demo');
  await assert.rejects(app.query('demo'), /permission-denied/);
  release(response('query'));
  await assert.rejects(stale, /permission-denied/);
  assert.equal(app.view, undefined);
  assert.equal(app.pending.key, original);
  assert.equal(app.status, 'permission-denied');
});

test('effect status uses the original command and accepts only its bounded effect', async () => {
  const id = 'e'.repeat(64), requests = [];
  const app = client(async (url, options) => {
    requests.push({url, ...options});
    if (requests.length === 1) {
      const body = await response('committed').json();
      body['effect-ids'] = [id];
      return new Response(JSON.stringify(body), {status: 200});
    }
    return new Response(JSON.stringify({profile: 'transaction-http-v1', disposition: 'effect',
      representation: 'effect-status', effect: {'effect-id': requests.length === 2 ? id : 'f'.repeat(64),
        disposition: 'provider-acknowledged', 'dispatch-attempt': 2}}), {status: 200});
  });
  const original = app.prepare('demo', '0', 3);
  await app.submit();
  assert.deepEqual(await app.effectStatus(id), {effectId: id, disposition: 'provider-acknowledged', dispatchAttempt: 2});
  assert.equal(requests[1].headers.get('idempotency-key'), original);
  assert.equal(requests[1].headers.get('effect-id'), id);
  await assert.rejects(app.effectStatus('f'.repeat(64)), /original-command-effect-required/);
  assert.equal(requests.length, 2);
  await assert.rejects(app.effectStatus(id), /invalid-effect-status/);
});

test('a query response cannot stand in for a command disposition', async () => {
  const app = client(async () => response('query'));
  const original = app.prepare('demo', '0', 3);
  await assert.rejects(app.submit(), /unexpected-transaction-response/);
  assert.equal(app.status, 'uncertain');
  assert.equal(app.pending.key, original);
  assert.equal(app.view, undefined);
});

test('an inconsistent HTTP status cannot install a terminal command result', async () => {
  const app = client(async () => new Response(await response('committed').text(), {status: 503}));
  const original = app.prepare('demo', '0', 3);
  await assert.rejects(app.submit(), /inconsistent-transaction-status/);
  assert.equal(app.status, 'uncertain');
  assert.equal(app.pending.key, original);
  assert.equal(app.view, undefined);
  assert.throws(() => app.finishOriginal(), /original-command-not-terminal/);
});

test('an older recovery response cannot downgrade a terminal command', async () => {
  let count = 0;
  const app = client(async () => ++count === 1 ? response('committed') : new Response(await response('in-progress').text(), {status: 202}));
  const original = app.prepare('demo', '0', 3);
  await app.submit();
  const terminalView = app.view;
  await assert.rejects(app.recover(), /terminal-command-regression/);
  assert.equal(app.status, 'committed');
  assert.equal(app.view, terminalView);
  assert.equal(app.pending.key, original);
  app.finishOriginal();
});

test('a late submission cannot overwrite a recovered terminal command', async () => {
  let release;
  let count = 0;
  const app = client(async () => ++count === 1
    ? new Promise(resolve => { release = resolve; }) : response('committed'));
  app.prepare('demo', '0', 3);
  const submission = app.submit();
  await app.recover();
  release(new Response(await response('in-progress').text(), {status: 202}));
  await assert.rejects(submission, /terminal-command-regression/);
  assert.equal(app.status, 'committed');
  app.finishOriginal();
});

test('a finished command cannot overwrite a newly prepared command', async () => {
  let release;
  let count = 0;
  const app = client(async () => ++count === 1
    ? new Promise(resolve => { release = resolve; }) : response('committed'));
  app.prepare('demo', '0', 3);
  const oldSubmission = app.submit();
  await app.recover();
  app.finishOriginal();
  const next = app.prepare('demo', '1', 4);
  release(new Response(await response('in-progress').text(), {status: 202}));
  await assert.rejects(oldSubmission, /original-command-changed/);
  assert.equal(app.status, 'prepared');
  assert.equal(app.pending.key, next);
});

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

test('oversized denial clears private observations before reading the body', async () => {
  const app = client(async () => new Response('x'.repeat(192 * 1024 + 1), {status: 403}));
  app.view = {private: 'prior user'}; app.last = {private: 'prior user'}; app.minimumView = 'prior-token';
  await assert.rejects(app.query('demo'), /permission-denied/);
  assert.equal(app.view, undefined); assert.equal(app.last, undefined); assert.equal(app.minimumView, undefined);
  assert.equal(app.status, 'permission-denied');
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


test('actual decimal attempt identities are accepted and obsolete or malformed counters refused', async () => {
  for (const attempt of ['1', '16']) {
    const app = client(async () => {const e = await response('committed').json();e['attempt-id']=attempt;return new Response(JSON.stringify(e));});
    app.prepare('demo','0',3);await app.submit();assert.equal(app.status,'committed');
  }
  for (const attempt of ['0','01','17','b'.repeat(64)]) {
    const app = client(async () => {const e = await response('committed').json();e['attempt-id']=attempt;return new Response(JSON.stringify(e));});
    app.prepare('demo','0',3);await assert.rejects(app.submit(),/invalid-attempt-identity/);assert.equal(app.status,'uncertain');
  }
});


test('short or wrong-kind state observations cannot become write preconditions', async () => {
  for (const [name,bytes] of [['namespace-view',[78,86,2]],['namespace-view',keyToken],['key-version',namespaceToken]]) {
    const app=client(async () => {const e=await response('committed').json();const value=JSON.parse(Buffer.from(e.result['body-base64'],'base64'));
      value[0].ok[name]=name==='key-version'?{some:bytes}:bytes;e.result['body-base64']=Buffer.from(JSON.stringify(value)).toString('base64');return new Response(JSON.stringify(e));});
    app.prepare('demo','0',3);await assert.rejects(app.submit(),/invalid-state-observation/);assert.equal(app.status,'uncertain');
  }
});
