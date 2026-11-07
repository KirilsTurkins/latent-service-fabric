import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';
import {request, requestReady, promiseReady, requestCopyReady, initialized} from './default-client.js';

// Probe-local declarations for the native globals; no broader DOM API claim.
declare class Event { constructor(type: string); }
declare class EventTarget {
  addEventListener(type: string, listener: () => void): void;
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

export const api: typeof Contract = {
  async run(mode, url) {
    if (mode === 1) return 'entered';
    if (mode === 2) return requestReady(url);
    if (mode === 3) return await promiseReady();
    if (mode === 4) return await requestCopyReady(url);
    if (mode === 20) return repeatedEventClone();
    if (mode === 21) return nestedEventClone();
    if (mode !== 0) throw new TypeError('unsupported-fetch-runtime-mode');
    return `${++calls}:${await request(url)}`;
  },
};
