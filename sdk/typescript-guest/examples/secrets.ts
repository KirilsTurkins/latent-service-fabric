import type * as Contract from '../generated/interfaces/tests-local-secrets-api.js';
import * as secrets from '../vendor/lsf/sdk/typescript-guest/capabilities/secrets.js';
export const api: typeof Contract = {
  run(_which, reference) {
    const result = secrets.read(reference);
    if (result.tag === 'err') return ({ 'permission-denied': 10n, 'not-found': 11n, expired: 12n, unavailable: 13n })[result.val.tag];
    const secret = result.val;
    try { return secret.use(bytes => BigInt(bytes.length)); }
    finally { secret.close(); }
  },
};
