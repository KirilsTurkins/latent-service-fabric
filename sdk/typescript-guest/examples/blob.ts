import type * as Contract from '../generated/interfaces/tests-local-blobs-api.js';
import * as raw from 'latent:blob/blob@0.2.0';
import * as blob from '../vendor/lsf/sdk/typescript-guest/capabilities/blob.js';
import { Scope } from '../vendor/lsf/sdk/typescript-guest/capabilities/owner.js';
import { call, unwrap } from '../vendor/lsf/sdk/typescript-guest/capabilities/result.js';
export const api: typeof Contract = {
  run(which, _text, previous) {
    const scope = new Scope();
    try {
      // Raw calls here deliberately probe stale primitive handles, not SDK
      // owner construction or an authority path available only to this test.
      if (which === 4) {
        const result = call<bigint, raw.BlobError>(() => raw.write(previous, 0n, new Uint8Array()),
          ['invalid-state', 'permission-denied']);
        if (result.tag !== 'err') throw new Error('foreign-handle-accepted');
        return result.val.tag === 'permission-denied' ? 11n : 10n;
      }
      const created = blob.create('text/plain', which === 2 || which === 5 ? 0n : 4n);
      if (created.tag === 'err' && created.val.tag === 'permission-denied') return 11n;
      const writer = unwrap(created);
      if (which === 1) return 1n; // Deliberate abandonment: host activation cleanup owns it.
      if (which === 5) return writer.consume(handle => handle); // Deliberately leak a raw stale identity.
      scope.own(writer);
      if (which === 2) {
        const handle = writer.borrow(value => value);
        unwrap(blob.close(writer));
        const result = call<bigint, raw.BlobError>(() => raw.write(handle, 0n, new Uint8Array()), ['invalid-state']);
        if (result.tag !== 'err') throw new Error('closed-handle-accepted');
        return 10n;
      }
      if (unwrap(blob.write(writer, 0n, new Uint8Array([100, 97, 116, 97]))) !== 4n) throw new Error('short-write');
      const reader = scope.own(unwrap(blob.open(unwrap(blob.seal(writer)))));
      const chunk = scope.own(unwrap(blob.read(reader, 0n, 4)));
      unwrap(blob.close(reader));
      if (which === 3) return 3n;
      const data = unwrap(blob.chunkBytes(chunk));
      if (data.length !== 4 || data.some((byte, i) => byte !== [100, 97, 116, 97][i])) throw new Error('blob-data-mismatch');
      if (which === 6) {
        const repeated = blob.chunkBytes(chunk);
        if (repeated.tag !== 'err' || repeated.val.tag !== 'invalid-state') throw new Error('chunk-rematerialized');
        return 10n;
      }
      return 4n;
    } finally { scope.close(); }
  },
};
