import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';
declare const performance: {now(): number};

let calls = 0;
const wait = (milliseconds: number) => new Promise<void>(resolve => setTimeout(resolve, milliseconds));
export const api: typeof Contract = {
  async run(mode, _url) {
    if (++calls !== 1) throw new Error('timer-races-stale-module');
    if (mode === 0) return 'ready|fresh=1';
    if (mode === 1) {
      const signal = AbortSignal.timeout(2);
      if (signal.aborted) throw new Error('timeout-aborted-synchronously');
      let count = 0;
      await new Promise<void>(resolve => signal.addEventListener('abort', () => { ++count; resolve(); }));
      if (!signal.aborted || signal.reason.name !== 'TimeoutError') throw new Error('timeout-reason');
      let caught = false;
      try { signal.throwIfAborted(); } catch (reason) { caught = reason === signal.reason; }
      await wait(10);
      if (!caught || count !== 1) throw new Error('timeout-repeated-or-reason-changed');
      return 'timeout:once:exact-reason|fresh=1';
    }
    if (mode === 2) {
      const controller = new AbortController();
      const timeout = AbortSignal.timeout(10);
      const signal = AbortSignal.any(new Set([controller.signal, timeout]));
      const reason = Object.freeze({kind:'explicit-first'});
      let count = 0;
      signal.addEventListener('abort', () => { ++count; });
      controller.abort(reason); controller.abort('ignored-second');
      await wait(30);
      if (!timeout.aborted || signal.reason !== reason || count !== 1) throw new Error('abort-any-late-timeout');
      return 'any:manual-first:late-timeout-fenced|fresh=1';
    }
    if (mode === 3) {
      const first = Object.freeze({kind:'already-aborted'});
      const controller = new AbortController();
      const signal = AbortSignal.any([AbortSignal.abort(first), controller.signal]);
      let late = 0;
      signal.addEventListener('abort', () => { ++late; });
      controller.abort('later');
      await wait(2);
      if (!signal.aborted || signal.reason !== first || late !== 0) throw new Error('already-aborted-replayed');
      return 'any:already-aborted:no-replay|fresh=1';
    }
    if (mode === 4) {
      let fired = 0;
      const timeout = setTimeout(() => { ++fired; }, 0);
      const interval = setInterval(() => { ++fired; }, 0);
      clearInterval(timeout); clearTimeout(interval);
      clearInterval(timeout); clearTimeout(interval); clearTimeout(-1); clearInterval();
      await wait(10);
      if (fired !== 0) throw new Error('cross-cleared-timer-fired');
      return 'clear:shared-ids:idempotent|fresh=1';
    }
    if (mode === 5) {
      const order: string[] = [];
      let sibling = 0;
      setTimeout(() => {
        order.push('first');
        Promise.resolve().then(() => { clearTimeout(sibling); order.push('microtask-clear'); });
      }, 0);
      sibling = setTimeout(() => { order.push('forbidden-sibling'); }, 0);
      await wait(15);
      if (order.join(',') !== 'first,microtask-clear') throw new Error('cleared-ready-callback-replayed');
      return 'clear:ready-sibling:microtask-fence|fresh=1';
    }
    if (mode === 6) {
      for (const value of [NaN, Infinity, -1, 2 ** 64, 18446744073710]) {
        let refused = false;
        try { AbortSignal.timeout(value); } catch (error) { refused = error instanceof TypeError; }
        if (!refused) throw new Error('invalid-timeout-was-admitted');
      }
      let closed = false, refused = false;
      const iterable = (function* () {
        try { yield new AbortController().signal; yield {} as AbortSignal; }
        finally { closed = true; }
      })();
      try { AbortSignal.any(iterable); } catch (error) { refused = error instanceof TypeError; }
      if (!closed || !refused) throw new Error('any-invalid-iterator-not-closed');
      const valid = AbortSignal.timeout(1);
      await new Promise<void>(resolve => valid.addEventListener('abort', () => resolve(), {once:true}));
      if (!valid.aborted) throw new Error('valid-after-refused-timeout');
      return 'timeout:checked-conversion:valid-after-refusal|fresh=1';
    }
    if (mode === 7) {
      let ticks = 0, active = false, blocked = false, checksum = 0;
      await new Promise<void>(resolve => {
        const interval = setInterval(() => {
          if (active) throw new Error('interval-reentered-synchronous-callback');
          active = true;
          if (++ticks === 1) {
            const start = performance.now();
            let polls = 0;
            do {
              for (let i = 0; i < 2000; ++i) checksum = (checksum + i) | 0;
              if (++polls > 512) throw new Error('bounded-clock-progress-not-observed');
            } while (performance.now() - start < 25);
            blocked = true;
          }
          if (ticks === 3) { clearInterval(interval); resolve(); }
          active = false;
        }, 1);
      });
      await wait(10);
      if (ticks !== 3 || active || !blocked || !Number.isInteger(checksum)) throw new Error('interval-coalescing');
      return 'interval:blocked-turn:bounded-coalescing|fresh=1';
    }
    if (mode === 8) {
      await wait(10000);
      return 'forbidden-timer-elapsed-after-root-deadline';
    }
    throw new TypeError('timer-races-unknown-mode');
  },
};
