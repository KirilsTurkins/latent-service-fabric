import type * as Contract from '../generated/interfaces/examples-http-status-api.js';
import { send } from '../vendor/lsf/sdk/typescript-guest/capabilities/http.js';
import { unwrap } from '../vendor/lsf/sdk/typescript-guest/capabilities/result.js';

export const api: typeof Contract = {
  check(url) {
    return unwrap(send({ method: 'get', url, headers: [], body: undefined, timeoutMillis: 5000n })).status;
  },
};
