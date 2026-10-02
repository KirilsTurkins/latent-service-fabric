import * as raw from 'latent:intents/staging@0.1.0';
import { Command } from './state.js';
import { borrowCommand } from './state-internal.js';
import { enumCall, type Result } from './result.js';
export type { IntentError, StagedIntent } from 'latent:intents/staging@0.1.0';
const errors: readonly raw.IntentError[] = ['permission-denied', 'invalid-binding', 'invalid-operation',
  'invalid-payload', 'invalid-expiry', 'count-limit', 'byte-limit', 'handle-closed', 'wrong-activation', 'wrong-mode',
  'unsupported-profile', 'cancelled', 'unavailable'];

/** Logical binding and payload only. Host policy controls provider and delivery. */
export class Intent {
  #expiry: bigint | undefined;
  constructor(private readonly binding: string, private readonly operation: string, private readonly payload: raw.Value) {}
  expiresAt(unixMillis: bigint): this {
    if (typeof unixMillis !== 'bigint' || unixMillis < 0n || unixMillis > 18446744073709551615n) {
      throw new Error('intent-expiry-u64');
    }
    this.#expiry = unixMillis;
    return this;
  }
  stage(command: Command): Result<raw.StagedIntent, raw.IntentError> {
    return enumCall(() => command[borrowCommand](owner => raw.stage(owner, {
      binding: this.binding, operation: this.operation, payload: this.payload,
      expiresAtUnixMillis: this.#expiry })), errors);
  }
}
