import * as state from 'latent:state/key-value@0.2.0';
import * as intents from 'latent:intents/staging@0.1.0';
import { drop } from '../vendor/lsf/sdk/typescript-guest/capabilities/owner.js';

// Stackful compiler projection preserves the authoritative async host signature.
export const api = {
  run(mode: number): bigint {
    if (mode === 0) {
      const view = state.acquireQuery();
      try {
        const identity = state.queryInfo(view);
        const value = state.getQuery(view, new Uint8Array([107]));
        const page = state.scanQuery(view, new Uint8Array(), 1, undefined);
        try {
          const bounds = state.describePage(page);
          const item = state.pageNext(page);
          return BigInt(identity.version.length + bounds.entryCount
            + (value === undefined ? 0 : 1) + (item === undefined ? 0 : 1));
        } finally { drop(page); }
      } finally { drop(view); }
    }
    const transaction = state.acquireCommand();
    try {
      const identity = state.info(transaction);
      const existing = state.get(transaction, new Uint8Array([107]));
      const payload: state.Value = { bytes: new Uint8Array(), mediaType: 'application/octet-stream',
        metadata: [['present', '']] };
      state.put(transaction, new Uint8Array([107]), payload);
      state.delete(transaction, new Uint8Array([107]));
      const page = state.scan(transaction, new Uint8Array(), 1, undefined);
      try {
        const bounds = state.describePage(page);
        const item = state.pageNext(page);
        const staged = intents.stage(transaction, { binding: 'approved-mail', operation: 'send',
          payload, expiresAtUnixMillis: 18446744073709551615n });
        return BigInt(staged.sequence + bounds.entryCount + identity.commandId.length
          + (existing === undefined ? 0 : 1) + (item === undefined ? 0 : 1));
      } finally { drop(page); }
    } finally { drop(transaction); }
  }
};
