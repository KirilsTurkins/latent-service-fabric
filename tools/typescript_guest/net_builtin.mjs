import { NET_PROFILE, NET_PRIVATE } from './node_net_bindings.mjs';

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
      if (args.path !== 'net' && args.path !== 'node:net') return undefined;
      if (!enabled) return {errors: [{text: 'standard-node-net-requires-exact-stream-runtime-and-declaration'}]};
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
