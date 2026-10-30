import { createHash } from 'node:crypto';
// Only the fixed compiler diagnostic may select this maintained generated read.
import { borrowReleaseHandoff } from './import_cancellation.mjs';
export const borrowProbeProfile = 'lsf-typescript-borrow-probe-v1';
export const borrowProbeBuiltin = 'lsf:typescript-borrow-probe';
const selected = Object.freeze([Object.freeze({
  binding: 'import_tests_typescript_import_borrow_gate_streams_1_0_0$read', alias: 'read'
})]);
export function borrowProbeBindings(source, parse, selection) {
  if (selection === undefined) return source;
  if (selection !== borrowProbeProfile || source.includes(borrowProbeBuiltin)) {
    throw new Error('compiler-owned-borrow-probe-selection');
  }
  const result = borrowReleaseHandoff(source, parse, selected);
  return result + '\ndefineBuiltinModule(' + JSON.stringify(borrowProbeBuiltin) +
    ', {startRead: __lsfBorrowCalls.read});\n';
}
export function borrowProbeConfiguration(configuration, imports) {
  if (configuration.borrowProbeProfile === undefined) return false;
  if (configuration.borrowProbeProfile !== borrowProbeProfile ||
      configuration.runtimeProfile !== 'spidermonkey-activation-promises-clocks-imports-v1' ||
      imports.size !== 3 ||
      !imports.has('latent:network/streams@0.1.0') ||
      !imports.has('tests:typescript-import-borrow-gate/streams@1.0.0') ||
      !imports.has('tests:typescript-import-borrow-gate/diagnostic@1.0.0')) {
    throw new Error('compiler-owned-borrow-probe-configuration');
  }
  return true;
}

// Read-only compiler diagnostic. The original splice API remains synchronous;
// its exact result object, bytes and imports/exports are returned unchanged.
export function borrowProbeSpliceCapture(selection, emit) {
  if (selection === undefined) return undefined;
  if (selection !== borrowProbeProfile || typeof emit !== 'function')
    throw new Error('compiler-owned-borrow-splice-capture-selection');
  return result => {
    const fail = () => { throw new Error('compiler-owned-borrow-splice-capture-shape-or-bound'); };
    if (!result || Object.keys(result).sort().join(',') !== 'exports,imports,jsBindings,wasm') fail();
    const {wasm, jsBindings, imports, exports} = result;
    if (!(wasm instanceof Uint8Array) || wasm.byteLength < 8 || wasm.byteLength > 64 * 1024 * 1024 ||
        [0,97,115,109,1,0,0,0].some((value,index) => wasm[index] !== value) ||
        typeof jsBindings !== 'string' || Buffer.byteLength(jsBindings,'utf8') > 8 * 1024 * 1024 ||
        !Array.isArray(imports) || imports.length > 512 || !Array.isArray(exports) || exports.length > 512) fail();
    const sha = value => 'sha256:' + createHash('sha256').update(value).digest('hex');
    const core = sha(wasm), bindings = sha(jsBindings), metadata = JSON.stringify({imports,exports});
    if (Buffer.byteLength(metadata,'utf8') > 1024 * 1024) fail();
    const receipt = JSON.stringify({schemaVersion:'latent.typescript.pre-wizer-splice.v1',
      scope:'diagnostic-raw-splice-not-runtime-qualification',
      wasm:{bytes:wasm.byteLength,sha256:core},
      rawBindings:{bytes:Buffer.byteLength(jsBindings,'utf8'),sha256:bindings},imports,exports,
      sameOriginalSpliceResult:true,signedExecution:false})+'\n';
    if (Buffer.byteLength(receipt,'utf8') > 1024 * 1024) fail();
    emit('pre-wizer.wasm',wasm);
    emit('pre-wizer-raw-bindings.js',jsBindings);
    emit('pre-wizer-splice.json',receipt);
    if (result.wasm !== wasm || result.jsBindings !== jsBindings || result.imports !== imports ||
        result.exports !== exports || sha(wasm) !== core ||
        JSON.stringify({imports,exports}) !== metadata) throw new Error('compiler-owned-borrow-splice-capture-mutated');
    return result;
  };
}
