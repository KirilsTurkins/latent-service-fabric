import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';
import {request, requestReady, promiseReady, requestCopyReady, initialized} from './default-client.js';

// Probe-local declarations for the native globals; no broader DOM API claim.
declare class DOMException extends Error { constructor(message?: string, name?: string); }
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

function abortAnyFrames(): string {
  const source = new AbortController();
  // Each iteration grows the conversion vector, then exits before creating a
  // dependent signal. More iterations than the native-owner ceiling require
  // continued progress without treating return from any() as a host witness.
  for (let turn = 0; turn < 80; ++turn) {
    const sentinel = {turn};
    let next = 0, caught: unknown;
    function* interrupted(): Generator<AbortSignal> {
      for (let index = 0; index < 9; ++index) { ++next; yield source.signal; }
      ++next;
      throw sentinel;
    }
    try { AbortSignal.any(interrupted()); } catch (error) { caught = error; }
    if (caught !== sentinel || next !== 10) throw new Error('abort-any-interrupted-conversion');
  }

  const seen: string[] = [];
  const holder: {signal?: AbortSignal} = {};
  function* inner(): Generator<AbortSignal> {
    for (let index = 0; index < 12; ++index) {
      seen.push(`inner:${index}`);
      yield source.signal;
    }
    seen.push('inner:done');
  }
  function* outer(): Generator<AbortSignal> {
    for (let index = 0; index < 12; ++index) {
      seen.push(`outer:${index}`);
      // The outer vector already has nine entries when inner any() starts.
      if (index === 9) holder.signal = AbortSignal.any(inner());
      yield source.signal;
    }
    seen.push('outer:done');
  }
  const result = AbortSignal.any(outer());
  const nested = holder.signal;
  const expected = [
    ...Array.from({length: 10}, (_, index) => `outer:${index}`),
    ...Array.from({length: 12}, (_, index) => `inner:${index}`),
    'inner:done', 'outer:10', 'outer:11', 'outer:done',
  ];
  if (!nested || result.aborted || nested.aborted || seen.join(',') !== expected.join(','))
    throw new Error('abort-any-nested-iteration');
  let outerEvents = 0, innerEvents = 0;
  result.addEventListener('abort', () => { ++outerEvents; });
  nested.addEventListener('abort', () => { ++innerEvents; });
  const reason = {kind: 'nested-any'};
  source.abort(reason);
  source.abort({kind: 'ignored'});
  if (!result.aborted || !nested.aborted || result.reason !== reason || nested.reason !== reason ||
      outerEvents !== 1 || innerEvents !== 1) throw new Error('abort-any-dependent-state');
  return 'abort-any:80:nested:12:ordered';
}

function refusedAbortAnyFrame(): AbortController {
  const source = new AbortController();
  const filler = new EventTarget();
  const held: Array<() => void> = [];
  const expected = 'activation-runtime-promise-native-register-denied:2';
  let fillDenied = false;
  try {
    for (let index = 0; index < 128; ++index) {
      const listener = () => {};
      try { filler.addEventListener('any-fill', listener); held.push(listener); }
      catch (error) {
        if (!(error instanceof Error) || error.message !== expected) throw error;
        fillDenied = true;
        break;
      }
    }
    if (!fillDenied || held.length === 0 || held.length >= 128)
      throw new Error('abort-any-fill-boundary-missing');

    const closeSentinel = {kind: 'iterator-return-throws'};
    let next = 0, closed = 0, caught: unknown;
    const signals: Iterable<AbortSignal> = {
      [Symbol.iterator](): Iterator<AbortSignal> {
        return {
          next(): IteratorResult<AbortSignal> {
            ++next;
            if (next > 12) return {done: true, value: undefined};
            return {done: false, value: source.signal};
          },
          return(): IteratorResult<AbortSignal> {
            ++closed;
            throw closeSentinel;
          },
        };
      },
    };
    try { AbortSignal.any(signals); } catch (error) { caught = error; }
    if (!(caught instanceof Error) || caught.message !== expected || next !== 9 || closed !== 1 ||
        source.signal.aborted) throw new Error('abort-any-refusal-close');
  } finally {
    for (const listener of held) filler.removeEventListener('any-fill', listener);
  }
  return source;
}

