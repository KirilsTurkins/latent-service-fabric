"""Native JS semantics and compiler selection; no emitted-component claim."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.typescript_guest import fetch_profile
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE, NATIVE_PROFILES, SYNC_PROFILE

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptFetchTests(unittest.TestCase):
    def test_response_error_factory_preserves_null_body_immutable_headers_and_clone(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
installFetch({}, () => false, target);
for (const Response of [globalThis.Response, target.Response]) {
  const response = Response.error();
  assert.equal(response instanceof Response, true);
  assert.deepEqual([response.status, response.statusText, response.type, response.ok,
    response.url, response.redirected, response.body, response.bodyUsed], [0, '', 'error', false, '', false, null, false]);
  assert.deepEqual([...response.headers], []);
  for (const value of [response, response.clone()]) {
    assert.equal(value.status, 0); assert.equal(value.type, 'error');
    assert.equal(await value.text(), '');
    assert.equal((await value.arrayBuffer()).byteLength, 0);
    await assert.rejects(value.json(), SyntaxError);
    assert.equal(value.bodyUsed, false);
    for (const operation of ['append', 'set', 'delete']) {
      assert.throws(() => value.headers[operation]('x-test', 'value'), TypeError);
    }
  }
  const copy = response.clone();
  assert.notEqual(copy, response); assert.notEqual(copy.headers, response.headers);
  assert.throws(() => new Response(null, {status: 0}), RangeError);
  const ordinary = new Response('ordinary');
  ordinary.headers.set('x-test', 'mutable');
  assert.equal(await ordinary.clone().text(), 'ordinary');
}
""")

    def test_response_redirect_factory_matches_reference_location_status_and_clone(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
installFetch({}, () => false, target);
const url = 'https://EXAMPLE.test:443/a path?value=\u2603#fragment';
const object = new URL(url);
assert.deepEqual([...target.Response.redirect(object).headers], [...globalThis.Response.redirect(object).headers]);
for (const status of [undefined, 301, 302, 303, 307, 308, '301', 301.9, 65536 + 302]) {
  const reference = globalThis.Response.redirect(url, status);
  const response = target.Response.redirect(url, status);
  assert.deepEqual([...response.headers], [...reference.headers]);
  assert.deepEqual([response.status, response.statusText, response.type, response.ok,
    response.url, response.redirected, response.body], [reference.status, '', 'default', false, '', false, null]);
  assert.equal(response.headers.get('location'), new URL(url).href);
  assert.equal(response.headers.get('location').endsWith('#fragment'), true);
  for (const value of [response, response.clone()]) {
    assert.equal(value.status, reference.status);
    assert.equal(await value.text(), ''); assert.equal(value.bodyUsed, false);
    for (const operation of ['append', 'set', 'delete']) {
      assert.throws(() => value.headers[operation]('x-test', 'value'), TypeError);
    }
  }
}
""")

    def test_response_redirect_preserves_conversion_errors_and_finite_url_profile(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
installFetch({}, () => false, target);
for (const Response of [globalThis.Response, target.Response]) {
  for (const status of [0, 200, 304, 400, null, NaN, Infinity]) {
    assert.throws(() => Response.redirect('https://example.test/', status), RangeError);
  }
  for (const url of ['/relative', 'invalid URL']) assert.throws(() => Response.redirect(url), TypeError);
  const reason = new Error('original status conversion');
  const events = [];
  assert.throws(() => Response.redirect({toString() {events.push('url'); return 'invalid URL';}},
    {valueOf() {events.push('status'); throw reason;}}), error => error === reason);
  assert.deepEqual(events, ['url', 'status']);
}
// Web IDL unsigned-short conversion uses ToNumber, which rejects BigInt.
assert.throws(() => target.Response.redirect('https://example.test/', 301n), TypeError);
// The unsigned-short modulo is nonnegative, including for negative inputs.
assert.equal(target.Response.redirect('https://example.test/', -65536 + 307).status, 307);
const prefix = 'https://example.test/';
const maximum = prefix + 'x'.repeat(2048 - prefix.length);
assert.equal(target.Response.redirect(maximum).headers.get('location'), maximum);
assert.throws(() => target.Response.redirect(maximum + 'x'), /fetch-url-limit/);
assert.throws(() => target.Response.redirect('ftp://example.test/'), /unsupported:Response.redirect-url/);
""")

    def test_synthetic_responses_do_not_contact_provider_or_convert_fetch_failure(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
let calls = 0;
const original = {tag: 'uncertain'};
installFetch({async open() {calls++; throw original;}}, () => false, target);
assert.equal(target.Response.error().clone().type, 'error');
assert.equal(target.Response.redirect('https://example.test/next').clone().status, 302);
assert.equal(calls, 0);
await assert.rejects(target.fetch('https://example.test/', {method: 'POST'}), error =>
  error instanceof TypeError && error.uncertain === true && error.cause === original);
assert.equal(calls, 1);
assert.equal(target.Response.error().status, 0);
assert.equal(calls, 1);
""")

    def test_headers_accept_iterable_pairs_and_capture_independent_values(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
installFetch({}, () => false, target);
const pairs = [
  () => new Set(['X-Value', ' one ']),
  () => ({*[Symbol.iterator]() {yield 'X-Value'; yield ' one ';}}),
  () => ({[Symbol.iterator]() {let index = 0; const values = ['X-Value', ' one '];
    return {next() {return index < values.length ? {value: values[index++], done: false} : {done: true};}};}})
];
for (const Headers of [globalThis.Headers, target.Headers]) {
  for (const pair of pairs) {
    const headers = new Headers([pair(), ['x-value', 'two']]);
    assert.deepEqual([...headers], [['x-value', 'one, two']]);
    assert.equal(headers.get('X-VALUE'), 'one, two');
  }
  const original = [['X-Value', 'original']];
  const headers = new Headers(original);
  original[0][1] = 'changed'; original.push(['x-value', 'added']);
  assert.equal(headers.get('x-value'), 'original');
  assert.deepEqual([...new Headers()], []);
  assert.deepEqual([...new Headers(undefined)], []);
}
""")

    def test_headers_reject_primitive_initializers_and_malformed_pairs(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
installFetch({}, () => false, target);
for (const Headers of [globalThis.Headers, target.Headers]) {
  for (const invalid of [null, 1, true, 1n, Symbol('invalid'), 'ab', {[Symbol.iterator]: 1}]) {
    assert.throws(() => new Headers(invalid), TypeError);
  }
  for (const pair of [null, undefined, 1, false, 'ab', {}, [], ['x'], ['x', 'v', 'extra']]) {
    assert.throws(() => new Headers([pair]), TypeError);
  }
  const original = new Error('iterator-failed');
  assert.throws(() => new Headers({get [Symbol.iterator]() {throw original;}}), error => error === original);
  assert.throws(() => new Headers([{get [Symbol.iterator]() {throw original;}}]), error => error === original);
}
""")

    def test_header_iterators_are_cached_and_closed_at_structural_and_profile_bounds(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
installFetch({}, () => false, target);
for (const Headers of [globalThis.Headers, target.Headers]) {
  let outerGets = 0, innerGets = 0;
  const pair = {get [Symbol.iterator]() {innerGets++;
    return function () {assert.equal(this, pair); return ['X-Value', 'v'][Symbol.iterator]();};}};
  const source = {get [Symbol.iterator]() {outerGets++;
    return function () {assert.equal(this, source); return [pair][Symbol.iterator]();};}};
  assert.equal(new Headers(source).get('x-value'), 'v');
  assert.equal(outerGets, 1); assert.equal(innerGets, 1);
}
let values = 0, innerClosed = 0, outerClosed = 0;
function *badPair() {try {while (true) {values++; yield 'x';}} finally {innerClosed++;}}
function *badSource() {try {yield badPair();} finally {outerClosed++;}}
assert.throws(() => new target.Headers(badSource()), TypeError);
assert.equal(values, 3); assert.equal(innerClosed, 1); assert.equal(outerClosed, 1);
let entries = 0, boundedClosed = 0;
function *tooMany() {try {while (true) {entries++; yield ['x', 'v'];}} finally {boundedClosed++;}}
assert.throws(() => new target.Headers(tooMany()), /invalid-header-sequence/);
assert.equal(entries, 65); assert.equal(boundedClosed, 1);
assert.equal(new target.Headers([['x', 'v'.repeat(32767)]]).get('x').length, 32767);
let bytesClosed = 0;
function *tooLarge() {try {yield new Set(['x', 'v'.repeat(32768)]);} finally {bytesClosed++;}}
assert.throws(() => new target.Headers(tooLarge()), /fetch-header-limit/);
assert.equal(bytesClosed, 1);
""")

    def test_fetch_iterable_headers_use_the_typed_boundary_once_and_refuse_before_contact(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
const requests = [], events = [];
const upload = {[Symbol.dispose]() {events.push('drop:upload');}};
const body = {[Symbol.dispose]() {events.push('drop:body');}};
installFetch({
  async open(request) {requests.push(request); return upload;},
  async finish(value) {assert.equal(value, upload); events.push('consume:upload');
    return {status: 503, headers: [], body};},
  async read(value, maximum) {assert.equal(value, body); assert.equal(maximum, 65536); return undefined;}
}, () => false, target);
function *pair(name, value) {yield name; yield value;}
const response = await target.fetch('https://example.test/', {
  headers: [pair('X-Value', ' one '), new Set(['x-value', 'two'])]
});
assert.equal(response.status, 503); assert.equal(response.ok, false);
assert.deepEqual(requests, [{method: 'get', url: 'https://example.test/',
  headers: [{name: 'x-value', value: 'one, two'}], bodyLength: 0n,
  bodyMediaType: undefined, idempotencyKey: undefined, timeoutMillis: undefined}]);
assert.deepEqual(events, ['consume:upload', 'drop:body']);
await assert.rejects(target.fetch('https://example.test/', {headers: false}), TypeError);
await assert.rejects(target.fetch('https://example.test/', {headers: [pair('x', 'v'), ['bad', 'v', 'extra']]}), TypeError);
await assert.rejects(target.fetch('https://example.test/', {headers: [pair('Authorization', 'must-not-send')]}), /unsupported:reserved-header/);
assert.equal(requests.length, 1);
assert.deepEqual(events, ['consume:upload', 'drop:body']);
""")

    def test_replacement_body_does_not_consume_or_reuse_inherited_bytes(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
installFetch({}, () => false, target);
for (const Request of [target.Request, globalThis.Request]) {
  const source = new Request('https://example.test', {method: 'POST', body: 'original'});
  const backing = new Uint8Array([9, 1, 2, 9]);
  const replaced = new Request(source, {body: backing.subarray(1, 3)});
  backing.fill(0);
  assert.equal(source.bodyUsed, false);
  assert.deepEqual(new Uint8Array(await replaced.arrayBuffer()), new Uint8Array([1, 2]));
  assert.equal(replaced.bodyUsed, true);
  assert.equal(await source.text(), 'original');
  const emptyReplacement = new Request(source, {body: ''});
  assert.equal(emptyReplacement.bodyUsed, false);
  assert.equal(await emptyReplacement.text(), '');
  assert.equal(emptyReplacement.bodyUsed, true);
  assert.equal(source.bodyUsed, true);
  assert.throws(() => new Request(source), TypeError);
  assert.throws(() => new Request(source, {body: null}), TypeError);
  assert.throws(() => source.clone(), TypeError);
}
""")

    def test_failed_get_head_construction_preserves_inherited_body(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
installFetch({}, () => false, target);
for (const Request of [target.Request, globalThis.Request]) {
  for (const method of ['GET', 'HEAD']) {
    const source = new Request('https://example.test', {method: 'POST', body: 'still-owned'});
    assert.throws(() => new Request(source, {method}), TypeError);
    assert.equal(source.bodyUsed, false);
    assert.throws(() => new Request(source, {method, body: 'replacement'}), TypeError);
    assert.equal(source.bodyUsed, false);
    const transferred = new Request(source);
    assert.equal(source.bodyUsed, true);
    assert.equal(await transferred.text(), 'still-owned');
    await assert.rejects(source.text(), TypeError);
  }
}
""")

    def test_fetch_replacement_body_uses_normal_typed_adapter_once(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
const requests = [], writes = [], events = [];
const owner = name => ({[Symbol.dispose]() {events.push('drop:' + name);}});
const upload = owner('upload'), body = owner('body');
installFetch({
  async open(request) {requests.push(request); return upload;},
  async write(value, bytes) {assert.equal(value, upload); writes.push(new TextDecoder().decode(bytes));},
  async finish(value) {assert.equal(value, upload); events.push('finish:upload'); return {status: 200, headers: [], body};},
  async read(value, maximum) {assert.equal(value, body); assert.equal(maximum, 65536); return undefined;}
}, () => false, target);
const source = new target.Request('https://example.test', {method: 'POST', body: 'already-consumed'});
assert.equal(await source.text(), 'already-consumed');
const response = await target.fetch(source, {body: 'fresh'});
assert.equal(response.status, 200);
assert.deepEqual(requests, [{method: 'post', url: 'https://example.test/', headers: [],
  bodyLength: 5n, bodyMediaType: 'text/plain;charset=UTF-8', idempotencyKey: undefined, timeoutMillis: undefined}]);
assert.deepEqual(writes, ['fresh']);
assert.deepEqual(events, ['finish:upload', 'drop:body']);
assert.equal(source.bodyUsed, true);
await assert.rejects(target.fetch(source), /body-already-used/);
await assert.rejects(target.fetch(source, {body: 'x'.repeat(1024 * 1024 + 1)}), /fetch-body-limit/);
assert.equal(requests.length, 1);
assert.deepEqual(events, ['finish:upload', 'drop:body']);
""")

    def test_only_exact_async_import_runtime_with_declared_typed_http_selects_backend(self):
        for profile in (SYNC_PROFILE, *NATIVE_PROFILES):
            for imports in ([], ['latent:http/client@0.2.0'], [fetch_profile.INTERFACE]):
                with self.subTest(profile=profile, imports=imports):
                    result = fetch_profile.bundle_configuration({}, profile, imports)
                    self.assertEqual(result.get('standardFetchProfile'),
                        fetch_profile.PROFILE if profile == IMPORT_PROFILE and fetch_profile.INTERFACE in imports else None)

    def test_application_metadata_cannot_install_or_override_backend(self):
        with self.assertRaisesRegex(ValueError, 'cannot-override'):
            fetch_profile.bundle_configuration({'standardFetchProfile': fetch_profile.PROFILE},
                                               IMPORT_PROFILE, [fetch_profile.INTERFACE])
        original = {'conditions': ['private']}
        result = fetch_profile.bundle_configuration(original, IMPORT_PROFILE, [fetch_profile.INTERFACE])
        self.assertNotIn('standardFetchProfile', original)
        self.assertEqual(result['conditions'], ['private'])

    def run_javascript(self, source):
        node = shutil.which('node')
        if node is None:
            self.skipTest('requires Node')
        with tempfile.TemporaryDirectory() as owned:
            directory = Path(owned)
            (directory/'fetch.mjs').write_bytes((ROOT/'tools/typescript_guest/fetch.mjs').read_bytes())
            (directory/'test.mjs').write_text("import assert from 'node:assert/strict';\n"
                "import {installFetch} from './fetch.mjs';\n" + source, encoding='utf-8')
            result = subprocess.run([node, str(directory/'test.mjs')], capture_output=True,
                                    text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_standard_headers_buffered_body_clone_and_one_shot_request(self):
        self.run_javascript(r"""
import vm from 'node:vm';
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
installFetch({}, () => false, target);
const {Headers, Request, Response} = target;
const headers = new Headers([['X-Test', ' one '], ['x-test', 'two'], ['Z', '3']]);
assert.equal(headers.get('X-TEST'), 'one, two');
assert.deepEqual([...headers.keys()], ['x-test', 'z']);
let visited = [];
headers.forEach((value, key, parent) => { assert.equal(parent, headers); visited.push([key, value]); });
assert.deepEqual(visited, [...headers]);
assert.throws(() => new Headers({'bad\r\nname': 'value'}), /invalid-header-name/);
assert.throws(() => new Headers({'x': 'one\r\ntwo'}), /invalid-header-value/);
assert.throws(() => new Headers(Array.from({length: 65}, (_, i) => ['x-' + i, 'v'])), /invalid-header-sequence/);
assert.throws(() => headers.set('large', 'x'.repeat(32769)), /fetch-header-limit/);
const original = new Uint8Array([9, 1, 2, 9]);
const response = new Response(original.subarray(1, 3), {status: 422});
original[1] = 8;
assert.equal(response.ok, false);
const copy = response.clone();
assert.deepEqual(new Uint8Array(await response.arrayBuffer()), new Uint8Array([1, 2]));
assert.equal(response.bodyUsed, true);
await assert.rejects(response.text(), /body-already-used/);
assert.throws(() => response.clone(), /body-already-used/);
assert.deepEqual(new Uint8Array(await copy.arrayBuffer()), new Uint8Array([1, 2]));
assert.deepEqual(new Uint8Array(await new Response(vm.runInNewContext('new Uint8Array([3, 4])')).arrayBuffer()),
  new Uint8Array([3, 4]));
const json = Response.json({value: 'Grüße 😀'});
assert.equal(json.headers.get('content-type'), 'application/json');
assert.deepEqual(await json.json(), {value: 'Grüße 😀'});
const empty = new Response();
assert.equal(await empty.text(), '');
assert.equal(await empty.text(), '');
assert.equal(empty.bodyUsed, false);
assert.throws(() => new Response('', {status: 204}), /null-body-status/);
const request = new Request('https://EXAMPLE.test/path#fragment', {method: 'POST', body: 'payload'});
assert.equal(request.url, 'https://example.test/path');
assert.throws(() => {request.url = 'https://other.test';}, TypeError);
const requestCopy = request.clone();
assert.equal(request.bodyUsed, false);
assert.equal(await requestCopy.text(), 'payload');
const transferred = new Request(request);
assert.equal(request.bodyUsed, true);
assert.equal(await transferred.text(), 'payload');
assert.throws(() => new Request(request), /body-already-used/);
assert.throws(() => new Request('https://example.test', {body: 'bad'}), /body-for-get-or-head/);
assert.throws(() => new Request('https://user:password@example.test'), /invalid-fetch-url/);
assert.throws(() => new Request('https://example.test', {credentials: 'include'}), /unsupported:credentials/);
assert.throws(() => new Request('https://example.test', {signal: {addEventListener(){}}}), /invalid-AbortSignal/);
const controller = new AbortController(), reason = {unchanged: true};
const dependent = new Request('https://example.test', {signal: controller.signal});
const dependentClone = dependent.clone();
const reference = new globalThis.Request('https://example.test', {signal: controller.signal});
assert.notEqual(reference.signal, controller.signal);
assert.notEqual(dependent.signal, controller.signal);
assert.notEqual(dependentClone.signal, dependent.signal);
controller.abort(reason);
for (const signal of [reference.signal, dependent.signal, dependentClone.signal]) {
  assert.equal(signal.aborted, true); assert.equal(signal.reason, reason);
}
const reset = new Request(dependent, {signal: null});
const referenceReset = new globalThis.Request(reference, {signal: null});
assert.equal(reset.signal.aborted, referenceReset.signal.aborted);
assert.equal(reset.signal.aborted, false);
assert.throws(() => new Response('bytes').body, /unsupported:streaming-body/);
assert.throws(() => new Request('https://example.test', {unknown: true}), /unsupported:RequestInit.unknown/);
""")

    def test_pending_typed_exchange_http_errors_chunk_retirement_and_no_replay(self):
        self.run_javascript(r"""
import vm from 'node:vm';
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
const release = Promise.withResolvers();
const events = [], requests = [];
let materialized;
const owner = name => ({[Symbol.dispose]() {events.push('drop:' + name);
  if (name === 'chunk') materialized.fill(0);}});
const upload = owner('upload'), body = owner('body'), chunk = owner('chunk');
let reads = 0;
installFetch({
  async open(request) { requests.push(request); await release.promise; return upload; },
  async write(value, bytes) { assert.equal(value, upload); events.push('write:' + new TextDecoder().decode(bytes)); },
  async finish(value) { assert.equal(value, upload); events.push('consume:upload');
    return {status: 503, headers: [], bodyMediaType: 'application/json', body}; },
  async read(value, maximum) { assert.equal(value, body); assert.equal(maximum, 65536); return reads++ === 0 ? chunk : undefined; },
  async chunkBytes(value) { assert.equal(value, chunk);
    materialized = vm.runInNewContext('new Uint8Array(values)', {values: [...new TextEncoder().encode('{"error":"busy"}')]});
    return materialized; }
}, () => false, target);
const request = new target.Request('https://example.test/api', {method: 'POST', body: '{}',
  headers: {'Content-Type': 'application/json', 'Idempotency-Key': 'caller-key', 'X-Trace': 'original'}});
let settled = false;
const pending = target.fetch(request).then(value => {settled = true; return value;});
assert(pending instanceof Promise);
assert.equal(settled, false);
assert.equal(request.bodyUsed, true);
assert.deepEqual(requests, [{method: 'post', url: 'https://example.test/api',
  headers: [{name: 'x-trace', value: 'original'}], bodyLength: 2n,
  bodyMediaType: 'application/json', idempotencyKey: 'caller-key', timeoutMillis: undefined}]);
release.resolve();
const response = await pending;
assert.equal(response.status, 503);
assert.equal(response.ok, false);
assert.equal(response.url, 'https://example.test/api');
assert.equal(response.redirected, false);
assert.throws(() => response.statusText, /unsupported:response-status-text/);
assert.throws(() => response.headers.set('x-test', 'changed'), /immutable-response-headers/);
const clone = response.clone();
assert.deepEqual(await response.json(), {error: 'busy'});
assert.deepEqual(await clone.json(), {error: 'busy'});
assert(materialized.every(value => value === 0)); // Destructor invalidated its borrowed view.
assert.deepEqual(events, ['write:{}', 'consume:upload', 'drop:chunk', 'drop:body']);
assert.equal(requests.length, 1);
let attempts = 0;
installFetch({async open() { attempts++; const error = new Error('typed'); error.payload = {tag: 'uncertain'}; throw error; }}, () => false, target);
await assert.rejects(target.fetch('https://example.test/api', {method: 'POST'}), error =>
  error.uncertain === true && error.cause.payload.tag === 'uncertain');
assert.equal(attempts, 1);
""")

    def test_abort_rejects_before_contact_and_retains_capacity_until_actual_completion(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
let calls = 0, drops = 0;
const gates = [], retired = Promise.withResolvers();
installFetch({async open() { calls++; const gate = Promise.withResolvers(); gates.push(gate);
    await gate.promise; return {[Symbol.dispose]() { if (++drops === 16) retired.resolve(); }}; }
}, () => false, target);
const cancelled = new AbortController(), reason = {identity: 'original'};
cancelled.abort(reason);
await assert.rejects(target.fetch('https://example.test', {signal: cancelled.signal}), error => error === reason);
assert.equal(calls, 0);
for (let i = 0; i < 16; i++) {
  const controller = new AbortController();
  const pending = target.fetch('https://example.test', {signal: controller.signal});
  controller.abort(reason);
  await assert.rejects(pending, error => error === reason);
}
assert.equal(calls, 16); assert.equal(drops, 0);
await assert.rejects(target.fetch('https://example.test'), /outstanding-operation-limit/);
assert.equal(calls, 16);
for (const gate of gates) gate.resolve();
await retired.promise;
assert.equal(drops, 16);
""")

    def test_completed_exchange_releases_capacity_before_its_consumer_admits_successor(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
const gates = [], events = [];
let admitted = 0;
const owner = label => ({[Symbol.dispose]() {events.push('drop:' + label);}});
installFetch({
  async open() {const gate = Promise.withResolvers(); gates.push(gate); await gate.promise;
    return owner('upload:' + ++admitted);},
  async finish() {return {status: 200, headers: [], body: owner('body')};},
  async read() {return undefined;}
}, () => false, target);
const pending = Array.from({length: 16}, () => target.fetch('https://example.test/'));
assert.equal(gates.length, 16);
const successor = pending[0].then(response => {
  assert.equal(response.status, 200);
  assert.deepEqual(events, ['drop:body']);
  return target.fetch('https://example.test/next');
});
successor.catch(() => {}); // Keep the old-source refusal observable by the assertion.
gates[0].resolve();
// A completed operation has physically dropped its body before the successor
// is admitted. The other fifteen genuinely pending operations stay charged.
await new Promise(resolve => setImmediate(resolve));
assert.equal(gates.length, 17);
for (const gate of gates) gate.resolve();
assert.equal((await successor).status, 200);
assert.equal((await Promise.all(pending)).length, 16);
assert.equal(admitted, 17);
assert.equal(events.length, 17);
""")

    def test_rejected_exchange_releases_capacity_before_rejection_consumer(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
const gates = [];
installFetch({
  async open() {const gate = Promise.withResolvers(); gates.push(gate); return await gate.promise;},
  async finish() {return {status: 200, headers: [], body: {[Symbol.dispose]() {}}};},
  async read() {return undefined;}
}, () => false, target);
const pending = Array.from({length: 16}, () => target.fetch('https://example.test/'));
const original = {tag: 'connection-failed'};
const successor = pending[0].catch(error => {
  assert.equal(error.cause, original);
  return target.fetch('https://example.test/next');
});
successor.catch(() => {});
gates[0].reject(original);
await new Promise(resolve => setImmediate(resolve));
assert.equal(gates.length, 17);
for (const gate of gates.slice(1)) gate.resolve({[Symbol.dispose]() {}});
assert.equal((await successor).status, 200);
assert.equal((await Promise.all(pending.slice(1))).length, 15);
// Construction errors remain rejected Promises, before any new provider call.
const invalid = target.fetch('invalid URL');
assert(invalid instanceof Promise);
await assert.rejects(invalid, TypeError);
assert.equal(gates.length, 17);
""")

    def test_redirects_reauthorize_strip_headers_and_mutation_is_never_replayed(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
const requests = [];
let status = 302;
const owner = () => ({[Symbol.dispose]() {}});
installFetch({async open(request) {requests.push(request); return owner();},
  async finish() { return {status: requests.length % 2 ? status : 200,
    headers: requests.length % 2 ? [{name: 'location', value: 'https://other.test/final'}] : [], body: owner()}; },
  async read() {return undefined;}
}, () => false, target);
const response = await target.fetch('https://example.test/start', {headers: {'x-tenant-token': 'private'}});
assert.equal(response.url, 'https://other.test/final'); assert.equal(response.redirected, true);
assert.equal(requests.length, 2);
assert.deepEqual(requests[0].headers, [{name: 'x-tenant-token', value: 'private'}]);
assert.deepEqual(requests[1].headers, []);
await assert.rejects(target.fetch('https://example.test/mutation', {method: 'POST'}), /unsupported:mutation-redirect/);
assert.equal(requests.length, 3);
for (const header of ['Authorization', 'Cookie', 'Content-Length', 'Host']) {
  await assert.rejects(target.fetch('https://example.test', {headers: {[header]: 'must-not-send'}}), /unsupported:reserved-header/);
}
assert.equal(requests.length, 3);
installFetch({}, () => true, target);
assert.throws(() => target.fetch('https://example.test'), /snapshot-time-network-observation/);
""")

    def test_partial_response_failure_and_oversize_drop_actual_resource_owners(self):
        self.run_javascript(r"""
const target = {TextEncoder, TextDecoder, URL, AbortController, AbortSignal};
const events = [];
const owner = name => ({[Symbol.dispose]() {events.push(name);}});
let reads = 0;
installFetch({async open() {return owner('upload');},
  async finish() {return {status: 200, headers: [], body: owner('body')};},
  async read() {if (++reads === 2) throw {tag: 'unexpected-eof'}; return owner('chunk');},
  async chunkBytes() {return new Uint8Array([1, 2]);}
}, () => false, target);
await assert.rejects(target.fetch('https://example.test'), /fetch-transport-failure:unexpected-eof/);
assert.deepEqual(events, ['chunk', 'body']);
events.length = 0;
installFetch({async open() {return owner('upload');},
  async finish() {return {status: 200, headers: [], body: owner('body')};},
  async read() {return owner('chunk');}, async chunkBytes() {return new Uint8Array(65536);}
}, () => false, target);
await assert.rejects(target.fetch('https://example.test'), /fetch-body-limit/);
assert.equal(events.filter(name => name === 'chunk').length, 17);
assert.equal(events.at(-1), 'body');
assert.equal(events.includes('upload'), false); // finish consumed it, never double Drop.
""")


if __name__ == '__main__':
    unittest.main()
