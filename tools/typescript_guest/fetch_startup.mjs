// Compiler-owned banner: consume the private binding before any dependency's
// initializer. This module is never supplied or replaced by the application.
import {installFetchGlobals} from './fetch-sdk/http-fetch.mjs';
const bridge = globalThis.__lsfSdkFetchBridge;
if (!bridge || !delete globalThis.__lsfSdkFetchBridge) {
  throw new Error('SDK-fetch-private-binding-required');
}
installFetchGlobals(bridge);
