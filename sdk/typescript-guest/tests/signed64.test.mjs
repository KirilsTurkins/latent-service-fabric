import assert from 'node:assert/strict';
import test from 'node:test';
import { coreI64Lowering, coreIntegerLowering } from '../../../tools/typescript_guest/signed64.mjs';

const intrinsic = `function toInt64(val) {
  const converted = BigInt(val)
  return BigInt.asIntN(64, converted);
}`;

test('signed lowering preserves every tested canonical 64-bit pattern', () => {
  const lower = new Function(coreI64Lowering(intrinsic) + '; return toInt64;')();
  for (const value of [-(1n << 63n), -2n, -1n, 0n, 1n, (1n << 63n) - 1n]) {
    const raw = lower(value);
    assert(raw >= 0n && raw <= (1n << 64n) - 1n);
    assert.equal(BigInt.asIntN(64, raw), value);
    const memory = new DataView(new ArrayBuffer(8));
    memory.setBigInt64(0, raw, true);
    assert.equal(memory.getBigInt64(0, true), value);
  }
});

test('unsigned 32-bit lowering uses signed core bits, without truncating its width', () => {
  const source = 'function toUint32(val) { return val >>> 0; }';
  const lower = new Function(coreIntegerLowering(source) + '; return toUint32;')();
  for (const value of [0, 1, 0x7fff_ffff, 0x8000_0000, 0xffff_ffff]) {
    assert.equal(lower(value) | 0, lower(value));
    assert.equal(lower(value) >>> 0, value);
  }
  for (const drift of [source + source, source.replace('>>> 0', '>>> 1')]) {
    assert.throws(() => coreIntegerLowering(drift), /intrinsic-drift/);
  }
});

test('only the pinned lower intrinsic changes, never signed lifting or user code', () => {
  const lift = '\nfunction lift(v) { return BigInt.asIntN(64, v); }';
  assert(coreI64Lowering(intrinsic + lift).endsWith(lift));
  assert.equal(coreI64Lowering(lift), lift);
  for (const changed of [intrinsic + intrinsic, intrinsic.replace('64,', '32,'),
                        intrinsic.replace('BigInt(val)', 'Number(val)')]) {
    assert.throws(() => coreI64Lowering(changed), /intrinsic-drift/);
  }
});
