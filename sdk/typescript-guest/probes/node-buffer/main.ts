import type * as Contract from '../generated/interfaces/examples-typescript-buffer-api.js';
import nodeModule, { Buffer as Named, kMaxLength, kStringMaxLength } from 'node:buffer';
import bareModule, { Buffer as Bare } from 'buffer';
import { fixtureBytes, fixtureConstructor } from './relative-fixture.js';

let entries = 0;
function check(value: unknown, label: string): asserts value {
  if (!value) throw new Error('buffer-probe:' + label);
}
function refuses(operation: () => unknown, code?: string) {
  let refused = false;
  try { operation(); } catch (error) {
    refused = error instanceof Error && (code === undefined ||
      (error as Error & {code?: string}).code === code);
  }
  check(refused, 'expected-refusal');
}

export const api: typeof Contract = {
  run(which) {
    check(++entries === 1, 'fresh-module-state');
    switch (which) {
      case 0: {
        check(Named === Bare && nodeModule === bareModule &&
          nodeModule.Buffer === Named && fixtureConstructor === Named, 'one-constructor');
        const value = Bare.from([0, 255, 128]);
        check(Named.isBuffer(value) && value instanceof Uint8Array &&
          value.toString('hex') === '00ff80', 'real-buffer');
        break;
      }
      case 1: {
        const backing = new ArrayBuffer(12), view = Named.from(backing, 2, 6);
        view.set([1, 2, 3, 4, 5, 6]);
        const copy = Bare.from(view), slice = view.slice(-4, -1), sub = view.subarray(1, 4);
        slice[0] = 77; sub[0] = 88;
        check(view[1] === 88 && view[2] === 77 && copy[1] === 2 && copy[2] === 3 &&
          slice.buffer === backing && sub.buffer === backing && view.byteOffset === 2,
          'copy-versus-shared-view');
        check(view.copy(view, 1, 0, 5) === 5 && view.toString('hex') === '0101584d0405', 'overlap');
        break;
      }
      case 2: {
        const value = Named.alloc(8, 0xaa);
        check(value.write('é😀Z', 1, 5, 'utf8') === 2 &&
          value.toString('hex') === 'aac3a9aaaaaaaaaa', 'whole-utf8-write');
        check(Bare.from([239, 187, 191, 65]).toString() === '\ufeffA' &&
          Named.from([255]).toString() === '\ufffd' &&
          Named.from('\ud800').toString('hex') === 'efbfbd', 'utf8-replacement-bom');
        check(Named.from([0, 216, 1]).toString('utf16le').charCodeAt(0) === 0xd800,
          'utf16-code-unit-and-odd-tail');
        break;
      }
      case 3: {
        check(Named.from('ff10zz20', 'hex').toString('hex') === 'ff10' &&
          Named.from('f\u0131', 'hex').toString('hex') === 'f1', 'partial-low-byte-hex');
        check(Named.from('\u0154Q==', 'base64').toString() === 'M' &&
          Named.from('YW-J_j==\n', 'base64').toString('base64url') === 'YW-J_g' &&
          Named.from('Aé😀\ud800Z', 'base64').length === 0, 'base64-low-byte-padding');
        check(Named.from('é', 'ascii')[0] === 233 && Named.from([233]).toString('ascii') === 'i' &&
          Named.from('é', 'latin1').toString('hex') === 'e9' &&
          Named.from('A', 'ucs2').toString('hex') === '4100', 'ascii-latin-utf16');
        break;
      }
      case 4: {
        const value = Named.alloc(24);
        check(value.writeUInt32BE(0x12345678, 1) === 5 && value.readUint32BE(1) === 0x12345678,
          'fixed-endian');
        value.writeIntLE(-37, 5, 6); check(value.readIntLE(5, 6) === -37, 'six-byte-signed');
        value.writeBigUInt64LE((1n << 64n) - 1n, 12);
        check(value.readBigUint64LE(12) === (1n << 64n) - 1n, 'bigint-endian');
        refuses(() => value.writeUInt8(256), 'ERR_OUT_OF_RANGE');
        refuses(() => value.readUInt32LE(22), 'ERR_OUT_OF_RANGE');
        check(value.readUInt32BE(1) === 0x12345678, 'range-refusal-preserves-bytes');
        break;
      }
      case 5: {
        const value = Named.from([1, 2, 3, 4, 5]);
        value.fill(value.subarray(0, 2), 1, 5);
        check(value.toString('hex') === '0101020102', 'snapshot-aliased-fill');
        check(Named.concat([Named.from([1, 2]), Bare.from([3, 4])], 3).toString('hex') === '010203' &&
          Named.concat([Named.from([1])], 4).toString('hex') === '01000000', 'bounded-concat');
        check(Named.compare(Named.from([1, 2]), Bare.from([1, 2, 0])) === -1 &&
          Named.from([1, 2]).equals(Bare.from([1, 2])), 'byte-compare');
        break;
      }
      case 6: {
        check(kMaxLength === 1048576 && kStringMaxLength === 4194304, 'profile-ceilings');
        refuses(() => Named.alloc(kMaxLength + 1), 'ERR_OUT_OF_RANGE');
        refuses(() => Named.from('€'.repeat(Math.floor(kMaxLength / 3) + 1)), 'ERR_OUT_OF_RANGE');
        refuses(() => Named.from('x'.repeat(kStringMaxLength + 1)), 'ERR_OUT_OF_RANGE');
        refuses(() => Named.from('x', 'made-up' as 'utf8'), 'ERR_UNKNOWN_ENCODING');
        const unavailable = Named.alloc(1) as unknown as {readFloatLE(): unknown};
        refuses(() => unavailable.readFloatLE(), 'ERR_BUFFER_UNSUPPORTED');
        check(Named.allocUnsafe(4).toString('hex') === '00000000' &&
          Bare.allocUnsafeSlow(3).toString('hex') === '000000', 'truthful-zero-fill');
        break;
      }
      case 7: {
        const bytes = fixtureBytes();
        check(Named.isBuffer(bytes) && Named.from(bytes).toString() === 'fixture-only' &&
          fixtureConstructor === Named, 'repository-relative-fixture-only');
        break;
      }
      default: throw new Error('buffer-probe:unknown-case');
    }
    return 'buffer:' + which + ':pass|fresh=1';
  },
};
