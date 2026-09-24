import * as raw from 'latent:random/random@0.1.0';
import { call } from './result.js';
export type { RandomError } from 'latent:random/random@0.1.0';
const errors: readonly raw.RandomError['tag'][] = ['invalid-length', 'budget-exhausted', 'unavailable'];
export function bytes(length: number) { return call<Uint8Array, raw.RandomError>(() => raw.bytes(length), errors); }
export function u64() { return call<bigint, raw.RandomError>(() => raw.u64Value(), errors); }
