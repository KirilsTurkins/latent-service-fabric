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

test('oversized backing storage is rejected before cloning it', () => {
  const buffer = new ArrayBuffer(9 * 1024 * 1024);
  const huge = new Uint8Array(buffer, 0, 1);
  const value = { command: { ...selector, extra: huge }, authorizationPublication: publication };
  const original = globalThis.structuredClone;
  let clonedHuge = false;
  globalThis.structuredClone = (data, ...options) => {
    if (data?.extra === huge) clonedHuge = true;
    return original(data, ...options);
  };
  try {
    assert.deepEqual(identity('lookupCommand', value), {});
    assert.equal(clonedHuge, false);
  } finally { globalThis.structuredClone = original; }
});

test('deep or accessor-bearing extra recovery data is refused', () => {
  let deep = {}; for (let i = 0; i < 18; i++) deep = { nested: deep };
  assert.deepEqual(identity('lookupCommand', { command: { ...selector, extra: deep }, authorizationPublication: publication }), {});
  const extra = {}; Object.defineProperty(extra, 'value', { enumerable: true, get() { throw new Error('getter executed'); } });
  assert.deepEqual(identity('lookupCommand', { command: { ...selector, extra }, authorizationPublication: publication }), {});
});
