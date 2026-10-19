// The pinned generator keeps an idle sync-import waiter in its component state.
// Allocate that intrinsic Promise only while there is an actual import to await.
export function lazySyncImportWaiters(source) {
  const replacements = [
    ['  #syncImportWait = promiseWithResolvers();', '  #syncImportWait = null;'],
    ['    this.#syncImportWait = promiseWithResolvers();\n    existing.resolve();',
      '    this.#syncImportWait = null;\n    if (existing) existing.resolve();'],
    ['  async waitForSyncImportCallEnd() {\n    await this.#syncImportWait.promise;\n  }',
      '  async waitForSyncImportCallEnd() {\n' +
      '    if (!this.#callingAsyncImport) return;\n' +
      '    this.#syncImportWait ??= promiseWithResolvers();\n' +
      '    await this.#syncImportWait.promise;\n  }'],
  ];
  for (const [before, after] of replacements) {
    if (source.split(before).length !== 2) {
      throw new Error('selected-runtime-sync-import-waiter-shape-drift');
    }
    source = source.replace(before, after);
  }
  return source;
}

export function retireGeneratedTaskSlots(source) {
  const replacements = [
    ['  #nextTaskPromise = Promise.resolve(true);', '  #nextTaskPromise = null;'],
    ['      await this.#nextTaskPromise;\n',
      '      await this.#nextTaskPromise;\n' +
      "      if (placeholder.completed) throw new Error('selected-runtime-task-exited-before-slot');\n"],
    ['        placeholder.completed = true;\n      }),',
      '        placeholder.completed = true;\n' +
      '        this.#nextTaskQueue = this.#nextTaskQueue.filter(entry => entry !== placeholder);\n' +
      '        if (this.#nextTaskPromise === placeholder.promise) this.#nextTaskPromise = null;\n' +
      '      }),'],
  ];
  for (const [before, after] of replacements) {
    if (source.split(before).length !== 2) {
      throw new Error('selected-runtime-task-slot-shape-drift');
    }
    source = source.replace(before, after);
  }
  return source;
}

