import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';

let calls = 0;
export const api: typeof Contract = {
  async run(mode, _url) {
    if (++calls !== 1) throw new Error('buffered-body-stale-module');
    if (mode === 0) {
      const input = new Uint8Array(131073).fill(85);
      const response = new Response(input);
      input.fill(0);
      const stream = response.body;
      if (stream === null) throw new Error('buffered-body-missing');
      await Promise.resolve();
      if (response.bodyUsed || stream.locked) throw new Error('buffered-body-prefetched');
      const reader = stream.getReader();
      await Promise.resolve();
      if (response.bodyUsed || !stream.locked) throw new Error('buffered-body-lock-prefetched');
      for (const length of [65536, 65536, 1]) {
        const part = await reader.read();
        if (part.done || part.value.length !== length || part.value.some(value => value !== 85))
          throw new Error('buffered-body-window-or-copy');
      }
      if (!(await reader.read()).done || !response.bodyUsed) throw new Error('buffered-body-not-complete');
      reader.releaseLock();
      if (stream.locked) throw new Error('buffered-body-release');
      return 'windows:65536,65536,1:copied:no-prefetch';
    }
    if (mode === 1) {
      const response = new Response(new Uint8Array(131073).fill(7));
      const stream = response.body;
      if (stream === null) throw new Error('buffered-body-missing');
      const reader = stream.getReader();
      const first = await reader.read();
      if (first.done || first.value.length !== 65536) throw new Error('buffered-body-first-window');
      await reader.cancel('abandon-buffered-remainder');
      if (!(await reader.read()).done || !response.bodyUsed) throw new Error('buffered-body-cancel-not-terminal');
      reader.releaseLock();
      try { await response.arrayBuffer(); }
      catch (error) {
        if (error instanceof TypeError && error.message === 'body-already-used') return 'cancelled:one-window:remainder-unread';
        throw error;
      }
      throw new Error('buffered-body-cancel-reconsumed');
    }
    if (mode === 2) {
      for (const [member, expected] of [['tee','Body.tee'],['pipeTo','Body.pipeTo'],
          ['pipeThrough','Body.pipeThrough'],['values','Body.values']] as const) {
        const body = new Response('unread').body;
        if (body === null) throw new Error('buffered-body-missing');
        let refused = false;
        try { Reflect.apply(Reflect.get(body, member), body, []); }
        catch (error) { refused = error instanceof TypeError &&
            error.message === 'lsf-fetch-buffered-v1:unsupported:' + expected; }
        if (!refused || body.locked) throw new Error('buffered-body-unsupported-operation');
      }
      return 'tee:pipeTo:pipeThrough:values:unsupported';
    }
    if (mode === 3) {
      try { new Response(new Uint8Array(1048577)); }
      catch (error) {
        if (error instanceof RangeError && error.message === 'fetch-body-limit') return 'body-limit:1048576';
        throw error;
      }
      throw new Error('buffered-body-limit-ignored');
    }
    if (mode === 4) {
      const absent = new Response(null);
      if (absent.body !== null || absent.bodyUsed || (await absent.arrayBuffer()).byteLength !== 0 || absent.bodyUsed)
        throw new Error('buffered-body-null-state');
      const empty = new Response(new Uint8Array(0));
      const stream = empty.body;
      if (stream === null || empty.bodyUsed) throw new Error('buffered-body-empty-state');
      const reader = stream.getReader();
      if (!(await reader.read()).done || !empty.bodyUsed) throw new Error('buffered-body-empty-disturbance');
      reader.releaseLock();
      return 'null:absent:empty:disturbed';
    }
    if (mode === 5) {
      const order: string[] = [];
      const values = {'x-observed': 'before'};
      const response = new Response(null, {
        get headers() { order.push('headers'); return values; },
        get status() { order.push('status'); values['x-observed'] = 'after'; return 201.9; },
        get statusText() { order.push('statusText'); return 'Created'; },
      });
      if (order.join(',') !== 'headers,status,statusText' || response.status !== 201 ||
          response.statusText !== 'Created' || response.headers.get('x-observed') !== 'before')
        throw new Error('response-init-order-or-snapshot');
      const jsonOrder: string[] = [];
      const json = Response.json({toJSON() { jsonOrder.push('json'); return {ok: true}; }}, {
        get headers() { jsonOrder.push('headers'); return {'x-json': 'present'}; },
        get status() { jsonOrder.push('status'); return 202; },
      });
      if (jsonOrder.join(',') !== 'headers,status,json' || json.status !== 202 ||
          json.headers.get('x-json') !== 'present' || json.headers.get('content-type') !== 'application/json' ||
          await json.text() !== '{"ok":true}') throw new Error('response-json-init-order');
      return 'response-init:ordered:snapshotted:json';
    }
    if (mode === 6) {
      let statusRead = false, convertedFirst = false;
      try { new Response(null, {headers: [['x', '\u0100']], get status() { statusRead = true; return 200; }}); }
      catch (error) { convertedFirst = error instanceof TypeError; }
      if (!convertedFirst || statusRead) throw new Error('response-header-conversion-order');
      const order: string[] = [];
      let statusFirst = false;
      try {
        new Response(null, {get headers() { order.push('headers'); return [['bad\nname', 'v']]; },
          get status() { order.push('status'); return 0; },
          get statusText() { order.push('statusText'); return ''; }});
      } catch (error) { statusFirst = error instanceof RangeError; }
      if (!statusFirst || order.join(',') !== 'headers,status,statusText')
        throw new Error('response-init-validation-precedence');
      return 'response-init:conversion:validation';
    }
    throw new TypeError('buffered-body-unknown-mode');
  },
};
