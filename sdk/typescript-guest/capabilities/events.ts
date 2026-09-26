import * as raw from 'latent:events/publisher@0.2.0';
import { call } from './result.js';
export type { Event, PublishReceipt, EventError } from 'latent:events/publisher@0.2.0';
const errors: readonly raw.EventError['tag'][] = ['invalid-topic', 'invalid-event', 'permission-denied',
  'budget-exhausted', 'deadline-exceeded', 'cancelled', 'unavailable', 'uncertain'];
/** A receipt acknowledges publication, not consumer processing or permission to retry. */
export function publish(event: raw.Event) {
  return call<raw.PublishReceipt, raw.EventError>(() => raw.publish(event), errors);
}