export function applicationRealmImportPromises(source) {
  const anchor = 'const __lsfImports = contentGlobal.__lsfAsyncImportBridge;\n';
  if (source.split(anchor).length !== 2) {
    throw new Error('selected-runtime-import-promise-realm-shape-drift');
  }
  const helper = `
const __lsfApplicationPromise = contentGlobal.Promise;
const __lsfAsyncFunctionPrototype = Object.getPrototypeOf(async function () {});
function __lsfApplicationAsyncFunction(original) {
  const callable = {
    [original.name](...args) {
      return __lsfApplicationPromise.resolve(Reflect.apply(original, this, args));
    }
  }[original.name];
  Object.defineProperty(callable, 'length', {value: original.length});
  return callable;
}
function __lsfNormalizeAsyncMethods(target) {
  if (!target) return;
  for (const key of Reflect.ownKeys(target)) {
    const descriptor = Object.getOwnPropertyDescriptor(target, key);
    if (typeof descriptor.value === 'function' &&
        Object.getPrototypeOf(descriptor.value) === __lsfAsyncFunctionPrototype) {
      Object.defineProperty(target, key,
        {...descriptor, value: __lsfApplicationAsyncFunction(descriptor.value)});
    }
  }
}
function __lsfApplicationBuiltinModule(name, exports) {
  const normalized = {};
  for (const [key, original] of Object.entries(exports)) {
    let value = original;
    if (typeof original === 'function') {
      if (Object.getPrototypeOf(original) === __lsfAsyncFunctionPrototype) {
        value = __lsfApplicationAsyncFunction(original);
      } else {
        __lsfNormalizeAsyncMethods(original);
        __lsfNormalizeAsyncMethods(original.prototype);
      }
    }
    Object.defineProperty(normalized, key,
      {value, enumerable: true, configurable: true, writable: true});
  }
  defineBuiltinModule(name, normalized);
}
`;
  return source.replace(/^defineBuiltinModule\(/gm, '__lsfApplicationBuiltinModule(')
    .replace(anchor, anchor + helper);
}

// The private carrier helper need not create another async Promise: the
// original typed binding already awaits its global task wrapper. Lift the
// carrier at that same existing await, before any original typed result lift.
export function fuseNativeImportAwaits(source, parse) {
  const fail = () => { throw new Error('selected-runtime-native-await-shape-drift'); };
  let tree;
  try { tree = parse(source, {ecmaVersion: 'latest', sourceType: 'module'}); }
  catch { fail(); }
  const entries = [];
  function walk(node, parents = []) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) { for (const child of node) walk(child, parents); return; }
    if (typeof node.type !== 'string') return;
    entries.push({node, parents});
    for (const value of Object.values(node)) {
      if (value && typeof value === 'object') walk(value, [...parents, node]);
    }
  }
  walk(tree);
  const helpers = entries.filter(({node}) => node.type === 'VariableDeclarator' &&
    node.id.type === 'Identifier' && node.id.name === '__lsfAwaitImport');
  if (!helpers.length) {
    if (source.includes('__lsfAwaitImport')) fail();
    return source;
  }
  if (entries.filter(({node}) => node.type === 'Identifier' && node.name === '__lsfAwaitImport').length !== helpers.length * 2) fail();
  const anchor = 'const __lsfImports = contentGlobal.__lsfAsyncImportBridge;';
  if (source.split(anchor).length !== 2) fail();
  const identifier = (node, name) => node?.type === 'Identifier' && node.name === name;
  const member = (node, name) => node?.type === 'MemberExpression' && !node.computed &&
    identifier(node.object, '__lsfImports') && identifier(node.property, name);
  const isFunction = node => ['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'].includes(node.type);
  const edits = [];
  for (const {node: helper, parents} of helpers) {
    const fn = [...parents].reverse().find(isFunction);
    const arrow = helper.init;
    if (!fn?.async || fn.body.type !== 'BlockStatement' ||
        arrow?.type !== 'ArrowFunctionExpression' || !arrow.async || arrow.generator ||
        arrow.params.length !== 1 || arrow.params[0].type !== 'RestElement' ||
        !identifier(arrow.params[0].argument, 'lowered') ||
        arrow.body.type !== 'CallExpression' || !member(arrow.body.callee, 'lift') ||
        arrow.body.arguments.length !== 1 || arrow.body.arguments[0].type !== 'AwaitExpression') fail();
    const native = arrow.body.arguments[0].argument;
    if (native.type !== 'CallExpression' || native.callee.type !== 'Identifier' ||
        native.arguments.length !== 2 || native.arguments[0].type !== 'BinaryExpression' ||
        native.arguments[0].operator !== '|' || !identifier(native.arguments[0].left, '__lsfImportId') ||
        native.arguments[0].right.type !== 'Literal' || native.arguments[0].right.value !== 0 ||
        native.arguments[1].type !== 'SpreadElement' || !identifier(native.arguments[1].argument, 'lowered')) fail();
    const inside = entries.filter(({node}) => node.start >= fn.start && node.end <= fn.end);
    const references = inside.filter(({node}) => identifier(node, '__lsfAwaitImport'));
    const calls = inside.filter(({node}) => node.type === 'CallExpression' && identifier(node.callee, '__lsfAwaitImport'));
    if (references.length !== 2 || calls.length !== 1) fail();
    const call = calls[0];
    const callback = call.parents.at(-1);
    const property = call.parents.at(-2);
    const object = call.parents.at(-3);
    const wrapper = call.parents.at(-4);
    const awaited = call.parents.at(-5);
    if (callback.type !== 'ArrowFunctionExpression' || callback.async || callback.body !== call.node ||
        property.type !== 'Property' || property.computed || !identifier(property.key, 'fn') || property.value !== callback ||
        object.type !== 'ObjectExpression' || object.properties.length !== 3 ||
        object.properties.some(p => p.type !== 'Property' || p.computed || p.key.type !== 'Identifier') ||
        object.properties.map(p => p.key.name).join(',') !== 'taskID,componentIdx,fn' ||
        wrapper.type !== 'CallExpression' || wrapper.callee.type !== 'Identifier' ||
        !/withGlobalCurrentTaskMeta.*Async/i.test(wrapper.callee.name) ||
        wrapper.arguments.length !== 1 || wrapper.arguments[0] !== object ||
        awaited.type !== 'AwaitExpression' || awaited.argument !== wrapper) fail();
    const reservations = inside.filter(({node}) => node.type === 'VariableDeclarator' &&
      identifier(node.id, '__lsfImportId') && node.init?.type === 'CallExpression' && member(node.init.callee, 'reserve'));
    const finalizers = inside.filter(({node}) => node.type === 'TryStatement' && node.finalizer &&
      node.block.start <= awaited.start && node.block.end >= awaited.end && node.finalizer.body.length === 1 &&
      node.finalizer.body[0].type === 'ExpressionStatement' && node.finalizer.body[0].expression.type === 'CallExpression' &&
      member(node.finalizer.body[0].expression.callee, 'finish') &&
      node.finalizer.body[0].expression.arguments.length === 1 &&
      identifier(node.finalizer.body[0].expression.arguments[0], '__lsfImportId'));
    if (reservations.length !== 1 || finalizers.length !== 1) fail();
    edits.push({start: arrow.start, end: arrow.end,
      text: `(...lowered) => ${source.slice(native.start, native.end)}`});
    edits.push({start: awaited.start, end: awaited.end,
      text: `__lsfImports.lift(${source.slice(awaited.start, awaited.end)})`});
  }
  edits.sort((a, b) => b.start - a.start);
  let previous = source.length;
  for (const edit of edits) {
    if (edit.end > previous) fail();
    source = source.slice(0, edit.start) + edit.text + source.slice(edit.end);
    previous = edit.start;
  }
  parse(source, {ecmaVersion: 'latest', sourceType: 'module'});
  return source;
}
