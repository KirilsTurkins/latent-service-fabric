// Compiler-local capture around one actual generated async import invocation.
// Its observer runs after native reservation and before typed lowering/dispatch.
export function nativeOperationCapture(imports, ApplicationPromise) {
  let current = null;

  function observe(id) {
    if (!current) return; // Ordinary calls allocate no retirement Promise.
    if (current.operation || !Number.isInteger(id) || id <= 0) {
      throw new TypeError('canonical-import-capture-not-a-single-operation');
    }
    const retired = imports.retired(id);
    current.operation = {id, retired, cancel() { imports.cancel(id, retired); }};
  }

  function invoke(callable, receiver, arguments_) {
    if (current) throw new TypeError('nested-canonical-import-capture-not-supported');
    if (typeof callable !== 'function' || !Array.isArray(arguments_)) {
      throw new TypeError('canonical-import-call-required');
    }
    const scope = {};
    current = scope;
    let result;
    try { result = ApplicationPromise.resolve(Reflect.apply(callable, receiver, arguments_)); }
    catch (error) { result = ApplicationPromise.reject(error); }
    finally { current = null; }
    if (!scope.operation) {
      // Missing admission/capture certifies no physical retirement. Keep the
      // original result/error, and fail its cleanup boundary independently.
      const retired = ApplicationPromise.reject(new TypeError('canonical-import-capture-missing'));
      return {result, retired, cancel() { throw new TypeError('canonical-import-capture-missing'); }};
    }
    return {result, ...scope.operation};
  }

  return Object.freeze({observe, invoke});
}
