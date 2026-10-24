// This self-contained factory is emitted into the initializer binding realm.
// It observes the ORIGINAL native operations; it cannot mint a host owner.
export function createNodeNetTransport(calls, target, inspect) {
  const apply = Reflect.apply, freeze = Object.freeze, E = Error;
  const arrays = freeze({find: Array.prototype.find, indexOf: Array.prototype.indexOf,
    splice: Array.prototype.splice, push: Array.prototype.push, slice: Array.prototype.slice,
    includes: Array.prototype.includes, some: Array.prototype.some});
  const find = (values, predicate) => apply(arrays.find, values, [predicate]);
  const indexOf = (values, value) => apply(arrays.indexOf, values, [value]);
  const push = (values, value) => apply(arrays.push, values, [value]);
  const remove = (values, index) => apply(arrays.splice, values, [index, 1]);
  const copy = values => apply(arrays.slice, values, []);
  const includes = (values, value) => apply(arrays.includes, values, [value]);
  const some = (values, predicate) => apply(arrays.some, values, [predicate]);
  const define = Object.defineProperty, descriptor = Object.getOwnPropertyDescriptor;
  const P = target.Promise, then = P.prototype.then, promiseResolve = P.resolve;
  const resolve = value => apply(promiseResolve, P, [value]);
  const react = (promise, yes, no) => apply(then, promise, [yes, no]);
  const dispose = Symbol.dispose || Symbol.for('dispose');
  const slots = []; // Explicit two-Socket port ceiling, not an activation ledger.
  let returning = false; // Synchronous canonical-return admission fence only.
  const failure = code => new E('lsf-node-net:' + code);
  const rootKey = '__lsfNodeNetRootCheck';
  if (descriptor(target, rootKey)) throw failure('root-check-already-installed');
  const state = token => {
    const item = find(slots, value => value.token === token);
    if (!item) throw failure('foreign-or-retired-socket');
    return item;
  };
  function poison(item, error, user = false) {
    item.unknown = true;
    if (!item.faulted) { item.faulted = true; item.fault = error; }
    if (user) item.userFaulted = true;
  }
  function invoke(item, callback, receiver, value) {
    ++item.callbackTails;
    try { return apply(callback, receiver, [value]); }
    catch (error) { poison(item, error, true); throw error; }
    finally { --item.callbackTails; }
  }
  function maybeRetire(item) {
    if (item.unknown || item.pending.length || item.chunks.length || item.callbackTails ||
        item.externalTails || item.notification || !item.closed) return;
    const index = indexOf(slots, item);
    if (index < 0) throw failure('socket-registry-identity');
    remove(slots, index);
  }
  function stopReady(item) {
    if (!item.stop || item.stop.delivered || item.callbackTails || item.externalTails ||
        !(item.unknown || !item.pending.length && !item.chunks.length)) return false;
    const stop = item.stop;
    stop.delivered = true; stop.failed = item.unknown; stop.fault = item.fault;
    invoke(item, stop.callback, stop.receiver, stop);
    return true;
  }
  function progress(item) {
    if (item.userFaulted || item.callbackTails || item.externalTails || item.progressing) return;
    item.progressing = true;
    try {
      stopReady(item);
      if (!item.callbackTails && !item.externalTails && item.afterTail)
        apply(item.afterTail, item.receiver, []);
      // A drain listener can request destroy during the fixed progress hook.
      // Retire that tail, then deliver stop and one closing continuation.
      if (stopReady(item) && !item.callbackTails && !item.externalTails && item.afterTail)
        apply(item.afterTail, item.receiver, []);
    } catch (error) { poison(item, error, true); throw error; }
    finally { item.progressing = false; }
    maybeRetire(item);
  }
  function borrowFailure(item, record, error) {
    poison(item, error);
    if (!record.borrowFailed) { record.borrowFault = error; record.borrowFailed = true; }
  }
  function advance(item, record) {
    if (!record.logicalDone || !record.borrowObserved || item.userFaulted) return;
    if (record.callback && !record.delivered) {
      record.delivered = true; record.tail = true;
      // User callbacks live OUTSIDE bookkeeping catches. A thrown value becomes
      // the existing observer job's original unhandled rejection, never EIO.
      try { invoke(item, record.callback, record.receiver, record); }
      finally { record.tail = false; record.tailReturned = true; }
    }
    if (record.borrowDone && !record.borrowFailed && record.tailReturned &&
        (!record.cancelIssued || record.cancelDone && !record.cancelFailed)) {
      try {
        const index = indexOf(item.pending, record);
        if (index < 0) throw failure('operation-registry-identity');
        remove(item.pending, index);
      } catch (error) {
        borrowFailure(item, record, error);
        if (record.callback) throw error;
      }
    }
    progress(item);
  }
  function start(item, kind, args, borrowed, callback, receiver) {
    if (callback !== undefined && typeof callback !== 'function' ||
        item.unknown || item.pending.length >= 3 || item.closing && kind !== 'close')
      throw failure('operation-state');
    const record = {kind, borrowed, callback, receiver, delivered: false, tail: false,
      tailReturned: callback === undefined, logicalDone: false, logicalFailed: false,
      value: undefined, logicalFault: undefined, borrowObserved: false, borrowDone: false,
      borrowFailed: false, borrowFault: undefined, cancelIssued: false, cancelDone: false,
      cancelFailed: false, cancelFault: undefined, cancelPromise: undefined};
    // Every callback/receiver/state slot exists BEFORE the original CAP start.
    push(item.pending, record);
    let original;
    record.assertBorrowReleased = () => {
      if (record.borrowFailed) throw record.borrowFault;
      if (!record.borrowDone) {
        borrowFailure(item, record, failure('borrow-release-unconfirmed'));
        throw record.borrowFault;
      }
    };
    record.cancel = () => {
      try { return original.cancel(); }
      catch (error) { poison(item, error); throw error; }
    };
    try { original = apply(calls[kind], undefined, args); }
    catch (error) { poison(item, error); throw error; }
    try {
      record.promise = react(original.promise, value => {
        try {
          if (kind === 'connect') { item.connection = value; item.connectDone = true; }
          if (kind === 'read' && value !== undefined) push(item.chunks, value);
          if (kind === 'close') { item.connection = undefined; item.closed = true; }
          record.value = value; record.logicalDone = true;
        } catch (error) { borrowFailure(item, record, error); record.logicalDone = true; }
        advance(item, record);
        return value;
      }, error => {
        if (kind === 'connect') item.connectDone = true;
        if (kind === 'close') poison(item, error);
        record.logicalDone = true; record.logicalFailed = true; record.logicalFault = error;
        advance(item, record);
        // Callback clients consume the native failure on the joined path.
        // Direct private controls still receive the original logical rejection.
        if (!callback) throw error;
      });
    } catch (error) { poison(item, error); throw error; }
    try {
      record.borrowSettlement = react(original.borrowReleased, () => {
        record.borrowObserved = true; record.borrowDone = true;
        advance(item, record);
      }, error => {
        record.borrowObserved = true; borrowFailure(item, record, error);
        advance(item, record);
      });
    } catch (error) {
      record.borrowObserved = true; borrowFailure(item, record, error);
      try { record.borrowSettlement = resolve(); }
      catch { throw error; }
    }
    return freeze({promise: record.promise, borrowSettlement: record.borrowSettlement,
      assertBorrowReleased: record.assertBorrowReleased, cancel: record.cancel});
  }
  const checkRoot = () => { if (slots.length) throw failure('unclosed-sockets'); };
  define(target, rootKey, {value: checkRoot, writable: false, configurable: false});
  return freeze({
    assertEmpty: checkRoot,
    beginRootReturn() {
      if (returning) throw failure('nested-root-return');
      checkRoot();
      returning = true;
    },
    endRootReturn() {
      if (!returning) throw failure('root-return-not-held');
      returning = false;
    },
    reserve(afterTail, receiver) {
      if (afterTail !== undefined && typeof afterTail !== 'function') throw failure('socket-progress');
      if (returning) throw failure('canonical-return-admission');
      if (slots.length >= 2) throw failure('socket-port-limit');
      const token = freeze({});
      push(slots, {token, pending: [], chunks: [], connection: undefined,
        connecting: false, connectDone: false, closing: false, closed: false, unknown: false,
        faulted: false, fault: undefined, userFaulted: false, afterTail, receiver, progressing: false,
        callbackTails: 0, externalTails: 0, notification: false, stop: undefined});
      return token;
    },
    connect(token, request, callback, receiver) {
      if (returning) throw failure('canonical-return-admission');
      const item = state(token);
      if (item.connecting || item.connection || item.connectDone) throw failure('connect-state');
      item.connecting = true;
      return start(item, 'connect', [request], undefined, callback, receiver);
    },
    read(token, maximum, timeout, callback, receiver) {
      const item = state(token);
      if (!item.connection || item.chunks.length) throw failure('read-state');
      return start(item, 'read', [item.connection, maximum, timeout], item.connection, callback, receiver);
    },
    write(token, bytes, timeout, callback, receiver) {
      const item = state(token);
      if (!item.connection) throw failure('write-state');
      return start(item, 'write', [item.connection, bytes, timeout], item.connection, callback, receiver);
    },
    ready(token, callback, receiver) {
      const item = state(token);
      if (!item.connection) throw failure('ready-state');
      return start(item, 'ready', [item.connection, 'writable', undefined], item.connection, callback, receiver);
    },
    chunkBytes(token, chunk, callback, receiver) {
      const item = state(token);
      if (!includes(item.chunks, chunk)) throw failure('foreign-chunk');
      return start(item, 'chunkBytes', [chunk], chunk, callback, receiver);
    },
    disposeChunk(token, chunk) {
      const item = state(token), index = indexOf(item.chunks, chunk);
      if (item.unknown || index < 0 || some(item.pending, operation => operation.borrowed === chunk &&
          !(operation.tail && operation.logicalDone && operation.borrowDone && !operation.borrowFailed)))
        throw failure('chunk-borrow-live');
      const destroy = chunk[dispose];
      if (typeof destroy !== 'function') throw failure('chunk-destructor');
      // A trap/refusal never certifies destruction or permits registry removal.
      item.unknown = true;
      apply(destroy, chunk, []);
      remove(item.chunks, index);
      item.unknown = false;
      progress(item);
    },
    shutdown(token, callback, receiver) {
      const item = state(token);
      if (!item.connection || some(item.pending, operation => operation.kind === 'write'))
        throw failure('shutdown-state');
      return start(item, 'shutdown', [item.connection, 'send'], item.connection, callback, receiver);
    },
    inspect(token) {
      const item = state(token);
      if (!item.connection || item.closing || item.unknown) throw failure('inspect-state');
      return inspect(item.connection);
    },
    canProgress(token) {
      const item = state(token);
      return !item.callbackTails && !item.externalTails && !item.userFaulted;
    },
    enterTail(token) { ++state(token).externalTails; },
    leaveTail(token) {
      const item = state(token);
      if (!item.externalTails) throw failure('socket-tail-not-held');
      --item.externalTails; progress(item);
    },
    holdNotification(token) {
      const item = state(token);
      if (item.notification) throw failure('socket-notification-already-held');
      item.notification = true;
    },
    finishNotification(token) {
      const item = state(token);
      if (!item.notification) throw failure('socket-notification-not-held');
      item.notification = false; maybeRetire(item);
    },
    poison(token, error) { poison(state(token), error, true); },
    stop(token, callback, receiver) {
      const item = state(token);
      if (typeof callback !== 'function' || item.stop || item.closing) throw failure('close-state');
      item.closing = true;
      item.stop = {callback, receiver, delivered: false, failed: false, fault: undefined};
      const pending = copy(item.pending);
      // Issue ALL real original cancellations before observing ANY cancel ACK.
      for (const record of pending) {
        if (record.logicalDone && record.borrowDone && !record.borrowFailed) continue;
        record.cancelIssued = true;
        try { record.cancelPromise = record.cancel(); }
        catch (error) { record.cancelFailed = true; record.cancelFault = error; poison(item, error); }
      }
      for (const record of pending) {
        if (!record.cancelIssued || record.cancelFailed) continue;
        try {
          react(record.cancelPromise, () => {
            record.cancelDone = true;
            advance(item, record);
          }, error => {
            record.cancelFailed = true; record.cancelFault = error; poison(item, error);
            progress(item);
          });
        } catch (error) {
          record.cancelFailed = true; record.cancelFault = error; poison(item, error);
        }
      }
      progress(item);
    },
    close(token, callback, receiver) {
      const item = state(token);
      if (typeof callback !== 'function' || !item.stop?.delivered || item.unknown ||
          item.pending.length || item.chunks.length || item.callbackTails || item.externalTails)
        throw failure('close-before-drain');
      if (!item.connection) {
        if (!item.connectDone) throw failure('connect-result-unproven');
        item.closed = true;
        invoke(item, callback, receiver, {logicalFailed: false, borrowFailed: false});
        progress(item);
        return;
      }
      return start(item, 'close', [item.connection], item.connection, callback, receiver);
    },
  });
}
