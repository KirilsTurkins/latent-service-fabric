// Compiler-private pure guest provision; no application installer or authority.
import {Buffer as originalBuffer} from 'node:buffer';
if (Object.getOwnPropertyDescriptor(globalThis, 'Buffer') !== undefined)
  throw new Error('compiler-owned-buffer-global-already-present');
Object.defineProperty(globalThis, 'Buffer', {
  value: originalBuffer, writable: true, configurable: true, enumerable: false,
});
