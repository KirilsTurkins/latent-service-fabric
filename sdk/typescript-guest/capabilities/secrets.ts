import * as raw from 'latent:secrets/reader@0.1.0';
import { call } from './result.js';
export type { SecretError } from 'latent:secrets/reader@0.1.0';
const errors: readonly raw.SecretError['tag'][] = ['not-found', 'permission-denied', 'expired', 'unavailable'];
/** Zeroes this result's owned bytes. Application-created copies are separate owners. */
export class Secret {
  #value: raw.SecretValue | undefined;
  readonly mediaType: string;
  readonly version?: string;
  readonly expiresAtUnixMillis?: bigint;
  constructor(value: raw.SecretValue) {
    this.#value = value;
    this.mediaType = value.mediaType;
    this.version = value.version;
    this.expiresAtUnixMillis = value.expiresAtUnixMillis;
  }
  use<T>(read: (bytes: Readonly<Uint8Array>) => T): T {
    if (!this.#value) throw new Error('secret-closed');
    return read(this.#value.bytes);
  }
  close(): void { this.#value?.bytes.fill(0); this.#value = undefined; }
}
export function read(reference: string) {
  return call<Secret, raw.SecretError>(() => new Secret(raw.read(reference)), errors);
}
