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
