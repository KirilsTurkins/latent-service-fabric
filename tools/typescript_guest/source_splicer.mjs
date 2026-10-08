// Explicit import selections never fall back to another compiler input.
export function selectedSourceSplicer(module) {
  if (module === null || typeof module !== 'object' ||
      typeof module.splicer !== 'function') {
    throw new Error('source-built-splicer-callable-export-required');
  }
  return module.splicer;
}
