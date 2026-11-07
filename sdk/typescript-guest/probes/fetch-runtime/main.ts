import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';
import {request, requestReady, promiseReady, requestCopyReady, initialized} from './default-client.js';

// Probe-local declarations for the native globals; no broader DOM API claim.
declare class Event { constructor(type: string); }
declare class EventTarget {
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
  dispatchEvent(event: Event): boolean;
}

// Only pure constructors are snapshotted; native signal owners stay invocation-local.
const headers = new Headers([['x-direct', 'present']]);
if (new Response(null, {headers}).headers.get('x-direct') !== 'present' || !initialized) {
  throw new Error('fetch-runtime-direct-initialization');
}
let calls = 0;

// More than the pinned RootedVector's inline capacity, with each listener a
// distinct function. Construct the mutable graph only inside an activation.
function repeatedEventClone(): string {
  const target = new EventTarget();
  const event = new Event('clone');
  const counts = Array<number>(12).fill(0);
  for (let index = 0; index < counts.length; ++index) {
    target.addEventListener('clone', () => { ++counts[index]; });
  }
  for (let turn = 0; turn < 40; ++turn) {
    if (!target.dispatchEvent(event)) throw new Error('event-clone-repeated-dispatch');
  }
  if (counts.some(count => count !== 40)) throw new Error('event-clone-repeated-count');
  return 'event-clone:repeated:12:40';
}

function nestedEventClone(): string {
  const target = new EventTarget();
  const outer = new Event('clone');
  const inner = new Event('clone');
  const seen: string[] = [];
  let nested = false, innerSucceeded = false;
  for (let index = 0; index < 12; ++index) {
    target.addEventListener('clone', () => {
      seen.push(`${nested ? 'inner' : 'outer'}:${index}`);
      if (!nested && index === 0) {
        nested = true;
        try { innerSucceeded = target.dispatchEvent(inner); }
        finally { nested = false; }
      }
    });
  }
  if (!target.dispatchEvent(outer) || !innerSucceeded) throw new Error('event-clone-nested-dispatch');
  const expected = ['outer:0'];
  for (let index = 0; index < 12; ++index) expected.push(`inner:${index}`);
  for (let index = 1; index < 12; ++index) expected.push(`outer:${index}`);
  if (seen.join(',') !== expected.join(',')) throw new Error('event-clone-nested-order');
  return 'event-clone:nested:12:ordered';
}

function ordinaryAbortClone(): string {
  const controller = new AbortController();
  const reason = {kind: 'ordinary-abort'};
  let calls = 0;
  for (let index = 0; index < 12; ++index) {
    controller.signal.addEventListener('abort', () => { ++calls; });
  }
  controller.abort(reason);
  if (!controller.signal.aborted || controller.signal.reason !== reason || calls !== 12)
    throw new Error('abort-clone-normal-result');
  return 'abort-clone:normal:12';
}

function refusedAbortClone(): void {
  const controller = new AbortController();
  const reason = {kind: 'refused-abort'};
  const expected = 'activation-runtime-promise-native-register-denied:2';
  let calls = 0, fillDenied = false, abortDenied = false;
  for (let index = 0; index < 12; ++index) {
    controller.signal.addEventListener('abort', () => { ++calls; });
  }
  const filler = new EventTarget();
  const held: Array<() => void> = [];
  try {
    for (let index = 0; index < 128; ++index) {
      const listener = () => {};
      try {
        filler.addEventListener('fill', listener);
        held.push(listener);
      } catch (error) {
        if (!(error instanceof Error) || error.message !== expected) throw error;
        fillDenied = true;
        break;
      }
    }
    if (!fillDenied || held.length === 0 || held.length >= 128)
      throw new Error('abort-clone-fill-boundary-missing');
    try { controller.abort(reason); }
    catch (error) {
      if (!(error instanceof Error) || error.message !== expected) throw error;
      abortDenied = true;
    }
    if (!abortDenied || !controller.signal.aborted || controller.signal.reason !== reason || calls !== 0)
      throw new Error('abort-clone-failure-not-propagated');
  } finally {
    for (const listener of held) filler.removeEventListener('fill', listener);
  }
}

function recoveredEventClone(): string {
  const target = new EventTarget();
  let calls = 0;
  for (let index = 0; index < 12; ++index) {
    target.addEventListener('recovered', () => { ++calls; });
  }
  if (!target.dispatchEvent(new Event('recovered')) || calls !== 12)
    throw new Error('abort-clone-recovery-result');
  return 'abort-clone:two-native-register-refusals:recovered';
}

export const api: typeof Contract = {
  async run(mode, url) {
    if (mode === 1) return 'entered';
    if (mode === 2) return requestReady(url);
    if (mode === 3) return await promiseReady();
    if (mode === 4) return await requestCopyReady(url);
    if (mode === 20) return repeatedEventClone();
    if (mode === 21) return nestedEventClone();
    if (mode === 22) return ordinaryAbortClone();
    if (mode === 23) {
      refusedAbortClone();
      // Normal Promise allocation invokes the existing pressure-GC/checkpoint.
      await Promise.resolve();
      return recoveredEventClone();
    }
    if (mode !== 0) throw new TypeError('unsupported-fetch-runtime-mode');
    return `${++calls}:${await request(url)}`;
  },
};
