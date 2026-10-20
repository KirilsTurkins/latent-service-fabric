import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';

let calls = 0;
export const api: typeof Contract = {
  async run(mode, url) {
    if (++calls !== 1) throw new Error('fetch-late-stale-module');
    if (mode === 0) return 'ready|fresh=1';
    if (mode !== 1) throw new TypeError('fetch-late-unknown-mode');
    const controller = new AbortController();
    const reason = Object.freeze({kind: 'ordinary-late-abort'});
    const started = performance.now();
    let resolved = 0;
    let rejected = 0;
    const pending = fetch(url, {signal: controller.signal});
    pending.then(() => { ++resolved; }, () => { ++rejected; });
    const timer = setTimeout(() => controller.abort(reason), 1000);
    let aborted = false;
    try { await pending; }
    catch (error) {
      if (error !== reason || performance.now() - started < 1000) throw error;
      aborted = true;
    } finally { clearTimeout(timer); }
    if (!aborted) throw new Error('fetch-late-abort-ignored');
    await new Promise<void>(resolve => { setTimeout(() => resolve(), 3000); });
    if (performance.now() - started < 4000 || resolved !== 0 || rejected !== 1)
      throw new Error('fetch-late-result-or-clock');
    return 'late:aborted:one-rejection:zero-resolution|fresh=1';
  },
};
