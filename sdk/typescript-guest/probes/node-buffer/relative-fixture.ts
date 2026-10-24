// Repository-owned relative fixture ONLY, not a published npm library.
import { Buffer } from 'buffer';
export function fixtureBytes(): Uint8Array {
  return Buffer.from('fixture-only', 'utf8');
}
export { Buffer as fixtureConstructor };