function recoveredAbortAnyFrame(source: AbortController): string {
  const result = AbortSignal.any(Array<AbortSignal>(12).fill(source.signal));
  if (result.aborted) throw new Error('abort-any-recovery-initial-state');
  const reason = {kind: 'any-recovery'};
  source.abort(reason);
  if (!result.aborted || result.reason !== reason) throw new Error('abort-any-recovery-result');
  return 'abort-any:refusal:closed:recovered';
}

function abortDefaultReason(): string {
  for (let turn = 0; turn < 2; ++turn) {
    const source = new AbortController();
    const first = AbortSignal.any([source.signal]);
    const second = AbortSignal.any([source.signal]);
    let firstEvents = 0, secondEvents = 0;
    let firstObserved: unknown, secondObserved: unknown;
    first.addEventListener('abort', () => { ++firstEvents; firstObserved = first.reason; });
    second.addEventListener('abort', () => { ++secondEvents; secondObserved = second.reason; });
    if (turn === 0) source.abort(); else source.abort(undefined);
    const reason = source.signal.reason;
    source.abort({kind: 'ignored-second-abort'});
    const alreadyAborted = AbortSignal.any([source.signal]);
    if (!reason || typeof reason !== 'object' || reason.name !== 'AbortError' ||
        !first.aborted || !second.aborted || !alreadyAborted.aborted ||
        first.reason !== reason || second.reason !== reason || alreadyAborted.reason !== reason ||
        firstObserved !== reason || secondObserved !== reason || firstEvents !== 1 || secondEvents !== 1)
      throw new Error('abort-default-reason-identity');
    for (const signal of [source.signal, first, second, alreadyAborted]) {
      let caught: unknown;
      try { signal.throwIfAborted(); } catch (error) { caught = error; }
      if (caught !== reason) throw new Error('abort-default-thrown-reason');
    }
  }
  return 'abort-default:shared:2:thrown';
}

// Nine distinct dependent signals exceed the native fan-out vector's inline
// capacity while preserving the qualification programme's 64-owner ceiling.
function abortFanoutGraph() {
  const source = new AbortController();
  const dependents = Array.from({length: 9}, () => AbortSignal.any([source.signal]));
  const reason = {kind: 'fanout'};
  const seen: number[] = [];
  let readyAtRoot = false;
  source.signal.addEventListener('abort', () => {
    readyAtRoot = dependents.every(signal => signal.aborted && signal.reason === reason);
    seen.push(-1);
    source.abort({kind: 'ignored-reentrant-abort'});
  });
  for (let index = 0; index < dependents.length; ++index) {
    dependents[index].addEventListener('abort', () => { seen.push(index); });
  }
  return {
    source, reason,
    unchanged() {
      return !source.signal.aborted && source.signal.reason === undefined && seen.length === 0 &&
        dependents.every(signal => !signal.aborted && signal.reason === undefined);
    },
    verify() {
      if (!readyAtRoot || !source.signal.aborted || source.signal.reason !== reason ||
          !dependents.every(signal => signal.aborted && signal.reason === reason) ||
          seen.join(',') !== '-1,0,1,2,3,4,5,6,7,8') throw new Error('abort-fanout-publication-or-order');
      for (const signal of [source.signal, ...dependents]) {
        let caught: unknown;
        try { signal.throwIfAborted(); } catch (error) { caught = error; }
        if (caught !== reason) throw new Error('abort-fanout-reason-identity');
      }
    },
  };
}

function ordinaryAbortFanout(): string {
  const graph = abortFanoutGraph();
  graph.source.abort(graph.reason);
  graph.source.abort({kind: 'ignored-after-fanout'});
  graph.verify();
  return 'abort-fanout:9:ordered';
}

