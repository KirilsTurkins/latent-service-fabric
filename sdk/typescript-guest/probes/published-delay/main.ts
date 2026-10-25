import delay, { clearDelay } from 'delay';

let calls = 0;
function check(value: boolean): void { if (!value) throw new Error('published-delay-fixture'); }
export const api = {
  async run(which: number): Promise<string> {
    check(++calls === 1);
    if (which === 0) {
      check(await delay(1, { value: 'ordinary' }) === 'ordinary');
    } else if (which === 1) {
      const order = ['before'];
      const pending = delay(1, { value: 'nested' }).then(value => {
        order.push('timer');
        return Promise.resolve(value).then(result => { order.push('nested'); return result; });
      });
      Promise.resolve().then(() => { order.push('micro'); });
      order.push('after');
      check(await pending === 'nested');
      check(order.join(',') === 'before,after,micro,timer,nested');
    } else if (which === 2) {
      const pending = delay(60000, { value: 'cleared' });
      clearDelay(pending);
      check(await pending === 'cleared');
    } else if (which === 3) {
      const controller = new AbortController();
      const reason = { source: 'pre-aborted' };
      controller.abort(reason);
      let matched = false;
      try { await delay(60000, { signal: controller.signal }); }
      catch (error) { matched = error === reason; }
      check(matched);
    } else if (which === 4) {
      const controller = new AbortController();
      const reason = { source: 'pending-abort' };
      // Attach the rejection observer in the creation turn. The original
      // Promise still rejects; the observer preserves its exact reason value.
      const observed = delay(60000, { signal: controller.signal, value: 'forbidden' })
        .then(() => false, error => error === reason);
      check(await delay(1, { value: 'abort-turn' }) === 'abort-turn');
      controller.abort(reason);
      check(await observed);
    } else if (which === 5) {
      check(await delay(1, { value: 'fresh' }) === 'fresh');
    } else throw new RangeError('published-delay-fixture-mode');
    return 'published-delay:' + which + ':pass|fresh=1';
  },
};
