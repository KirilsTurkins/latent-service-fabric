import assert from 'node:assert/strict';
import test from 'node:test';
import { identity } from '../../dist/node/transaction.js';
const namespace = { tenant: 'tests', namespace: 'sample', incarnation: '1' };
const selector = { namespace, operation: 'update', clientKey: 'original' };
const publication = { tenant: 'tests', id: `publication:sha256:${'2'.repeat(64)}` };

test('recovery snapshot retains original scope without retaining mutable source', () => {
  const result = identity('lookupCommand', { command: selector, authorizationPublication: publication });
  assert.deepEqual(result.command, selector);
  assert.notEqual(result.command, selector);
  assert.notEqual(result.command.namespace, selector.namespace);
  assert.deepEqual(result.authorizationPublication, publication);
});

test('a short view copies only selected bytes and keeps the original recovery key', () => {
  const buffer = new ArrayBuffer(9 * 1024 * 1024);
  const view = new Uint8Array(buffer, 17, 1); view[0] = 42;
  const result = identity('invokeCommand', { command: selector, invocation: { activationId: 'original' },
    expectedVersions: [{ key: view }] });
  assert.equal(result.command.clientKey, 'original');
  assert.equal(result.expectedVersions[0].key[0], 42);
  assert.equal(result.expectedVersions[0].key.buffer.byteLength, 1);
  view[0] = 9;
  assert.equal(result.expectedVersions[0].key[0], 42);
});

test('oversized, deep or accessor-bearing recovery data is refused', () => {
  assert.deepEqual(identity('lookupCommand', { command: { ...selector, extra: new Uint8Array(9 * 1024 * 1024) }, authorizationPublication: publication }), {});
  let deep = {}; for (let i = 0; i < 18; i++) deep = { nested: deep };
  assert.deepEqual(identity('lookupCommand', { command: { ...selector, extra: deep }, authorizationPublication: publication }), {});
  const extra = {}; Object.defineProperty(extra, 'value', { enumerable: true, get() { throw new Error('getter executed'); } });
  assert.deepEqual(identity('lookupCommand', { command: { ...selector, extra }, authorizationPublication: publication }), {});
});
