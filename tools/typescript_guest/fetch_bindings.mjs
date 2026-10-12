// An explicit SDK fetch selection adds private operation access to the existing
// generated initializer. This creates no grant and exposes no application pump.
export function fetchOperationBindings(source, captureSource) {
  const declaration = 'export function nativeOperationCapture(';
  if (captureSource.split(declaration).length !== 2) {
    throw new Error('fetch-native-operation-source-shape');
  }
  const capture = captureSource.replace(declaration, 'function nativeOperationCapture(');
  const anchor = 'const __lsfApplicationPromise = contentGlobal.Promise;\n';
  const registration = '  defineBuiltinModule(name, normalized);\n';
  if (source.split(anchor).length !== 2 || source.split(registration).length !== 2) {
    throw new Error('fetch-initializer-operation-hook-shape');
  }
  const integration = `
${capture}
const __lsfFetchCapture = nativeOperationCapture(__lsfImports, __lsfApplicationPromise);
const __lsfObserveNativeImport = id => __lsfFetchCapture.observe(id);
let __lsfFetchHttp;
const __lsfFetchBridge = Object.freeze({
  get http() {
    if (!__lsfFetchHttp) throw new Error('SDK-streaming-HTTP-module-not-bound');
    return __lsfFetchHttp;
  },
  invoke: __lsfFetchCapture.invoke
});
Object.defineProperty(contentGlobal, '__lsfSdkFetchBridge',
  {value: __lsfFetchBridge, configurable: true});
`;
  return source.replace(anchor, anchor + integration).replace(registration,
    `  if (name === 'latent:http/streaming@0.3.0') {
    if (__lsfFetchHttp) throw new Error('duplicate-SDK-streaming-HTTP-module');
    __lsfFetchHttp = normalized;
  }
` + registration);
}
