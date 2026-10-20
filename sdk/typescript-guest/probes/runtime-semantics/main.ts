import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';

let calls = 0;
const wait = (milliseconds: number) => new Promise<void>(resolve => setTimeout(resolve, milliseconds));
export const api: typeof Contract = {
  async run(mode, _url) {
    if (++calls !== 1) throw new Error('runtime-semantics-stale-module');
    if (mode === 0) return 'ready|fresh=1';
    if (mode === 1) {
      let entered = 0;
      const value = await {then(resolve: (value: string) => void, reject: (reason: unknown) => void) {
        ++entered;
        setTimeout(() => { resolve('thenable'); reject(new Error('ignored-second-settlement')); }, 1);
      }};
      if (value !== 'thenable' || entered !== 1) throw new Error('thenable-assimilation');
      return 'thenable:pending:once|fresh=1';
    }
    if (mode === 2) {
      const order = ['sync-start'];
      Promise.resolve().then(() => {
        order.push('micro-a');
        Promise.resolve().then(() => order.push('micro-b'));
      });
      for (let i = 0; i < 10000; ++i) {
        if (order.length !== 1) throw new Error('synchronous-turn-preempted');
      }
      order.push('sync-end');
      await new Promise<void>(resolve => setTimeout(() => { order.push('timer'); resolve(); }, 10));
      if (order.join(',') !== 'sync-start,sync-end,micro-a,micro-b,timer')
        throw new Error('microtask-order');
      return 'microtasks:nested:run-to-completion|fresh=1';
    }
    if (mode === 3) {
      const reason = Object.freeze({kind: 'ordinary-private-reason'});
      let caught = false;
      try { await new Promise<void>((_resolve, reject) => setTimeout(() => reject(reason), 1)); }
      catch (error) { if (error !== reason) throw new Error('rejection-identity'); caught = true; }
      if (!caught) throw new Error('rejection-disappeared');
      return 'rejection:pending:exact-object|fresh=1';
    }
    if (mode === 4) {
      const reason = Object.freeze({kind: 'finally-reason'});
      const order: string[] = [];
      try { await Promise.reject(reason).finally(() => { order.push('finally'); }); }
      catch (error) { if (error !== reason) throw new Error('finally-rejection-identity'); order.push('caught'); }
      const value = await Promise.resolve(42).finally(() => { order.push('fulfilled'); });
      if (value !== 42 || order.join(',') !== 'finally,caught,fulfilled') throw new Error('finally-order');
      return 'finally:values:reason:order|fresh=1';
    }
    if (mode === 5) {
      let ticks = 0, active = false;
      await new Promise<void>(resolve => {
        const id = setInterval(() => {
          if (active) throw new Error('interval-overlap');
          active = true;
          if (++ticks === 3) { clearInterval(id); resolve(); }
          active = false;
        }, 1);
      });
      await wait(20);
      if (ticks !== 3 || active) throw new Error('cleared-interval-fired');
      return 'interval:three:clear:no-overlap|fresh=1';
    }
    if (mode === 6) {
      const order: string[] = [];
      await new Promise<void>(resolve => {
        setTimeout((value: {n: number}, increment: number) => {
          if (value.n + increment !== 42) throw new Error('timer-arguments');
          order.push('outer');
          Promise.resolve().then(() => order.push('micro'));
          setTimeout(() => { order.push('inner'); resolve(); }, 0);
        }, 0, {n: 40}, 2);
      });
      if (order.join(',') !== 'outer,micro,inner') throw new Error('timer-microtask-checkpoint');
      return 'timer:arguments:nesting:microtask|fresh=1';
    }
    if (mode === 7) {
      let fired = false;
      const cleared = setTimeout(() => { fired = true; }, 0);
      clearTimeout(cleared); clearTimeout(cleared); clearTimeout();
      await wait(10);
      if (fired) throw new Error('cancelled-timer-fired');
      return 'timer:clear-before-fire:idempotent|fresh=1';
    }
    if (mode === 8) {
      return await new Promise<string>(() => setTimeout(() => {
        throw new Error('runtime-semantics-callback-exception');
      }, 1));
    }
    if (mode === 9) {
      Promise.reject(new Error('runtime-semantics-unhandled-rejection'));
      await wait(1);
      return 'unhandled-rejection-must-refuse';
    }
    if (mode === 10) {
      for (;;) { /* Original host fuel must contain a synchronous turn. */ }
    }
    throw new TypeError('runtime-semantics-unknown-mode');
  },
};