function refusedAbortFanout() {
  const graph = abortFanoutGraph();
  const filler = new EventTarget();
  const held: Array<() => void> = [];
  const expected = 'activation-runtime-promise-native-register-denied:2';
  let fillDenied = false, abortDenied = false;
  try {
    for (let index = 0; index < 128; ++index) {
      const listener = () => {};
      try { filler.addEventListener('fanout-fill', listener); held.push(listener); }
      catch (error) {
        if (!(error instanceof Error) || error.message !== expected) throw error;
        fillDenied = true;
        break;
      }
    }
    if (!fillDenied || held.length === 0 || held.length >= 128)
      throw new Error('abort-fanout-fill-boundary-missing');
    try { graph.source.abort(graph.reason); }
    catch (error) {
      if (!(error instanceof Error) || error.message !== expected) throw error;
      abortDenied = true;
    }
    if (!abortDenied || !graph.unchanged()) throw new Error('abort-fanout-refusal-mutated-state');
  } finally {
    for (const listener of held) filler.removeEventListener('fanout-fill', listener);
  }
  return graph;
}

function reentrantDefaultAbortFanout(): string {
  const graph = abortFanoutGraph();
  const original = DOMException;
  const descriptor = Object.getOwnPropertyDescriptor(original.prototype, 'constructor');
  if (!descriptor) throw new Error('abort-fanout-default-constructor-missing');
  let entered = 0;
  Object.defineProperty(original.prototype, 'constructor', {
    ...descriptor,
    value: function(message?: string, name?: string) {
      ++entered;
      graph.source.abort(graph.reason);
      return new original(message, name);
    },
  });
  try { graph.source.abort(); }
  finally { Object.defineProperty(original.prototype, 'constructor', descriptor); }
  // This probes the selected native factory, not Node's primordial factory.
  // A missing reentrant execution is a failure, never a passing fallback.
  if (entered !== 1) throw new Error('abort-fanout-default-factory-not-reentered');
  graph.verify();
  const fresh = new AbortController();
  fresh.abort();
  if (!fresh.signal.aborted || fresh.signal.reason?.name !== 'AbortError' || entered !== 1)
    throw new Error('abort-fanout-default-constructor-not-restored');
  return 'abort-fanout:default-reentry:first-wins';
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
    if (mode === 24) return abortAnyFrames();
    if (mode === 25) {
      const source = refusedAbortAnyFrame();
      // As in the existing abort-clone case, use the ordinary Promise
      // allocation path to collect and checkpoint unreachable listener owners.
      await Promise.resolve();
      return recoveredAbortAnyFrame(source);
    }
    if (mode === 26) return abortDefaultReason();
    if (mode === 27) return ordinaryAbortFanout();
    if (mode === 28) {
      let stage = 'refusal';
      try {
        const graph = refusedAbortFanout();
        // Use the ordinary allocation/GC checkpoint, not a fixture-only pump.
        stage = 'checkpoint';
        await Promise.resolve();
        // A refused fan-out must not resume itself when admission recovers.
        stage = 'after-checkpoint';
        if (!graph.unchanged()) throw new Error('abort-fanout-checkpoint-mutated-state');
        stage = 'retry';
        graph.source.abort(graph.reason);
        stage = 'verification';
        graph.verify();
        return 'abort-fanout:refusal:unchanged:recovered';
      } catch (error) {
        // Keep a finite diagnostic instead of losing a catchable failure to
        // the component's generic rejected-export trap. This is never the
        // success value; the signed runner rejects every diagnostic result.
        const cause = error instanceof Error &&
          error.message === 'activation-runtime-promise-native-register-denied:2'
          ? 'native-admission' : 'contract';
        return `diagnostic:abort-fanout:${stage}:${cause}`;
      }
    }
    if (mode === 29) return reentrantDefaultAbortFanout();
    if (mode !== 0) throw new TypeError('unsupported-fetch-runtime-mode');
    return `${++calls}:${await request(url)}`;
  },
};
