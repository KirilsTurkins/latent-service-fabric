import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';

let calls = 0;
const reason = 'explicit-fetch-abort';

async function caught(operation: () => Promise<unknown>, expected: string): Promise<string> {
  try { await operation(); }
  catch (error) {
    if (error instanceof Error && error.message === expected) return expected;
    throw error;
  }
  throw new Error('fetch-conformance-expected-refusal');
}

export const api: typeof Contract = {
  async run(mode, url) {
    if (++calls !== 1) throw new Error('fetch-conformance-stale-module');
    if (mode === 0) {
      const response = await fetch(new Request(url));
      const copy = response.clone();
      const value = await response.json();
      if (!response.bodyUsed || copy.bodyUsed) throw new Error('fetch-conformance-body-state');
      let refused = false;
      try { await response.text(); } catch (error) { refused = error instanceof TypeError; }
      if (!refused || await copy.text() !== JSON.stringify(value)) throw new Error('fetch-conformance-clone');
      return `${response.status}:${JSON.stringify(value)}:used:clone`;
    }
    if (mode >= 10 && mode <= 16) {
      const method = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'][mode - 10];
      const response = await fetch(url, {method, headers: {'x-conformance': 'ordinary-global'},
        ...(method === 'GET' || method === 'HEAD' ? {} : {body: 'caf\u00e9\u03bb'})});
      return `${response.status}:${await response.text()}`;
    }
    if (mode === 20) {
      const controller = new AbortController();
      controller.abort(reason);
      try { await fetch(url, {signal: controller.signal}); }
      catch (error) { if (error === reason) return 'already-aborted'; throw error; }
      throw new Error('fetch-conformance-abort-ignored');
    }
    if (mode === 21) {
      return caught(() => fetch(url, {headers: {authorization: 'guest-forbidden'}}),
        'lsf-fetch-buffered-v1:unsupported:reserved-header:authorization');
    }
    if (mode === 22) {
      const request = new Request(url, {method: 'POST', body: 'once'});
      const response = await fetch(request);
      if (!request.bodyUsed || response.status !== 200) throw new Error('fetch-conformance-request-used');
      return caught(() => fetch(request), 'body-already-used');
    }
    if (mode === 23) {
      const response = await fetch(url);
      const stream = response.body;
      if (stream === null || stream.locked || response.bodyUsed) throw new Error('fetch-conformance-reader-start');
      const reader = stream.getReader();
      if (!stream.locked || response.bodyUsed) throw new Error('fetch-conformance-reader-lock');
      const chunks: Uint8Array[] = [];
      for (;;) {
        const part = await reader.read();
        if (part.done) break;
        if (part.value.length > 65536) throw new Error('fetch-conformance-reader-window');
        chunks.push(part.value);
      }
      if (!response.bodyUsed || !stream.locked) throw new Error('fetch-conformance-reader-disturbance');
      reader.releaseLock();
      if (stream.locked) throw new Error('fetch-conformance-reader-release');
      const length = chunks.reduce((sum, item) => sum + item.length, 0);
      const bytes = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      return await new Response(bytes).text();
    }
    if (mode === 24) {
      const response = await fetch(url);
      const stream = response.body;
      if (stream === null) throw new Error('fetch-conformance-cancel-null');
      const reader = stream.getReader();
      await reader.cancel();
      if (!response.bodyUsed || !stream.locked) throw new Error('fetch-conformance-cancel-state');
      reader.releaseLock();
      return caught(() => response.json(), 'body-already-used');
    }
    if (mode === 25) {
      try { new Request(url, {method: 'GET', body: 'forbidden'}); }
      catch (error) { if (error instanceof TypeError) return 'get-body-refused'; throw error; }
      throw new Error('fetch-conformance-get-body-accepted');
    }
    if (mode === 26) {
      const response = await fetch(url);
      try { await response.json(); }
      catch (error) { if (error instanceof SyntaxError) return 'malformed-json'; throw error; }
      throw new Error('fetch-conformance-malformed-json-accepted');
    }
    if (mode === 27) {
      try { await fetch(url); }
      catch (error) {
        if (error instanceof TypeError && error.message.startsWith('fetch-transport-failure:'))
          return error.message;
        throw error;
      }
      throw new Error('fetch-conformance-transport-succeeded');
    }
    if (mode === 28) {
      const response = await fetch(url);
      return `${response.status}:${response.redirected}:${await response.text()}`;
    }
    if (mode === 30 || mode === 31) {
      const controller = new AbortController();
      const timer = mode === 30 ? setTimeout(() => controller.abort(reason), 25) : undefined;
      const signal = mode === 30 ? controller.signal : AbortSignal.timeout(25);
      try { await fetch(url, {signal}); }
      catch (error) {
        if (mode === 30 && error === reason) return 'explicit-abort';
        if (mode === 31 && error instanceof Error && error.name === 'TimeoutError') return 'operation-timeout';
        throw error;
      } finally { if (timer !== undefined) clearTimeout(timer); }
      throw new Error('fetch-conformance-pending-abort-ignored');
    }
    if (mode === 32) {
      fetch(url).catch(() => {});
      return 'accepted-fetch-root-return';
    }
    if (mode === 33) {
      try { await fetch(url, {method: 'POST', body: 'commit-once'}); }
      catch (error) {
        if (error instanceof TypeError && error.message === 'fetch-transport-failure:uncertain' &&
            (error as TypeError & {uncertain?: boolean}).uncertain === true) return 'uncertain:true';
        throw error;
      }
      throw new Error('fetch-conformance-uncertain-mutation-succeeded');
    }
    if (mode === 34) return `${(await fetch(url)).status}`;
    throw new TypeError('fetch-conformance-unknown-mode');
  },
};
