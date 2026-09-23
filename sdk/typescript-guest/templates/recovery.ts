import type * as Contract from '../generated/interfaces/examples-recovery-api.js';

let calls = 0;
export const api: typeof Contract = {
  run(which) {
    if (which === 1) throw new Error('deliberate guest failure');
    if (which === 2) {
      const retained: Uint8Array[] = [];
      for (let n = 0; n < 32; n++) retained.push(new Uint8Array(16 * 1024 * 1024));
      return retained.length;
    }
    if (which === 3) for (;;) { /* host fuel, deadline and cancellation remain active */ }
    return ++calls;
  },
};
