import type * as Contract from '../generated/interfaces/tests-caller-api.js';
import { call } from '../vendor/lsf/sdk/typescript-guest/capabilities/service.js';
export const api: typeof Contract = {
  run(which) {
    const result = call({ service: 'callee', contract: 'tests:local/api@1.0.0',
      function: which === 0 ? 'answer' : which === 1 ? 'fail' : 'spin', route: 'callee' },
    new Uint8Array([91, 93]), 'application/vnd.latent.wit-values.v1+json', { priority: 0, metadata: [] });
    if (result.tag === 'declared-error') {
      if (result.val.payload.length === 0) throw new Error('missing-declared-payload');
      return 10n;
    }
    if (result.tag === 'platform-failure') {
      switch (result.val.code) {
        case 'permission-denied': return 11n;
        case 'cancelled': return 12n;
        case 'deadline-exceeded': return 13n;
        case 'resource-exhausted': return 14n;
        default: throw new Error('unexpected-child-failure');
      }
    }
    if (result.val.payload.length !== 4 || result.val.payload.some((byte, i) => byte !== [91, 52, 50, 93][i]))
      throw new Error('child-payload-mismatch');
    return 42n;
  },
};
