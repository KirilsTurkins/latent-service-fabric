import type * as Contract from '../generated/interfaces/tests-streaming-http-api.js';
import * as http from '../vendor/lsf/sdk/typescript-guest/capabilities/streaming.js';
import { Scope } from '../vendor/lsf/sdk/typescript-guest/capabilities/owner.js';
import { unwrap } from '../vendor/lsf/sdk/typescript-guest/capabilities/result.js';
export const api: typeof Contract = {
  run(which, url) {
    const scope = new Scope();
    try {
      const result = http.open({ method: 'post', url, headers: [], bodyLength: 4n,
        bodyMediaType: 'text/plain', timeoutMillis: 1000n });
      if (result.tag === 'err' && result.val.tag === 'permission-denied') return 10n;
      const upload = scope.own(unwrap(result));
      if (which === 1) return 1n;
      unwrap(http.write(upload, new Uint8Array([100, 97, 116, 97])));
      const response = unwrap(http.finish(upload));
      const body = scope.own(response.body);
      if (which === 2) return 2n;
      let count = 0n;
      while (true) {
        const chunk = unwrap(http.read(body, 4));
        if (chunk === undefined) break;
        // Chunk ownership is independent of the body and retains its charge.
        try {
          if (which === 3) body.close();
          count += BigInt(unwrap(http.chunkBytes(chunk)).length);
          if (which === 3) return count;
        } finally { chunk.close(); }
      }
      unwrap(http.trailers(body));
      const repeated = http.trailers(body);
      if (repeated.tag !== 'err' || repeated.val.tag !== 'invalid-state') throw new Error('trailers-reused');
      return count;
    } finally { scope.close(); }
  },
};
