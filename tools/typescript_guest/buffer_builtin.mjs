// Compiler-private resolver. No application path, package identity or authority
// can select another implementation. Both spellings share one esbuild identity.
export const BUFFER_PROFILE = 'lsf-node-buffer-v1';
export const BUFFER_MODULE = 'node:buffer';
export function bufferBuiltin(source) {
  if (typeof source !== 'string' || !source.length || source.length > 128 * 1024)
    throw new Error('compiler-owned-buffer-source-bound');
  let selected = false;
  return {
    resolve(path) {
      if (path !== 'buffer' && path !== BUFFER_MODULE) return undefined;
      selected = true;
      return {path: BUFFER_MODULE, namespace: 'lsf-owned-node-buffer'};
    },
    load(args) {
      if (args.path !== BUFFER_MODULE || args.namespace !== 'lsf-owned-node-buffer')
        throw new Error('compiler-owned-buffer-module-identity');
      return {contents: source, loader: 'js'};
    },
    selection() { return selected ? [BUFFER_MODULE] : []; },
  };
}
