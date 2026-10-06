// lsf-example-begin: order-draft
import type * as Contract from '../generated/interfaces/examples-order-draft-api.js';
import {Command, Query, type VersionedValue} from '../vendor/lsf/sdk/typescript-guest/capabilities/state.js';
import {Intent} from '../vendor/lsf/sdk/typescript-guest/capabilities/intents.js';
import type {Result} from '../vendor/lsf/sdk/typescript-guest/capabilities/result.js';

const media = 'application/vnd.lsf.order-draft-v1';
const encoder = new TextEncoder();
function host<T, E>(result: Result<T, E>): T {
  if (result.tag === 'err') throw new Error('transaction host failure: ' + String(result.val));
  return result.val;
}
function keys(id: string): [Uint8Array, Uint8Array] {
  if (!/^[a-z0-9][a-z0-9-]{0,31}$/.test(id)) throw 'invalid-draft' satisfies Contract.BusinessError;
  return [encoder.encode('drafts/' + id + '/draft'), encoder.encode('drafts/' + id + '/summary')];
}
function decode(primary?: VersionedValue, summary?: VersionedValue): {revision: bigint; units: number} {
  if (primary === undefined && summary === undefined) return {revision: 0n, units: 0};
  if (primary === undefined || summary === undefined) throw 'malformed-state' satisfies Contract.BusinessError;
  for (const value of [primary.value, summary.value]) {
    if (value.mediaType !== media || value.metadata.length !== 0 || value.bytes.length !== 12)
      throw 'malformed-state' satisfies Contract.BusinessError;
  }
  if (!primary.value.bytes.every((byte, index) => byte === summary.value.bytes[index]))
    throw 'malformed-state' satisfies Contract.BusinessError;
  const bytes = primary.value.bytes;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const result = {revision: view.getBigUint64(0, true), units: view.getUint32(8, true)};
  if (result.revision === 0n || result.units > 10000) throw 'malformed-state' satisfies Contract.BusinessError;
  return result;
}

export const api: typeof Contract = {
  edit(request) {
    const [primaryKey, summaryKey] = keys(request.draftId);
    if (!Number.isInteger(request.units) || request.units < 0 || request.units > 10000)
      throw 'invalid-units' satisfies Contract.BusinessError;
    const command = host(Command.acquire());
    try {
      if (host(command.info()).view.namespace !== 'order-drafts-' + request.draftId)
        throw 'invalid-draft' satisfies Contract.BusinessError;
      const original = host(command.get(primaryKey));
      const old = decode(original, host(command.get(summaryKey)));
      if (old.revision !== request.expectedRevision) throw 'stale-edit' satisfies Contract.BusinessError;
      if (old.revision === (1n << 64n) - 1n) throw 'revision-overflow' satisfies Contract.BusinessError;
      const revision = old.revision + 1n;
      const bytes = new Uint8Array(12);
      const view = new DataView(bytes.buffer);
      view.setBigUint64(0, revision, true); view.setUint32(8, request.units, true);
      const value = {bytes, mediaType: media, metadata: [] as [string, string][]};
      host(command.put(primaryKey, value));
      host(command.put(summaryKey, value));
      const identity = encoder.encode(request.draftId);
      const event = new Uint8Array(identity.length + 1 + bytes.length);
      event.set(identity); event.set(bytes, identity.length + 1);
      const payload = {bytes: event, mediaType: media, metadata: [] as [string, string][]};
      host(new Intent('draft-change', 'event', payload).stage(command));
      host(new Intent('draft-http', 'put-once', payload).stage(command));
      if (request.reject) throw 'rejected' satisfies Contract.BusinessError;
      return {draftId: request.draftId, revision, units: request.units,
        namespaceView: host(command.info()).view.version, keyVersion: original?.version};
    } finally { command.close(); }
  },
  query(id) {
    const [primaryKey, summaryKey] = keys(id);
    const query = host(Query.acquire());
    try {
      if (host(query.info()).namespace !== 'order-drafts-' + id)
        throw 'invalid-draft' satisfies Contract.BusinessError;
      const primary = host(query.get(primaryKey));
      const value = decode(primary, host(query.get(summaryKey)));
      return {draftId: id, ...value, namespaceView: host(query.info()).version, keyVersion: primary?.version};
    } finally { query.close(); }
  },
};
// lsf-example-end: order-draft
