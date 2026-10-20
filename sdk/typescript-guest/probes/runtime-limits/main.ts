import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';

let calls = 0;
export const api: typeof Contract = {
  async run(mode, _url) {
    if (++calls !== 1) throw new Error('runtime-limit-stale-module');
    if (mode === 0) return 'ready|fresh=1';
    if (mode === 4) {
      const timers: number[] = [];
      try {
        for (let i = 0; i < 16; ++i)
          timers.push(setTimeout(() => { throw new Error('runtime-limit-long-timer-fired'); }, 3600000));
      } catch (error) {
        if (!(error instanceof Error) || error.message !== 'activation-runtime-timer-start-denied:2') throw error;
        if (timers.length !== 8) throw new Error('runtime-limit-wrong-timer-boundary');
        return error.message + '|count=8|fresh=1';
      } finally {
        for (const timer of timers) clearTimeout(timer);
      }
      throw new Error('runtime-limit-timer-not-enforced');
    }
    if (mode === 5) {
      const held: Uint8Array[] = [];
      for (let i = 0; i < 24; ++i) held.push(new Uint8Array(4194304).fill(i + 1));
      let checksum = 0;
      for (const block of held) checksum += block[0] + block[block.length - 1];
      return 'memory-limit-not-enforced:' + checksum;
    }
    const labels: Record<number, string> = {
      1: 'activation-runtime-task-register-denied:2',
      2: 'activation-runtime-queue-register-denied:2',
      3: 'activation-runtime-promise-native-register-denied:2',
    };
    const label = labels[mode];
    if (label === undefined) throw new TypeError('runtime-limit-unknown-mode');
    const held: Promise<unknown>[] = [];
    const pending = new Promise<void>(() => {});
    let admitted = 0;
    try {
      for (; admitted < 128; ++admitted)
        held.push(mode === 3 ? new Promise<void>(() => {}) : pending.then(() => 'unreachable'));
    } catch (error) {
      if (!(error instanceof Error) || error.message !== label) throw error;
      if (admitted === 0 || admitted >= 128 || held.length !== admitted)
        throw new Error('runtime-limit-invalid-admission-count');
      return label + '|count=' + admitted + '|fresh=1';
    }
    throw new Error('runtime-limit-not-enforced');
  },
};
