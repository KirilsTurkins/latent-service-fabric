// lsf-example-begin: capsule
import type * as Contract from '../generated/interfaces/examples-transactional-aggregate-api.js';
import { Command, Query, type VersionedValue } from '../vendor/lsf/sdk/typescript-guest/capabilities/state.js';
import { Intent } from '../vendor/lsf/sdk/typescript-guest/capabilities/intents.js';
import type { Result } from '../vendor/lsf/sdk/typescript-guest/capabilities/result.js';
const key = new Uint8Array([97,103,103,114,101,103,97,116,101,47,99,111,117,110,116]);
const media = 'application/vnd.lsf.aggregate-v1';
function host<T, E>(result: Result<T, E>): T {
  if (result.tag === 'err') throw new Error('transaction host failure: ' + String(result.val));
  return result.val;
}
function count(value?: VersionedValue): bigint {
  if (value === undefined) return 0n;
  if (value.value.mediaType !== media || value.value.metadata.length !== 0 || value.value.bytes.length !== 8)
    throw 'malformed-state' satisfies Contract.BusinessError;
  const bytes = value.value.bytes;
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getBigUint64(0, true);
}
export const api: typeof Contract = {
  update(request) {
    const command = host(Command.acquire());
    try {
      const stored = host(command.get(key));
      const next = count(stored) + BigInt(request.delta);
      if (next > (1n << 64n) - 1n) throw 'overflow' satisfies Contract.BusinessError;
      const viewVersion = host(command.info()).view.version;
      const keyVersion = stored?.version;
      const bytes = new Uint8Array(8); new DataView(bytes.buffer).setBigUint64(0, next, true);
      const payload = { bytes, mediaType: media, metadata: [] as [string, string][] };
      host(command.put(key, payload));
      host(new Intent('approved-event', 'event', payload).stage(command));
      if (request.reject) throw 'rejected' satisfies Contract.BusinessError;
      return { count: next, viewVersion, keyVersion };
    } finally { command.close(); }
  },
  query() {
    const query = host(Query.acquire());
    try {
      const stored = host(query.get(key));
      return { count: count(stored), viewVersion: host(query.info()).version, keyVersion: stored?.version };
    }
    finally { query.close(); }
  },
  scan(prefix, limit, cursor) {
    const query = host(Query.acquire());
    try {
      const page = host(query.scan(prefix, limit, cursor));
      try {
        const info = host(page.info()); let count = 0;
        while (host(page.next()) !== undefined) count++;
        if (count !== info.entryCount) throw new Error('page count mismatch');
        return { count, encodedBytes: info.encodedBytes, viewVersion: info.view.version, nextCursor: info.nextCursor };
      } finally { page.close(); }
    } finally { query.close(); }
  },
};
// lsf-example-end: capsule
