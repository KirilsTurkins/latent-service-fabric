import * as raw from 'latent:blob/blob@0.2.0';
import { Owner, drop } from './owner.js';
import { call } from './result.js';
export type { BlobReference, BlobError } from 'latent:blob/blob@0.2.0';
export type Handle = Owner<raw.BlobHandle, 'blob-handle'>;
export type Chunk = Owner<raw.Chunk, 'blob-chunk'>;
const errors: readonly raw.BlobError['tag'][] = ['not-found', 'permission-denied', 'invalid-range',
  'invalid-state', 'checksum-mismatch', 'budget-exhausted', 'unavailable', 'uncertain',
  'deadline-exceeded', 'cancelled'];
function invoke<T>(operation: () => T) { return call<T, raw.BlobError>(operation, errors); }
function owned(handle: raw.BlobHandle): Handle {
  return new Owner(handle, value => { raw.close(value); });
}
export function create(mediaType: string, expectedSize?: bigint) {
  return invoke(() => owned(raw.create(mediaType, expectedSize)));
}
export function open(reference: raw.BlobReference) { return invoke(() => owned(raw.open(reference))); }
export function write(handle: Handle, offset: bigint, bytes: Uint8Array) {
  return invoke(() => handle.borrow(value => raw.write(value, offset, bytes)));
}
export function read(handle: Handle, offset: bigint, length: number) {
  return invoke((): Chunk => handle.borrow(value => new Owner(raw.read(value, offset, length), drop)));
}
export function chunkBytes(chunk: Chunk) { return invoke(() => chunk.borrow(raw.chunkBytes)); }
export function seal(handle: Handle) { return invoke(() => handle.consume(raw.seal)); }
export function close(handle: Handle) { return invoke(() => handle.consume(raw.close)); }
