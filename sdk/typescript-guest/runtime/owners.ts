import { BoundaryError, type Result, type Option, type Resource, type Scope } from './codec.js';

/** Zeroizes the owned result; caller-created copies remain caller-owned. */
export class Secret {
  #bytes: Uint8Array;
  #scope: Scope;
  #close: (() => void) | undefined;
  readonly mediaType: string;
  readonly version: Option<string>;
  readonly expiresAtUnixMillis: Option<bigint>;
  constructor(scope: Scope, value: { bytes: Uint8Array; mediaType: string; version: Option<string>; expiresAtUnixMillis: Option<bigint> }) {
    this.#scope = scope;
    this.#bytes = value.bytes;
    this.#close = scope.secret(this.#bytes);
    this.mediaType = value.mediaType;
    this.version = value.version;
    this.expiresAtUnixMillis = value.expiresAtUnixMillis;
  }
  use<T>(read: (bytes: Readonly<Uint8Array>) => T): T {
    this.#scope.check();
    if (!this.#close) throw new BoundaryError('secret-closed');
    return read(this.#bytes);
  }
  dispose(): void { this.#close?.(); this.#close = undefined; }
}

/** One materialization; destructor runs even when the host returns a typed error. */
export async function chunkBytes<E>(chunk: Resource,
    materialize: (chunk: Resource) => Promise<Result<Uint8Array, E>>): Promise<Result<Uint8Array, E>> {
  try { return await materialize(chunk); } finally { chunk.dispose(); }
}

/** Primitive blob handles are not resources: closing is explicit and async. */
export class BlobHandle<E> {
  #handle: bigint | undefined;
  #busy = false;
  constructor(handle: bigint, readonly closeHandle: (handle: bigint) => Promise<Result<boolean, E>>) {
    this.#handle = handle;
  }
  async use<T>(operation: (handle: bigint) => Promise<T>): Promise<T> {
    if (this.#handle === undefined || this.#busy) throw new BoundaryError('blob-closed-or-busy');
    this.#busy = true;
    try { return await operation(this.#handle); } finally { this.#busy = false; }
  }
  async consume<T>(operation: (handle: bigint) => Promise<T>): Promise<T> {
    if (this.#handle === undefined || this.#busy) throw new BoundaryError('blob-closed-or-busy');
    const handle = this.#handle;
    this.#handle = undefined;
    return operation(handle); // No retry on error or uncertain outcome.
  }
  close(): Promise<Result<boolean, E>> { return this.consume(handle => this.closeHandle(handle)); }
}
