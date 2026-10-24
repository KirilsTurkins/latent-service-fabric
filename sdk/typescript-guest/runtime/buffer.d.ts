/** lsf-node-buffer-v1: finite pure guest subset, 1 MiB per buffer.
 * Both `buffer` and `node:buffer` resolve to the same compiler-owned module.
 * No global Buffer, native storage, Node process or network authority is added.
 * Unsafe allocation is deliberately zero-filled. Unselected entrypoints throw.
 */
export type BufferEncoding = 'utf8' | 'utf-8' | 'hex' | 'ascii' | 'latin1' | 'binary' |
  'utf16le' | 'utf-16le' | 'ucs2' | 'ucs-2' | 'base64' | 'base64url';
export interface Buffer extends Uint8Array {
  subarray(start?: number, end?: number): Buffer;
  slice(start?: number, end?: number): Buffer;
  toString(encoding?: BufferEncoding, start?: number, end?: number): string;
  write(value: string, encoding?: BufferEncoding): number;
  write(value: string, offset?: number, encoding?: BufferEncoding): number;
  write(value: string, offset: number, length: number, encoding?: BufferEncoding): number;
  equals(other: Uint8Array): boolean;
  compare(target: Uint8Array, targetStart?: number, targetEnd?: number, sourceStart?: number, sourceEnd?: number): number;
  copy(target: Uint8Array, targetStart?: number, sourceStart?: number, sourceEnd?: number): number;
  fill(value: number | string | Uint8Array, start?: number, end?: number, encoding?: BufferEncoding): this;
  fill(value: string, encoding: BufferEncoding): this;
  fill(value: string, start: number, encoding: BufferEncoding): this;
  toJSON(): {type: 'Buffer'; data: number[]};
  readUInt8(offset?: number): number; readInt8(offset?: number): number;
  readUInt16LE(offset?: number): number; readUInt16BE(offset?: number): number;
  readInt16LE(offset?: number): number; readInt16BE(offset?: number): number;
  readUInt32LE(offset?: number): number; readUInt32BE(offset?: number): number;
  readInt32LE(offset?: number): number; readInt32BE(offset?: number): number;
  writeUInt8(value: number, offset?: number): number; writeInt8(value: number, offset?: number): number;
  writeUInt16LE(value: number, offset?: number): number; writeUInt16BE(value: number, offset?: number): number;
  writeInt16LE(value: number, offset?: number): number; writeInt16BE(value: number, offset?: number): number;
  writeUInt32LE(value: number, offset?: number): number; writeUInt32BE(value: number, offset?: number): number;
  writeInt32LE(value: number, offset?: number): number; writeInt32BE(value: number, offset?: number): number;
  readUIntLE(offset: number, byteLength: number): number; readUIntBE(offset: number, byteLength: number): number;
  readIntLE(offset: number, byteLength: number): number; readIntBE(offset: number, byteLength: number): number;
  writeUIntLE(value: number, offset: number, byteLength: number): number; writeUIntBE(value: number, offset: number, byteLength: number): number;
  writeIntLE(value: number, offset: number, byteLength: number): number; writeIntBE(value: number, offset: number, byteLength: number): number;
  readBigUInt64LE(offset?: number): bigint; readBigUInt64BE(offset?: number): bigint;
  readBigInt64LE(offset?: number): bigint; readBigInt64BE(offset?: number): bigint;
  writeBigUInt64LE(value: bigint, offset?: number): number; writeBigUInt64BE(value: bigint, offset?: number): number;
  writeBigInt64LE(value: bigint, offset?: number): number; writeBigInt64BE(value: bigint, offset?: number): number;
  readUint8: Buffer['readUInt8']; readUint16LE: Buffer['readUInt16LE']; readUint16BE: Buffer['readUInt16BE'];
  readUint32LE: Buffer['readUInt32LE']; readUint32BE: Buffer['readUInt32BE'];
  writeUint8: Buffer['writeUInt8']; writeUint16LE: Buffer['writeUInt16LE']; writeUint16BE: Buffer['writeUInt16BE'];
  writeUint32LE: Buffer['writeUInt32LE']; writeUint32BE: Buffer['writeUInt32BE'];
  readUintLE: Buffer['readUIntLE']; readUintBE: Buffer['readUIntBE'];
  writeUintLE: Buffer['writeUIntLE']; writeUintBE: Buffer['writeUIntBE'];
  readBigUint64LE: Buffer['readBigUInt64LE']; readBigUint64BE: Buffer['readBigUInt64BE'];
  writeBigUint64LE: Buffer['writeBigUInt64LE']; writeBigUint64BE: Buffer['writeBigUInt64BE'];
}
export interface BufferConstructor {
  readonly prototype: Buffer;
  new(size?: number): Buffer;
  new(value: ArrayBuffer, byteOffset?: number, length?: number): Buffer;
  from(value: string, encoding?: BufferEncoding): Buffer;
  from(value: ArrayBuffer, byteOffset?: number, length?: number): Buffer;
  from(value: readonly number[] | Uint8Array | Uint8ClampedArray | Uint16Array | Uint32Array |
    Int8Array | Int16Array | Int32Array | Float32Array | Float64Array | {type: 'Buffer'; data: number[]}): Buffer;
  alloc(size: number, fill?: number | string | Uint8Array, encoding?: BufferEncoding): Buffer;
  allocUnsafe(size: number): Buffer; allocUnsafeSlow(size: number): Buffer;
  isBuffer(value: unknown): value is Buffer;
  isEncoding(value: unknown): value is BufferEncoding;
  byteLength(value: string | ArrayBuffer | ArrayBufferView, encoding?: BufferEncoding): number;
  concat(values: readonly Uint8Array[], totalLength?: number): Buffer;
  compare(a: Uint8Array, b: Uint8Array): number;
}
export const Buffer: BufferConstructor;
export function SlowBuffer(size: number): Buffer;
export const kMaxLength: number;
export const kStringMaxLength: number;
export const constants: Readonly<{MAX_LENGTH: number; MAX_STRING_LENGTH: number}>;
declare const module: Readonly<{Buffer: BufferConstructor; SlowBuffer: typeof SlowBuffer;
  constants: typeof constants; kMaxLength: number; kStringMaxLength: number}>;
export default module;
