import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
const base = process.env.LSF_TYPESCRIPT_RUNTIME;
assert.ok(base, 'compile the guest runtime before testing it');
const { Scope, Resource, encode, decode, call, parse, stringify } = await import(pathToFileURL(resolve(base, 'codec.js')));
const { Secret, BlobHandle, chunkBytes } = await import(pathToFileURL(resolve(base, 'owners.js')));
const type = kind => ({ kind });
const unit = type('unit');
const u64 = type('u64');
const bytes = { kind: 'list', type: type('u8') };
const error = { kind: 'variant', fields: [['denied', unit], ['uncertain', unit], ['invalid', type('string')]] };
const result = value => ({ kind: 'result', types: [value, error] });
function active() { const scope = new Scope(); scope.begin(); return scope; }
function roundtrip(shape, value) { const scope = active(); const decoded = decode(shape, encode(shape, value, scope), scope); scope.close(); return decoded; }
function broker(run, destroy = () => {}) { return { call: run, drop: destroy }; }

for (const [kind, values] of [
  ['u64', [0n, 9007199254740993n, (1n << 64n) - 1n]],
  ['s64', [-(1n << 63n), -9007199254740993n, 0n, (1n << 63n) - 1n]],
]) {
  test(`${kind} preserves the full WIT range without Number conversion`, () => {
    for (const value of values) assert.equal(roundtrip(type(kind), value), value);
    const scope = active();
    for (const value of [1, 1.1, NaN, true, '1', undefined]) assert.throws(() => encode(type(kind), value, scope));
    const outside = kind === 'u64' ? [-1n, 1n << 64n] : [-(1n << 63n) - 1n, 1n << 63n];
    for (const value of outside) assert.throws(() => encode(type(kind), value, scope));
    for (const value of ['+1', '01', '-0', '1.0', '1e2', ' 1', '']) assert.throws(() => decode(type(kind), JSON.stringify(value), scope));
    scope.close();
  });
}

test('all finite-width integers reject truncation and overflow', () => {
  for (const kind of ['u8', 'u16', 'u32', 's8', 's16', 's32']) {
    const width = Number(kind.slice(1)), signed = kind[0] === 's';
    const max = 2 ** (width - (signed ? 1 : 0)) - 1, min = signed ? -max - 1 : 0;
    assert.equal(roundtrip(type(kind), max), max);
    assert.equal(roundtrip(type(kind), min), min);
    for (const value of [max + 1, min - 1, 0.5, -0, Infinity]) assert.throws(() => roundtrip(type(kind), value));
  }
});

test('NaN, infinities and negative zero survive typed floating-point values', () => {
  for (const kind of ['f32', 'f64']) for (const value of [NaN, Infinity, -Infinity, -0, 0, 1.5]) {
    assert.ok(Object.is(roundtrip(type(kind), value), value));
  }
  assert.equal(roundtrip(type('f32'), 0.1), Math.fround(0.1));
  assert.throws(() => decode(type('f64'), '"unknown"', active()));
});

test('UTF-8 strings and Unicode scalar chars reject lossy surrogate conversion', () => {
  for (const value of ['', 'hello', 'こんにちは', '𐐷🧑🏽‍💻', '\u0000']) assert.equal(roundtrip(type('string'), value), value);
  assert.equal(roundtrip(type('char'), '𐐷'), '𐐷');
  for (const value of ['', 'aa', 'a\u0301', '\ud800', '\udfff']) assert.throws(() => roundtrip(type('char'), value));
  for (const value of ['\ud800', 'a\udfff', '\ud800a']) assert.throws(() => roundtrip(type('string'), value));
});

test('records, tuples, lists, aliases and payload variants preserve structure', () => {
  const shape = { kind: 'record', fields: [
    ['body-bytes', bytes], ['pair', { kind: 'tuple', types: [type('s32'), type('string')] }],
    ['failure', error], ['enabled', type('bool')],
  ] };
  const value = { bodyBytes: new Uint8Array([0, 255, 17]), pair: [-7, 'hi'], failure: { tag: 'invalid', val: 'details' }, enabled: true };
  assert.deepEqual(roundtrip(shape, value), value);
  assert.throws(() => roundtrip(shape, { ...value, extra: 1 }));
  assert.throws(() => roundtrip(shape, { ...value, pair: [-7] }));
  assert.throws(() => roundtrip(bytes, [1, 2]));
  assert.throws(() => decode(bytes, '[256]', active()));
});

test('nested option none is distinct from some(none)', () => {
  const shape = { kind: 'option', type: { kind: 'option', type: type('string') } };
  for (const value of [{ tag: 'none' }, { tag: 'some', val: { tag: 'none' } }, { tag: 'some', val: { tag: 'some', val: '' } }]) {
    assert.deepEqual(roundtrip(shape, value), value);
  }
  for (const value of [null, undefined, { tag: 'none', val: null }, { tag: 'some' }, { tag: 'bad' }]) assert.throws(() => roundtrip(shape, value));
});

