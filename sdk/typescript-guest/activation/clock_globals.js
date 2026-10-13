// LSF-owned selected source module, installed before any application module.
// The native reads enforce phase, exact typed imports and caller grants.
(({wall, now, origin}) => {
  const OriginalDate = globalThis.Date;
  const SelectedDate = new Proxy(OriginalDate, {
    apply() {
      return new OriginalDate(wall()).toString();
    },
    construct(target, args, receiver) {
      return Reflect.construct(target, args.length ? args : [wall()], receiver);
    }
  });
  Object.defineProperty(OriginalDate, 'now', {
    value: wall, writable: true, configurable: true
  });
  Object.defineProperty(OriginalDate.prototype, 'constructor', {
    value: SelectedDate, writable: true, configurable: true
  });
  globalThis.Date = SelectedDate;
  Object.defineProperties(globalThis.performance, {
    now: {value: now, writable: true, configurable: true},
    timeOrigin: {get: origin, configurable: true}
  });
})(__lsfSelectedClockBridge);
delete globalThis.__lsfSelectedClockBridge;
