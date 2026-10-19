import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';
import {request} from './default-client.js';

// Component snapshot initialization must see the compiler-installed globals.
const headers = new Headers([['x-direct', 'present']]);
const response = new Response(null, {headers});
if (response.status !== 200 || response.headers.get('x-direct') !== 'present' ||
    response.body !== null || response.bodyUsed || Response.error().status !== 0 ||
    Response.redirect('https://fixture.invalid/next#kept').headers.get('location') !==
      'https://fixture.invalid/next#kept') {
  throw new Error('default-fetch-direct-initialization');
}

export const api: typeof Contract = {
  async run(url) {
    return request(url);
  },
};