test('unit results are not coerced into undefined successes', () => {
  const shape = result(unit);
  assert.deepEqual(roundtrip(shape, { tag: 'ok', val: undefined }), { tag: 'ok', val: undefined });
  assert.deepEqual(roundtrip(shape, { tag: 'err', val: { tag: 'uncertain' } }), { tag: 'err', val: { tag: 'uncertain' } });
  for (const value of [undefined, { tag: 'ok' }, { tag: 'ok', val: null }, { tag: 'err', val: { tag: 'unknown' } }]) assert.throws(() => roundtrip(shape, value));
});

test('enums and flags reject unknown or repeated cases', () => {
  const fields = [['read', unit], ['write', unit]];
  assert.deepEqual(roundtrip({ kind: 'flags', fields }, new Set(['write', 'read'])), new Set(['read', 'write']));
  assert.equal(roundtrip({ kind: 'enum', fields }, 'read'), 'read');
  assert.throws(() => roundtrip({ kind: 'flags', fields }, new Set(['admin'])));
  assert.throws(() => decode({ kind: 'flags', fields }, '["read","read"]', active()));
  assert.throws(() => roundtrip({ kind: 'enum', fields }, 'admin'));
});

test('wire limits reject large and deeply nested inputs', () => {
  assert.throws(() => stringify('x'.repeat(1024 * 1024)));
  assert.throws(() => parse('"' + 'x'.repeat(1024 * 1024) + '"'));
  assert.throws(() => decode({ kind: 'list', type: type('u32') }, JSON.stringify(Array(131073).fill(1)), active()));
  let shape = type('string'), value = 'done';
  for (let i = 0; i < 65; i += 1) { shape = { kind: 'list', type: shape }; value = [value]; }
  assert.throws(() => encode(shape, value, active()));
});

test('plain records neither run getters nor accept inherited fields', () => {
  const shape = { kind: 'record', fields: [['value', type('string')]] };
  let reads = 0;
  assert.throws(() => encode(shape, { get value() { reads += 1; return 'bad'; } }, active()));
  assert.equal(reads, 0);
  assert.throws(() => encode(shape, Object.create({ value: 'inherited' }), active()));
  const value = Object.create(null); value.value = 'explicit';
  assert.deepEqual(roundtrip(shape, value), { value: 'explicit' });
});

const resource = { kind: 'resource', identity: 'latent:test/resources@1.0.0#chunk' };
const borrow = { kind: 'borrow', type: resource };
function acquire(scope, host, token = 1) { return call(scope, broker(() => String(token), host.drop), 'acquire', [], resource, []); }

test('resource identities cannot be forged or borrowed across activations', () => {
  const one = active(), two = active(), drops = [];
  const host = broker(() => 'null', (_, token) => drops.push(token));
  const owner = acquire(one, host);
  assert.throws(() => new Resource(Symbol('guest-resource-construction')));
  assert.throws(() => call(one, host, 'read', [borrow], unit, [1]));
  assert.throws(() => call(two, host, 'read', [borrow], unit, [owner]));
  assert.throws(() => call(one, host, 'read', [{ kind: 'borrow', type: { ...resource, identity: 'other' } }], unit, [owner]));
  one.close(); two.close();
  assert.deepEqual(drops, [1]);
});

test('borrow retains ownership and close disposes exactly once', () => {
  const scope = active(), calls = [], drops = [];
  const host = broker((name, input) => { calls.push([name, JSON.parse(input)]); return 'null'; }, (_, token) => drops.push(token));
  const owner = acquire(scope, host);
  call(scope, host, 'read', [borrow], unit, [owner]);
  call(scope, host, 'read', [borrow], unit, [owner]);
  owner.dispose(); owner.dispose();
  assert.throws(() => call(scope, host, 'read', [borrow], unit, [owner]));
  scope.close();
  assert.equal(calls.length, 2);
  assert.deepEqual(drops, [1]);
});

test('owned arguments are consumed on typed failure without an implicit retry', () => {
  const scope = active(), drops = [];
  let attempts = 0;
  const host = broker(() => { attempts += 1; return '{"tag":"err","val":{"tag":"uncertain"}}'; }, (_, token) => drops.push(token));
  const owner = acquire(scope, host);
  assert.deepEqual(call(scope, host, 'finish', [resource], result(unit), [owner]), { tag: 'err', val: { tag: 'uncertain' } });
  assert.throws(() => call(scope, host, 'finish', [resource], result(unit), [owner]));
  scope.close();
  assert.equal(attempts, 1); assert.deepEqual(drops, []);
});

