// ComponentizeJS 0.22 emits imported opaque-resource lifts but omits their
// JavaScript classes. Complete that exact pinned shape with deterministic
// canonical drops. Guest GC finalizers must never issue host effects.
export function explicitResourceOwners(source) {
  const pattern = /const (finalizationRegistry_import\$([A-Za-z0-9_$]+)\$([A-Za-z0-9_]+)) = new FinalizationRegistry\(\(handle\) => \{\s*(\$resource_import\$[A-Za-z0-9_$]+)\(handle\);\s*\}\);/g;
  const resources = [...source.matchAll(pattern)];
  if (!resources.length) {
    if (source.includes('new FinalizationRegistry')) throw new Error('resource-finalizer-shape-drift');
    return source;
  }
  const anchor = "const symbolRscHandle = Symbol('handle');";
  if (source.split(anchor).length !== 2) throw new Error('resource-handle-symbol-drift');
  const classes = resources.map(([, , namespace, resource, drop]) => {
    const type = resource.replace(/(^|_)([a-z])/g, (_, __, c) => c.toUpperCase());
    const name = 'import_' + namespace + '$' + type;
    if (drop !== '$resource_import$' + namespace + '$drop$' + resource ||
        source.includes('class ' + name) || source.includes('function ' + name)) {
      throw new Error('opaque-resource-class-shape-drift');
    }
    return `class ${name} {
  constructor() { throw new TypeError('host-resource-cannot-be-constructed'); }
  [symbolDispose]() {
    const handle = this[symbolRscHandle];
    if (handle === undefined) return;
    this[symbolRscHandle] = undefined;
    ${drop}(handle);
  }
}`;
  });
  source = source.replace(pattern, (_, registry) =>
    'const ' + registry + ' = { register() {}, unregister() {} };');
  if (source.includes('new FinalizationRegistry')) throw new Error('unreviewed-resource-finalizer');
  return source.replace(anchor, anchor + '\n' + classes.join('\n'));
}
