// Run with the separately authenticated Firefox 147 JS shell, not Node.
let held;
let promiseWeak;
let rejectWeak;
(function createAndResolve() {
  let reject;
  const promise = new Promise((resolve, fail) => { held = resolve; reject = fail; });
  promiseWeak = new WeakRef(promise);
  rejectWeak = new WeakRef(reject);
  held(42);
})();
clearKeptObjects();
gc();
assertEq(promiseWeak.deref(), undefined);
assertEq(rejectWeak.deref(), undefined);
assertEq(typeof held, 'function');
assertEq(held(99), undefined);
print(JSON.stringify({case: 'retained-resolver', promiseCollected: true,
  rejectCollected: true, resolverRetained: true, engineQualified: false}));
