import type * as Contract from '../generated/interfaces/tests-http-api.js';
import * as http from '../vendor/lsf/sdk/typescript-guest/capabilities/http.js';
import { unwrap } from '../vendor/lsf/sdk/typescript-guest/capabilities/result.js';
export const api: typeof Contract = {
  run(which, url) {
    const result = http.send({ method: which === 0 ? 'get' : which === 1 ? 'head' : 'post', url,
      headers: [], body: new Uint8Array([112, 97, 121, 108, 111, 97, 100]),
      bodyMediaType: 'text/plain', timeoutMillis: 1000n });
    if (result.tag === 'err' && result.val.tag === 'permission-denied') return 10n;
    if (result.tag === 'err' && result.val.tag === 'uncertain') return 11n;
    const response = unwrap(result);
    return BigInt(response.status) + 1000n * BigInt(response.body.length);
  },
};
