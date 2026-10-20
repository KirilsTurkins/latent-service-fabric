import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';

let calls = 0;
let retained: unknown;
export const api: typeof Contract = {
  async run(mode, _url) {
    if (++calls !== 1) throw new Error('root-lifecycle-stale-module');
    if (mode === 0) return 'ready|fresh=1';
    if (mode === 1) {
      setTimeout(() => console.info('accepted-after-root'), 100);
      return 'accepted-timer|fresh=1';
    }
    if (mode === 2) {
      Promise.resolve().then(() => console.info('microtask-after-root'));
      return 'accepted-microtask|fresh=1';
    }
    if (mode === 3) {
      setTimeout(() => {
        console.info('accepted-parent');
        setTimeout(() => console.info('accepted-child'), 1);
      }, 100);
      return 'accepted-chain|fresh=1';
    }
    if (mode === 4) {
      new Promise<void>(() => {});
      return 'unreachable-promise|fresh=1';
    }
    if (mode === 5) {
      retained = new Promise<void>(() => {});
      if (!retained) throw new Error('opaque-work-not-created');
      return 'opaque-work-must-refuse';
    }
    if (mode === 6 || mode === 10) {
      setTimeout(() => {
        console.info('callback-throw-reached');
        if (mode === 6) throw new Error('root-lifecycle-callback-throw');
      }, 100);
      return mode === 6 ? 'callback-throw-must-refuse' : 'callback-control|fresh=1';
    }
    if (mode === 7 || mode === 11) {
      setTimeout(() => {
        console.info('rejection-reached');
        if (mode === 7) Promise.reject(new Error('root-lifecycle-unhandled-rejection'));
        else Promise.resolve();
      }, 100);
      return mode === 7 ? 'unhandled-rejection-must-refuse' : 'rejection-control|fresh=1';
    }
    if (mode === 8) {
      setInterval(() => {}, 100);
      return 'live-interval-must-not-be-discarded';
    }
    if (mode === 9) {
      await new Promise<void>(resolve => setTimeout(resolve, 1));
      console.info('root-rejection-reached');
      throw new Error('root-lifecycle-root-rejection');
    }
    throw new TypeError('root-lifecycle-unknown-mode');
  },
};
