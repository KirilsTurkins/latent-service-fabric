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
  const P = target.Promise, then = P.prototype.then;
  const resolve = value => apply(P.resolve, P, [value]);
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
  function maybeRetire(item) {
    if (item.unknown || item.pending.length || item.chunks.length) return;
    if (!item.closed) return;
    const index = indexOf(slots, item);
    if (index < 0) throw failure('socket-registry-identity');
    remove(slots, index);
  }
  function collected(item, operation) {
    if (!operation.logicalDone || !operation.borrowDone) return;
    const index = indexOf(item.pending, operation);
    if (index < 0) throw failure('operation-registry-identity');
    remove(item.pending, index);
    maybeRetire(item);
  }
  function start(item, kind, args, borrowed) {
    if (item.unknown || item.pending.length >= 3 || item.closing && kind !== 'close')
      throw failure('operation-state');
    const record = {kind, borrowed, logicalDone: false, borrowDone: false};
    push(item.pending, record); // Retain state before the original native start.
    let original;
    try { original = apply(calls[kind], undefined, args); }
    catch (error) { item.unknown = true; throw error; }
    record.promise = react(original.promise, value => {
      if (kind === 'connect') { item.connection = value; item.connectDone = true; }
      if (kind === 'read' && value !== undefined) push(item.chunks, value);
      if (kind === 'close') { item.connection = undefined; item.closed = true; }
      record.logicalDone = true;
      collected(item, record);
      return value;
    }, error => {
      if (kind === 'connect') item.connectDone = true;
      if (kind === 'close') item.unknown = true;
      record.logicalDone = true;
      collected(item, record);
      throw error;
    });
    try {
      record.borrowReleased = react(original.borrowReleased, () => {
        record.borrowDone = true;
        collected(item, record);
      }, error => { item.unknown = true; throw error; });
    } catch (error) {
      // No handle is NOT a release acknowledgement. Keep this reservation.
      item.unknown = true;
      record.borrowReleased = react(resolve(), () => { throw error; });
    }
    // Observe internal acknowledgement failures even before destroy is called.
    // The state remains poisoned; the public operation retains its own result.
    react(record.borrowReleased, undefined, () => undefined);
    record.cancel = () => {
      try { return original.cancel(); }
      catch (error) { item.unknown = true; throw error; }
    };
    return freeze({promise: record.promise, borrowReleased: record.borrowReleased,
      cancel: record.cancel});
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
    reserve() {
      if (returning) throw failure('canonical-return-admission');
      if (slots.length >= 2) throw failure('socket-port-limit');
      const token = freeze({});
      push(slots, {token, pending: [], chunks: [], connection: undefined,
        connecting: false, connectDone: false, closing: false, closed: false, unknown: false});
      return token;
    },
    connect(token, request) {
      if (returning) throw failure('canonical-return-admission');
      const item = state(token);
      if (item.connecting || item.connection || item.connectDone) throw failure('connect-state');
      item.connecting = true;
      return start(item, 'connect', [request]);
    },
    read(token, maximum, timeout) {
      const item = state(token);
      if (!item.connection || item.chunks.length) throw failure('read-state');
      return start(item, 'read', [item.connection, maximum, timeout], item.connection);
    },
    write(token, bytes, timeout) {
      const item = state(token);
      if (!item.connection) throw failure('write-state');
      return start(item, 'write', [item.connection, bytes, timeout], item.connection);
    },
    ready(token) {
      const item = state(token);
      if (!item.connection) throw failure('ready-state');
      return start(item, 'ready', [item.connection, 'writable', undefined], item.connection);
    },
    chunkBytes(token, chunk) {
      const item = state(token);
      if (!includes(item.chunks, chunk)) throw failure('foreign-chunk');
      return start(item, 'chunkBytes', [chunk], chunk);
    },
    disposeChunk(token, chunk) {
      const item = state(token), index = indexOf(item.chunks, chunk);
      if (item.unknown || index < 0 || some(item.pending, operation => operation.borrowed === chunk))
        throw failure('chunk-borrow-live');
      const destroy = chunk[dispose];
      if (typeof destroy !== 'function') throw failure('chunk-destructor');
      // A trap/refusal never certifies destruction or permits registry removal.
      item.unknown = true;
      apply(destroy, chunk, []);
      remove(item.chunks, index);
      item.unknown = false;
      maybeRetire(item);
    },
    shutdown(token) {
      const item = state(token);
      if (!item.connection || some(item.pending, operation => operation.kind === 'write'))
        throw failure('shutdown-state');
      return start(item, 'shutdown', [item.connection, 'send'], item.connection);
    },
    inspect(token) {
      const item = state(token);
      if (!item.connection || item.closing || item.unknown) throw failure('inspect-state');
      return inspect(item.connection);
    },
    async stop(token) {
      const item = state(token);
      if (item.closing || item.unknown) throw failure('close-state');
      item.closing = true;
      const pending = copy(item.pending), cancellations = [];
      // Issue ALL original cancellations before awaiting any acknowledgement.
      let cancellationError;
      for (let index = 0; index < pending.length; ++index) {
        try { push(cancellations, pending[index].cancel()); }
        catch (error) { item.unknown = true; cancellationError ||= error; push(cancellations, undefined); }
      }
      if (cancellationError !== undefined) throw cancellationError;
      for (let index = 0; index < pending.length; ++index) {
        try { await pending[index].promise; } catch { /* Original caller observes it. */ }
        try { await cancellations[index]; await pending[index].borrowReleased; }
        catch (error) { item.unknown = true; throw error; }
      }
      if (item.unknown || item.pending.length) throw failure('close-acknowledgement');
      // The owned Socket's actual read/copy worker must finish its finally and
      // dispose arrived chunks before close. Never race a second chunk drop.
    },
    async close(token) {
      const item = state(token);
      if (!item.closing || item.unknown || item.pending.length || item.chunks.length)
        throw failure('close-before-drain');
      if (!item.connection) {
        if (!item.connectDone) throw failure('connect-result-unproven');
        item.closed = true;
        maybeRetire(item);
        return;
      }
      const operation = start(item, 'close', [item.connection]);
      await operation.promise;
      await operation.borrowReleased;
      if (!item.closed || item.unknown) throw failure('close-not-confirmed');
    },
  });
}
