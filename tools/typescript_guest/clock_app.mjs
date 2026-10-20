// Application-realm guards. The selected engine retains ownership of clock reads.
export function installApplicationClocks(approved, snapshotActive, target = globalThis) {
  if (typeof approved !== 'boolean' || typeof snapshotActive !== 'function' ||
      !target || typeof target !== 'object' || typeof target.Date !== 'function') {
    throw new TypeError('standard-clock-installation-shape');
  }
  const OriginalDate = target.Date, Unsupported = Error;
  const apply = Reflect.apply, construct = Reflect.construct, get = Reflect.get;
  const originalNow = approved ? OriginalDate.now : null;
  const performance = target.performance ?? {};
  function descriptor(name) {
    let value = performance;
    for (let depth = 0; value && depth < 32; depth++, value = Object.getPrototypeOf(value)) {
      const found = Object.getOwnPropertyDescriptor(value, name);
      if (found) return found;
    }
    throw new TypeError('standard-clock-performance-backend-shape');
  }
  let elapsed, origin;
  if (approved) {
    const now = descriptor('now'), epoch = descriptor('timeOrigin');
    if (typeof originalNow !== 'function' || typeof now.value !== 'function' ||
        !('value' in epoch) && typeof epoch.get !== 'function') {
      throw new TypeError('standard-clock-performance-backend-shape');
    }
    elapsed = () => apply(now.value, performance, []);
    origin = 'value' in epoch ? () => epoch.value : () => apply(epoch.get, performance, []);
  }
  function requireClock() {
    if (snapshotActive()) throw new Unsupported('snapshot-time-clock-observation-unsupported');
    if (!approved) throw new Unsupported('unsupported:standard-clock-without-approved-profile');
  }
  function now() { requireClock(); return apply(originalNow, OriginalDate, []); }
  const SelectedDate = new Proxy(OriginalDate, {
    apply(target, self, args) {
      // Calling Date as a function always observes now, even Date('literal').
      requireClock();
      return apply(target, self, args);
    },
    construct(target, args, receiver) {
      if (args.length === 0) requireClock();
      return construct(target, args, receiver);
    },
    get(target, name, receiver) {
      return name === 'now' ? now : get(target, name, receiver);
    }
  });
  Object.defineProperty(OriginalDate.prototype, 'constructor', {
    value: SelectedDate, writable: true, configurable: true
  });
  target.Date = SelectedDate;
  Object.defineProperties(performance, {
    now: {value: function now() { requireClock(); return elapsed(); }, writable: true, configurable: true},
    timeOrigin: {get() { requireClock(); return origin(); }, configurable: true}
  });
  if (target.performance === undefined) target.performance = performance;
}
