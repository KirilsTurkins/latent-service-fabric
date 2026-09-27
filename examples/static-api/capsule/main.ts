import type * as Contract from '../generated/interfaces/latent-web-application.js';
import { send } from '../vendor/lsf/sdk/typescript-guest/capabilities/http.js';
import { handle } from './status.js';

// The approved destination is captured in the capsule source. No browser value
// can change its origin, path, method, credentials, redirect policy or timeout.
export const application: typeof Contract = {
  handle(request) {
    return handle(request, () => send({
      method: 'get', url: 'https://status.backend.test/health', headers: [],
      body: undefined, bodyMediaType: undefined, idempotencyKey: undefined,
      timeoutMillis: 1500n,
    }));
  },
};
