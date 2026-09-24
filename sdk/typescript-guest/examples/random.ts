import type * as Contract from '../generated/interfaces/tests-random-api.js';
import * as random from '../vendor/lsf/sdk/typescript-guest/capabilities/random.js';
import { unwrap } from '../vendor/lsf/sdk/typescript-guest/capabilities/result.js';
export const api: typeof Contract = {
  run(which) {
    if (which === 1) { unwrap(random.u64()); return 8n; }
    const result = random.bytes(which === 2 ? 0xffff_ffff : 32);
    if (result.tag === 'err' && result.val.tag === 'invalid-length') return 10n;
    return BigInt(unwrap(result).length);
  },
};
