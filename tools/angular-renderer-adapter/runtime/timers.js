// Runs before evaluating application modules. Limits accumulate for the entire
// Store; only real Store destruction retires its queues and resets its counters.
const enqueue = globalThis.queueMicrotask.bind(globalThis);
const pending = new Map();
let timers = 0;
let microtasks = 0;
const microtask = callback => {
  if (typeof callback !== 'function' || ++microtasks > 4096) {
    throw new Error('renderer-microtask-limit');
  }
  enqueue(callback);
};
const timeout = (callback, delay = 0, ...args) => {
  if (typeof callback !== 'function' || delay !== 0 || ++timers > 256) {
    throw new Error('renderer-timer-profile-denied');
  }
  const id = timers;
  pending.set(id, () => callback(...args));
  microtask(() => {
    const run = pending.get(id);
    pending.delete(id);
    if (run) run();
  });
  return id;
};
const denyInterval = () => { throw new Error('renderer-interval-denied'); };
for (const [name, value] of Object.entries({
  queueMicrotask: microtask, setTimeout: timeout, clearTimeout: id => pending.delete(id),
  setInterval: denyInterval, clearInterval: denyInterval,
})) {
  Object.defineProperty(globalThis, name, {value, writable: false, configurable: false});
}
