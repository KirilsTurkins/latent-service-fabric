// Qualification fixture. Production admission and the async web adapter are #233.
import {render as applicationRender} from './dist/server.js';

const enqueue = globalThis.queueMicrotask.bind(globalThis);
const pending = new Map();
let timers = 0;
let microtasks = 0;
globalThis.queueMicrotask = callback => {
  if (typeof callback !== 'function' || ++microtasks > 4096) {
    throw new Error('renderer-microtask-limit');
  }
  enqueue(callback);
};
globalThis.setTimeout = (callback, delay = 0, ...args) => {
  if (typeof callback !== 'function' || delay !== 0 || ++timers > 256) {
    throw new Error('renderer-timer-profile-denied');
  }
  const id = timers;
  pending.set(id, () => callback(...args));
  globalThis.queueMicrotask(() => {
    const run = pending.get(id);
    pending.delete(id);
    if (run) run();
  });
  return id;
};
globalThis.clearTimeout = id => pending.delete(id);
globalThis.setInterval = () => { throw new Error('renderer-interval-denied'); };
globalThis.clearInterval = () => { throw new Error('renderer-interval-denied'); };

// Counters deliberately survive calls: only discarding the Store resets a request.
export async function render(name) {
  try { return await applicationRender(name); }
  finally { pending.clear(); }
}

// Qualification-only export, never an application request or production API.
export async function probe(mode) {
  if (mode === 'spin') { for (;;) {} }
  if (mode === 'promise-storm') {
    const repeat = () => Promise.resolve().then(repeat);
    await repeat();
  }
  if (mode === 'throw') throw new Error('renderer-probe-exception');
  if (mode === 'allocate') {
    const held = [];
    for (let i = 0; i < 1024; i++) {
      const bytes = new Uint8Array(4 * 1024 * 1024);
      bytes.fill(7);
      held.push(bytes);
    }
    return 'unexpected allocation success';
  }
  if (mode === 'output') return 'x'.repeat(256 * 1024);
  if (mode === 'delayed-timer') setTimeout(() => {}, 1);
  if (mode === 'interval') setInterval(() => {}, 0);
  if (mode === 'timer-limit') {
    for (let i = 0; i < 257; i++) setTimeout(() => {}, 0);
  }
  if (mode === 'microtask-limit') {
    for (let i = 0; i < 4097; i++) queueMicrotask(() => {});
  }
  // Returning makes the host fail qualification if a supposed denial did not
  // happen. An unconditional throw here would mask a missing timer/work limit.
  return 'unexpected probe success';
}