test('argument validation is atomic with respect to ownership transfer', () => {
  const scope = active(), drops = [];
  let calls = 0;
  const host = broker(() => { calls += 1; return 'null'; }, (_, token) => drops.push(token));
  const owner = acquire(scope, host);
  assert.throws(() => call(scope, host, 'move', [resource, u64], unit, [owner, 1]));
  assert.throws(() => call(scope, host, 'move', [resource, resource], unit, [owner, owner]));
  assert.throws(() => call(scope, host, 'move', [borrow, resource], unit, [owner, owner]));
  assert.throws(() => call(scope, host, 'move', [resource, borrow], unit, [owner, owner]));
  scope.close();
  assert.equal(calls, 0); assert.deepEqual(drops, [1]);
});

test('resource cleanup continues after a destructor trap, and never retries it', () => {
  const scope = active(), drops = [];
  const host = broker(() => 'null', (_, token) => { drops.push(token); if (token === 1) throw new Error('destructor-trap'); });
  acquire(scope, host, 1); acquire(scope, host, 2);
  assert.throws(() => scope.close(), /destructor-trap/);
  assert.deepEqual(drops, [1, 2]);
  assert.throws(() => scope.begin(), /reuse-denied/);
});

test('duplicate returned tokens and excess owners fail closed', () => {
  const scope = active(), host = broker(() => 'null');
  acquire(scope, host);
  assert.throws(() => acquire(scope, host));
  for (let token = 2; token <= 256; token += 1) acquire(scope, host, token);
  assert.throws(() => acquire(scope, host, 257));
  scope.close();
});

test('capability traps stay traps; capability failures stay typed values', () => {
  const scope = active(); let attempts = 0;
  const trap = new Error('host-trap');
  assert.throws(() => call(scope, broker(() => { attempts += 1; throw trap; }), 'send', [], result(bytes), []), error => error === trap);
  assert.deepEqual(call(scope, broker(() => '{"tag":"err","val":{"tag":"denied"}}'), 'send', [], result(bytes), []), { tag: 'err', val: { tag: 'denied' } });
  assert.equal(attempts, 1); scope.close();
});

test('unstarted and closed scopes cannot make capability calls', () => {
  const scope = new Scope(); let calls = 0;
  const host = broker(() => { calls += 1; return 'null'; });
  assert.throws(() => call(scope, host, 'read', [], unit, []));
  scope.begin(); scope.close();
  assert.throws(() => call(scope, host, 'read', [], unit, []));
  assert.throws(() => scope.begin());
  assert.equal(calls, 0);
});

test('secrets zeroize on explicit disposal and activation exit', () => {
  const scope = active();
  const secretValue = value => ({ bytes: new Uint8Array(value), mediaType: 'text/plain', version: { tag: 'none' }, expiresAtUnixMillis: { tag: 'none' } });
  const first = secretValue([1, 2]), second = secretValue([3, 4]);
  const secret = new Secret(scope, first); new Secret(scope, second);
  const applicationCopy = secret.use(bytes => Uint8Array.from(bytes));
  secret.dispose(); secret.dispose();
  assert.deepEqual(first.bytes, new Uint8Array([0, 0]));
  assert.throws(() => secret.use(() => {}));
  scope.close();
  assert.deepEqual(second.bytes, new Uint8Array([0, 0]));
  assert.deepEqual(applicationCopy, new Uint8Array([1, 2]));
});

test('chunk helper destroys ownership after success and typed error', async () => {
  const scope = active(), drops = [];
  const host = broker(() => 'null', (_, token) => drops.push(token));
  const value = { tag: 'err', val: { tag: 'denied' } };
  assert.deepEqual(await chunkBytes(acquire(scope, host), async () => value), value);
  assert.deepEqual(drops, [1]); scope.close();
});

test('blob helpers serialize ownership and consume seal or close on every outcome', async () => {
  let closed = 0;
  const owner = new BlobHandle(9007199254740993n, async value => { assert.equal(value, 9007199254740993n); closed += 1; return { tag: 'ok', val: true }; });
  let release;
  const pending = owner.use(() => new Promise(resolve => { release = resolve; }));
  await assert.rejects(owner.close(), /busy/);
  release('done'); assert.equal(await pending, 'done');
  assert.deepEqual(await owner.close(), { tag: 'ok', val: true });
  await assert.rejects(owner.close(), /closed/);
  assert.equal(closed, 1);
  const seal = new BlobHandle(5n, async () => { throw new Error('should-not-close'); });
  assert.deepEqual(await seal.consume(async () => ({ tag: 'err', val: 'uncertain' })), { tag: 'err', val: 'uncertain' });
  await assert.rejects(seal.use(async () => true), /closed/);
});
