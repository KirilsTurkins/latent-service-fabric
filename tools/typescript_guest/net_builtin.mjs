import { NET_PROFILE, NET_PRIVATE } from './node_net_bindings.mjs';

// Compiler-only boundary, independent of the host Node version and npm package
// identity. These exact builtins must not resolve to captured npm/browser shims.
// This does not install a stream, resolver or TLS implementation in the guest.
const unavailable = new Map([
  ...['dns', 'dns/promises'].map(name => [name,
    'No public DNS API is installed. Hostname resolution belongs to an explicitly authorized TCP connect; it does not authorize lookup, resolve, reverse or custom resolvers.']),
  ['tls',
    'No Node TLS port is installed. The TCP profile cannot supply TLS certificate callbacks, STARTTLS or client identity; host TLS is not a transparent replacement.'],
  ...['stream', 'stream/promises', 'stream/web', 'stream/consumers',
    '_stream_duplex', '_stream_passthrough', '_stream_readable',
    '_stream_transform', '_stream_wrap', '_stream_writable'].map(name => [name,
    'No general Node stream module is installed. The Socket event subset is not Readable, Writable, Duplex, pipeline or a Web Streams adapter.']),
]);
const compatibility = 'See docs/component-development/typescript-network-compatibility.md. Issue #737 approves a contract, not runtime enablement; #745 networking consumes the implementation and qualification gates in #738 and #739. No npm dependency or module declaration grants network authority.';

function unavailableModule(path) {
  const name = path.startsWith('node:') ? path.slice(5) : path;
  const explanation = unavailable.get(name);
  if (explanation === undefined) return undefined;
  return {errors: [{text: 'standard-node-network-module-unavailable:node:' + name,
    notes: [{text: explanation}, {text: compatibility}]}]};
}

export function netBuiltin(source, enabled) {
  if (typeof source !== 'string' || source.length < 1 || source.length > 128 * 1024 ||
      typeof enabled !== 'boolean' || source.split('export function createNodeNetModule(').length !== 2)
    throw new Error('compiler-owned-node-net-source');
  const identity = 'lsf-owned-node-net:node:net';
  const module = source.replace('export function createNodeNetModule(', 'function createNodeNetModule(') +
    '\nimport * as __lsfNetTransport from ' + JSON.stringify(NET_PRIVATE) + ';\n' +
    'import {Buffer as __lsfNetBuffer} from "node:buffer";\n' +
    'const __lsfNetApi = createNodeNetModule(__lsfNetTransport, __lsfNetBuffer, () => __lsfSnapshotActive);\n' +
    'export const Socket = __lsfNetApi.Socket, connect = __lsfNetApi.connect, createConnection = __lsfNetApi.createConnection, createServer = __lsfNetApi.createServer;\n' +
    'export default __lsfNetApi;\n';
  return {
    resolve(args) {
      if (args.path === NET_PRIVATE) {
        if (!enabled || args.namespace !== 'lsf-owned-node-net' || args.importer !== 'node:net')
          return {errors: [{text: 'compiler-private-node-net-transport'}]};
        return {path: NET_PRIVATE, external: true};
      }
      const denied = unavailableModule(args.path);
      if (denied) return denied;
      if (args.path !== 'net' && args.path !== 'node:net') return undefined;
      if (!enabled) return {errors: [{text: 'standard-node-net-requires-exact-stream-runtime-and-declaration',
        notes: [{text: 'Select the maintained activation-import runtime and exact latent:network/streams@0.1.0 world through the normal compiler. The lsf-node-net-tcp-v1 mapping is TCP-only; declarations do not install a provider or grant an endpoint.'},
          {text: compatibility}]}]};
      return {path: 'node:net', namespace: 'lsf-owned-node-net', sideEffects: false};
    },
    load(args) {
      if (!enabled || args.path !== 'node:net' || args.namespace !== 'lsf-owned-node-net')
        throw new Error('compiler-owned-node-net-module-identity');
      return {contents: module, loader: 'js'};
    },
    selection(metafile, output) {
      const row = metafile.outputs[output];
      if (!row || !row.inputs || !Array.isArray(row.imports)) throw new Error('compiler-owned-node-net-output');
      const linked = Object.hasOwn(row.inputs, identity) && row.inputs[identity].bytesInOutput > 0;
      const privateImports = row.imports.filter(value => value.path === NET_PRIVATE);
      if (!linked) {
        if (privateImports.length) throw new Error('compiler-owned-node-net-detached-private-import');
        return [];
      }
      if (!enabled || !Object.hasOwn(metafile.inputs, identity) || privateImports.length !== 1 ||
          privateImports[0].external !== true || privateImports[0].kind !== 'import-statement')
        throw new Error('compiler-owned-node-net-linked-identity');
      return ['node:net'];
    },
  };
}

export { NET_PROFILE, NET_PRIVATE };
