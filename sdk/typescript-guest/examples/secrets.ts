import type * as Contract from '../generated/interfaces/tests-local-secrets-api.js';
import * as secrets from '../vendor/lsf/sdk/typescript-guest/capabilities/secrets.js';
export const api: typeof Contract = {
  run(_which, reference) {
    const result = secrets.read(reference);
    if (result.tag === 'err') return ({ 'permission-denied': 10n, 'not-found': 11n, expired: 12n, unavailable: 13n })[result.val.tag];
    const secret = result.val;
    try {
      const owned = secret.use(bytes => bytes);
      const copy = Uint8Array.from(owned);
      const original = [...copy];
      const length = BigInt(owned.length);
      secret.close();
      secret.close();
      if (owned.some(byte => byte !== 0)) throw new Error('secret-not-zeroed');
      if (copy.some((byte, index) => byte !== original[index])) throw new Error('application-copy-was-modified');
      let rejected = false;
      try { secret.use(() => 0); }
      catch (error) { rejected = error instanceof Error && error.message === 'secret-closed'; }
      if (!rejected) throw new Error('closed-secret-reused');
      return length;
    }
    finally { secret.close(); }
  },
};
