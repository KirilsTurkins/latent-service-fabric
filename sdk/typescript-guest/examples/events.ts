import type * as Contract from '../generated/interfaces/tests-nats-events-api.js';
import * as events from '../vendor/lsf/sdk/typescript-guest/capabilities/events.js';
import { unwrap } from '../vendor/lsf/sdk/typescript-guest/capabilities/result.js';
export const api: typeof Contract = {
  run(_which, topic, handle) {
    const result = events.publish({ topic, payload: new Uint8Array([112, 97, 121, 108, 111, 97, 100]),
      mediaType: 'text/plain', attributes: [], idempotencyKey: 'guest-sdk-' + handle.toString() });
    if (result.tag === 'err' && result.val.tag === 'permission-denied') return 10n;
    if (result.tag === 'err' && result.val.tag === 'uncertain') return 11n;
    return unwrap(result).sequence;
  },
};
