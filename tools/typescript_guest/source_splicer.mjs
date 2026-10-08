// Explicit import selections never fall back to another compiler input.
export function selectedSourceSplicer(module) {
  if (module === null || typeof module !== 'object' ||
      module.splicer === null || typeof module.splicer !== 'object' ||
      typeof module.splicer.spliceBindings !== 'function' ||
      typeof module.splicer.stubWasi !== 'function') {
    throw new Error('source-built-splicer-callable-export-required');
  }
  return module.splicer;
}
