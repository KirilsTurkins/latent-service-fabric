import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';
import {request, initialized} from './default-client.js';

// Only pure constructors are snapshotted; native signal owners stay invocation-local.
const headers = new Headers([['x-direct', 'present']]);
if (new Response(null, {headers}).headers.get('x-direct') !== 'present' || !initialized) {
  throw new Error('fetch-runtime-direct-initialization');
}
let calls = 0;

export const api: typeof Contract = {
  async run(mode, url) {
    if (mode === 1) return 'entered';
    if (mode !== 0) throw new TypeError('unsupported-fetch-runtime-mode');
    return `${++calls}:${await request(url)}`;
  },
};
