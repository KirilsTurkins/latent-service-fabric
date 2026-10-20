import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';
import {request, initialized} from './default-client.js';
import ky from 'ky';

if (!initialized) throw new Error('phase-fetch-default-globals-unavailable');
let calls = 0;
export const api: typeof Contract = {
  async run(mode, url) {
    if (++calls !== 1) throw new Error('phase-fetch-state-reused');
    if (mode === 13 || mode === 14) {
      let forwarded = 0;
      const extension: typeof fetch = (input, init) => {
        forwarded++;
        return globalThis.fetch(input, init);
      };
      try {
        const value = await ky.get(url, {fetch: extension, retry: 0, timeout: false}).json();
        if (mode === 14 || forwarded !== 1) throw new Error('phase-fetch-extension-authority');
        return `extension:1:${JSON.stringify(value)}|fresh=1`;
      } catch (error) {
        if (mode !== 14 || forwarded !== 1 || !(error instanceof TypeError)
            || error.message !== 'fetch-transport-failure:permission-denied') throw error;
        return 'extension:denied:no-contact|fresh=1';
      }
    }
    if (mode === 7 || mode === 8) {
      const response = await fetch(url), clone = response.clone();
      const expected = mode === 7 ? '' : ' Caf\u00ff ';
      if (response.statusText !== expected || clone.statusText !== expected)
        throw new Error('phase-fetch-wire-reason-lost');
      if (await response.text() !== await clone.text())
        throw new Error('phase-fetch-clone-body-differs');
      return `wire:${response.status}:${JSON.stringify(expected)}|fresh=1`;
    }
    if (mode === 9) {
      const controller = new AbortController(), reason = {kind: 'phase-fetch-public-abort'};
      const timer = setTimeout(() => controller.abort(reason), 1000);
      try {
        await fetch(url, {signal: controller.signal});
        throw new Error('phase-fetch-abort-resolved');
      } catch (error) {
        if (error !== reason) throw error;
        await new Promise<void>(resolve => setTimeout(resolve, 3000));
        return 'abort:exact-reason|fresh=1';
      } finally { clearTimeout(timer); }
    }
    if (mode === 10) {
      await fetch(url);
      throw new Error('phase-fetch-held-root-resolved');
    }
    if (mode === 11) {
      try {
        await fetch(url, {method: 'POST', body: 'one'});
        throw new Error('phase-fetch-uncertain-post-resolved');
      } catch (error) {
        if (!(error instanceof Error) || (error as Error & {uncertain?: boolean}).uncertain !== true)
          throw error;
        return 'uncertain:true|fresh=1';
      }
    }
    if (mode === 12) {
      try {
        await fetch(url);
        throw new Error('phase-fetch-denied-target-resolved');
      } catch (error) {
        if (!(error instanceof TypeError) || error.message !== 'fetch-transport-failure:permission-denied')
          throw error;
        return 'denied:no-contact|fresh=1';
      }
    }
    return `1|${await request(mode, url)}`;
  },
};
