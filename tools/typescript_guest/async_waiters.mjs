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

// Preserve public asynchronous entry while avoiding a synthetic await-null
// reaction only for the actual private Task that is first in an idle queue.
export function directIdleTaskSlots(source) {
  const replacements = [
    ['isSync() { return !this.isAsync(); }',
      'isSync() { return !this.isAsync(); }\n  hasExitedBeforeEntry() { return this.#exited; }'],
    ["      await this.#nextTaskPromise;\n      if (placeholder.completed) throw new Error('selected-runtime-task-exited-before-slot');",
      '      if (this.#nextTaskPromise !== null || !(task instanceof AsyncTask) ||\n' +
      '          this.#nextTaskQueue.find(entry => !entry.completed) !== placeholder) {\n' +
      '        await this.#nextTaskPromise;\n' +
      '      }\n' +
      '      if (placeholder.completed || task instanceof AsyncTask && task.hasExitedBeforeEntry()) {\n' +
      '        placeholder.completed = true;\n' +
      '        this.#nextTaskQueue = this.#nextTaskQueue.filter(entry => entry !== placeholder);\n' +
      '        if (this.#nextTaskPromise === placeholder.promise) this.#nextTaskPromise = null;\n' +
      "        throw new Error('selected-runtime-task-exited-before-slot');\n" +
      '      }'],
    ['    await cstate.nextTaskExecutionSlot({ task: this });',
      '    await cstate.nextTaskExecutionSlot({ task: this });\n' +
      "    if (this.#exited) throw new Error('selected-runtime-task-exited-before-entry');"],
  ];
  if (source.split('class AsyncTask {').length !== 2 ||
      source.split('  #exited = false;').length !== 2 ||
      source.split('    this.#exited = true;').length !== 2 ||
      source.includes('hasExitedBeforeEntry')) {
    throw new Error('selected-runtime-idle-task-shape-drift');
  }
  for (const [before, after] of replacements) {
    if (source.split(before).length !== 2) {
      throw new Error('selected-runtime-idle-task-shape-drift');
    }
    source = source.replace(before, after);
  }
  return source;
}

// The private carrier helper need not create another async Promise: the
// original typed binding already awaits its global task wrapper. Lift the
// carrier at that same existing await, before any original typed result lift.
export function fuseNativeImportAwaits(source, parse) {
  const fail = () => { throw new Error('selected-runtime-native-await-shape-drift'); };
  let tree;
  const comments = [];
  try { tree = parse(source, {ecmaVersion: 'latest', sourceType: 'module', onComment: comments}); }
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
        wrapper.callee.name !== '_withGlobalCurrentTaskMetaAsync' ||
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
    // The compiler identifies ErrHandling, then this closed AST check matches
    // the original FunctionBindgen Return instruction. Evaluate the complete
    // return/error object BEFORE transferring ownership; arbitrary exceptions
    // during lifting remain unmarked and quarantine the native record.
    const markers = comments.filter(comment => comment.start >= fn.start && comment.end <= fn.end &&
      comment.value.trim().startsWith('lsf-owned-result-transfer:'));
    if (markers.length !== 1) fail();
    const mode = markers[0].value.trim();
    const body = finalizers[0].node.block.body;
    const text = node => source.slice(node.start, node.end);
    const taskCall = (node, name) => node?.type === 'ExpressionStatement' &&
      node.expression.type === 'CallExpression' && node.expression.callee.type === 'MemberExpression' &&
      !node.expression.callee.computed && identifier(node.expression.callee.object, 'task') &&
      identifier(node.expression.callee.property, name) ? node.expression : null;
    const resolve = taskCall(body.at(-3), 'resolve');
    const exit = taskCall(body.at(-2), 'exit');
    const returned = body.at(-1);
    const transfer = node => `__lsfImports.delivered(__lsfImportId, ${text(node)})`;
    if (mode === 'lsf-owned-result-transfer:wit-result') {
      const declared = body.at(-5);
      const resolved = taskCall(body.at(-4), 'resolve');
      const exited = taskCall(body.at(-3), 'exit');
      const branch = body.at(-2);
      const value = node => node?.type === 'MemberExpression' && !node.computed &&
        identifier(node.object, 'retCopy') && identifier(node.property, 'val');
      const test = branch?.test;
      const tag = test?.right;
      const kind = test?.left;
      const thrown = branch?.consequent?.body?.[0];
      if (declared?.type !== 'VariableDeclaration' || declared.kind !== 'const' ||
          declared.declarations.length !== 1 || !identifier(declared.declarations[0].id, 'retCopy') ||
          !resolved || resolved.arguments.length !== 1 || resolved.arguments[0].type !== 'ArrayExpression' ||
          resolved.arguments[0].elements.length !== 1 || !value(resolved.arguments[0].elements[0]) ||
          !exited || exited.arguments.length !== 0 || returned.type !== 'ReturnStatement' || !value(returned.argument) ||
          branch?.type !== 'IfStatement' || branch.alternate || branch.consequent.type !== 'BlockStatement' ||
          branch.consequent.body.length !== 1 || test?.type !== 'LogicalExpression' || test.operator !== '&&' ||
          kind?.type !== 'BinaryExpression' || kind.operator !== '===' || kind.left.type !== 'UnaryExpression' ||
          kind.left.operator !== 'typeof' || !identifier(kind.left.argument, 'retCopy') ||
          kind.right.type !== 'Literal' || kind.right.value !== 'object' ||
          tag?.type !== 'BinaryExpression' || tag.operator !== '===' || tag.left.type !== 'MemberExpression' ||
          tag.left.computed || !identifier(tag.left.object, 'retCopy') || !identifier(tag.left.property, 'tag') ||
          tag.right.type !== 'Literal' || tag.right.value !== 'err' || thrown?.type !== 'ThrowStatement' ||
          thrown.argument.type !== 'NewExpression' || !identifier(thrown.argument.callee, 'ComponentError') ||
          thrown.argument.arguments.length !== 1 || !value(thrown.argument.arguments[0])) fail();
      edits.push({start: thrown.argument.start, end: thrown.argument.end, text: transfer(thrown.argument)});
      edits.push({start: returned.argument.start, end: returned.argument.end, text: transfer(returned.argument)});
    } else if (mode === 'lsf-owned-result-transfer:value') {
      if (returned?.type === 'ReturnStatement' && returned.argument) {
        if (!resolve || resolve.arguments.length !== 1 || resolve.arguments[0].type !== 'ArrayExpression' ||
            resolve.arguments[0].elements.length !== 1 || !resolve.arguments[0].elements[0] ||
            text(resolve.arguments[0].elements[0]) !== text(returned.argument) || !exit || exit.arguments.length !== 0) fail();
        edits.push({start: returned.argument.start, end: returned.argument.end, text: transfer(returned.argument)});
      } else {
        const resolved = taskCall(body.at(-2), 'resolve');
        const exited = taskCall(returned, 'exit');
        if (!resolved || resolved.arguments.length !== 1 || resolved.arguments[0].type !== 'ArrayExpression' ||
            resolved.arguments[0].elements.length !== 1 || !identifier(resolved.arguments[0].elements[0], 'ret') ||
            !exited || exited.arguments.length !== 0) fail();
        edits.push({start: returned.end, end: returned.end,
          text: '\n__lsfImports.delivered(__lsfImportId, undefined);'});
      }
    } else fail();
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

// Exact generated task metadata wrapper; preserve all contention and cleanup.
const nativeTaskMetaPreimage = `async function _withGlobalCurrentTaskMetaAsync(args) {
  _debugLog('[_withGlobalCurrentTaskMetaAsync()] args', args);
  if (!args) { throw new TypeError('args missing'); }
  if (args.taskID === undefined) { throw new TypeError('missing task ID'); }
  if (args.componentIdx === undefined) { throw new TypeError('missing component idx'); }
  if (!args.fn) { throw new TypeError('missing fn'); }
  const { taskID, componentIdx, fn } = args;
\x20\x20
  // If there is already an async task executing, we must wait for it
  // to complete before we can can run the closure we were given
  //
  let current = CURRENT_TASK_META[componentIdx];
  let cstate;
  if (current && current.taskID !== taskID) {
    cstate = getOrCreateAsyncState(componentIdx);
    while (current && current.taskID !== taskID) {
      const { promise, resolve } = Promise.withResolvers();
      cstate.onNextExclusiveRelease(resolve);
      await promise;
      current = CURRENT_TASK_META[componentIdx];
    }
\x20\x20\x20\x20
    // Since we've just waited for the component to not be locked, re-lock
    // exclusivity so we can run the fn below (likely a callee/callback)
    cstate.exclusiveLock();
  }
\x20\x20
  try {
    CURRENT_TASK_META[componentIdx] = { taskID, componentIdx };
    return await fn();
  } catch (err) {
    _debugLog("error while executing async callee/callback", {
      ...args,
      err,
    });
    throw err;
  } finally {
    CURRENT_TASK_META[componentIdx] = null;
  }
}`;

export function inlineNativeTaskMeta(source, parse) {
  const fail = () => { throw new Error('selected-runtime-native-task-meta-shape-drift'); };
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
  const identifier = (node, name) => node?.type === 'Identifier' && node.name === name;
  const enclosingFunction = parents => [...parents].reverse().find(node=>node.type==='FunctionDeclaration');
  const helpers = entries.filter(({node})=>node.type==='VariableDeclarator' && identifier(node.id,'__lsfAwaitImport'));
  if (!helpers.length) {
    if (source.includes('__lsfAwaitImport')) fail();
    return source;
  }
  if (helpers.length>256) fail();
  const nativeFunctions = helpers.map(({node,parents})=> {
    const outer=enclosingFunction(parents);
    if (!outer?.async || node.init?.type!=='ArrowFunctionExpression' || node.init.async) fail();
    return outer;
  });
  if (new Set(nativeFunctions).size!==helpers.length) fail();
  const wrappers = entries.filter(({node}) => node.type === 'FunctionDeclaration' &&
    identifier(node.id, '_withGlobalCurrentTaskMetaAsync'));
  if (wrappers.length !== 1 || source.slice(wrappers[0].node.start, wrappers[0].node.end) !== nativeTaskMetaPreimage) fail();
  const allCalls = entries.filter(({node}) => node.type === 'CallExpression' && identifier(node.callee, '_withGlobalCurrentTaskMetaAsync'));
  // Framework callbacks and application exports keep their original wrappers.
  const calls = allCalls.filter(({parents})=>nativeFunctions.includes(enclosingFunction(parents)));
  if (calls.length!==helpers.length || nativeFunctions.some(outer=>
      calls.filter(({parents})=>enclosingFunction(parents)===outer).length!==1) ||
      entries.filter(({node})=>identifier(node,'_withGlobalCurrentTaskMetaAsync')).length!==allCalls.length+1) fail();
  const body = nativeTaskMetaPreimage.slice(nativeTaskMetaPreimage.indexOf('{')+1, -1)
    .replace('return await fn();', '__lsfNativeCarrier = await fn();');
  const locals = new Set(['args','taskID','componentIdx','fn','current','cstate','err','promise','resolve','__lsfNativeCarrier']);
  const edits = [];
  for (const {node:call,parents} of calls) {
    const awaited=parents.at(-1),lift=parents.at(-2),assignment=parents.at(-3),statement=parents.at(-4);
    const outer=enclosingFunction(parents);
    const object=call.arguments[0];
    if (!outer?.async || call.arguments.length!==1 || object?.type!=='ObjectExpression' ||
        object.properties.length!==3 || object.properties.some(p=>p.type!=='Property'||p.computed||p.key.type!=='Identifier') ||
        object.properties.map(p=>p.key.name).join(',')!=='taskID,componentIdx,fn' ||
        awaited?.type!=='AwaitExpression' || awaited.argument!==call ||
        lift?.type!=='CallExpression' || lift.arguments.length!==1 || lift.arguments[0]!==awaited ||
        lift.callee.type!=='MemberExpression' || lift.callee.computed ||
        !identifier(lift.callee.object,'__lsfImports') || !identifier(lift.callee.property,'lift') ||
        assignment?.type!=='AssignmentExpression' || assignment.operator!=='=' || !identifier(assignment.left,'ret') || assignment.right!==lift ||
        statement?.type!=='ExpressionStatement' || statement.expression!==assignment) fail();
    for (const [index,name] of [[0,'id'],[1,'componentIdx']]) {
      const value=object.properties[index].value;
      if (value.type!=='CallExpression' || value.arguments.length || value.callee.type!=='MemberExpression' ||
          value.callee.computed || !identifier(value.callee.object,'task') || !identifier(value.callee.property,name)) fail();
    }
    const fn=object.properties[2].value;
    if (fn.type!=='ArrowFunctionExpression' || fn.async || fn.params.length ||
        fn.body.type!=='CallExpression' || !identifier(fn.body.callee,'__lsfAwaitImport') ||
        entries.some(({node})=>node.start>=fn.body.start && node.end<=fn.body.end && node.type==='Identifier' && locals.has(node.name))) fail();
    const helper=entries.filter(({node})=>node.start>=outer.start && node.end<=outer.end &&
      node.type==='VariableDeclarator' && identifier(node.id,'__lsfAwaitImport'));
    if (helper.length!==1 || helper[0].node.init?.type!=='ArrowFunctionExpression' || helper[0].node.init.async) fail();
    edits.push({start:statement.start,end:statement.end,text:'{\n  let __lsfNativeCarrier;\n  {\n    const args = '+
      source.slice(object.start,object.end)+';\n'+body+'\n  }\n  ret = __lsfImports.lift(__lsfNativeCarrier);\n}'});
  }
  edits.sort((a,b)=>b.start-a.start);
  let previous=source.length;
  for (const edit of edits) {
    if (edit.end>previous) fail();
    source=source.slice(0,edit.start)+edit.text+source.slice(edit.end);previous=edit.start;
  }
  parse(source,{ecmaVersion:'latest',sourceType:'module'});
  return source;
}

// A selected native import already has a real admitted C++ Task/Record and
// canonical subtask. Its generated synchronous-ABI JCO Task is a surrogate:
// retaining that task's execution slot until its Promise exits serializes all
// sibling native imports. Project only the fully recognized surrogate away.
// Actual typed lowering/lifting and the original native finally remain intact.
export function nativeCarrierImports(source, parse) {
  const fail = () => { throw Error('selected-runtime-native-carrier-shape-drift'); };
  // Retain the existing exact native-helper/metadata-wrapper checks. This is
  // validation only: the legacy inlined wrapper is never emitted here.
  inlineNativeTaskMeta(source, parse);
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
  const identifier = (node, name) => node?.type === 'Identifier' && node.name === name;
  const helpers = entries.filter(({node}) => node.type === 'VariableDeclarator' &&
    identifier(node.id, '__lsfAwaitImport'));
  if (!helpers.length) return source;
  if (helpers.length > 256) fail();
  const bridges = tree.body.filter(node => node.type === 'VariableDeclaration' && node.kind === 'const' &&
    node.declarations.length === 1 && identifier(node.declarations[0].id, '__lsfImports'));
  const bridge = bridges[0]?.declarations[0]?.init;
  if (bridges.length !== 1 || bridge?.type !== 'MemberExpression' || bridge.computed ||
      !identifier(bridge.object, 'contentGlobal') || !identifier(bridge.property, '__lsfAsyncImportBridge')) fail();
  const text = node => source.slice(node.start, node.end);
  const normalized = node => JSON.stringify(node, (key, value) =>
    ['start', 'end', 'loc', 'raw'].includes(key) ? undefined : value);
  const same = (node, expected) => {
    const body = parse(`async function __lsfPattern() { ${expected} }`,
      {ecmaVersion: 'latest', sourceType: 'module'}).body[0].body.body;
    return body.length === 1 && normalized(node) === normalized(body[0]);
  };
  const forbidden = new Set(['getCurrentTask', 'getCurrentTaskMeta', '_getGlobalCurrentTaskMeta',
    '_clearCurrentTask', 'clearCurrentTask', 'createNewCurrentTask', 'getOrCreateAsyncState',
    'CURRENT_TASK_META', 'ASYNC_CURRENT_TASK_IDS', 'ASYNC_CURRENT_COMPONENT_IDXS',
    'ASYNC_TASKS_BY_COMPONENT_IDX', 'AsyncTask', 'AsyncSubtask', 'borrowedHandles',
    'getParentSubtask', 'createSubtask', 'getLatestSubtask', 'getSubtaskByWaitableRep',
    'getPostReturnFn', 'setPostReturnFn', 'postReturnFn']);
  // Follow statically named typed helpers as well as their .bind/.call uses.
  // A typed helper that still needs JCO task/borrow/post-return state is not a
  // candidate for this projection, even when the outer wrapper looks familiar.
  const functions = new Map();
  const aliases = new Map();
  const classes = new Map(tree.body.filter(node => node.type === 'ClassDeclaration' && node.id)
    .map(node => [node.id.name, node]));
  for (const node of tree.body) {
    if (node.type !== 'VariableDeclaration') continue;
    for (const item of node.declarations) {
      if (item.id.type !== 'Identifier' || !item.init) continue;
      if (aliases.has(item.id.name)) fail();
      aliases.set(item.id.name, item.init);
    }
  }
  for (const {node} of entries) {
    if (node.type === 'FunctionDeclaration' && node.id) {
      const values = functions.get(node.id.name) ?? [];
      values.push(node); functions.set(node.id.name, values);
    } else if (node.type === 'VariableDeclarator' && node.id.type === 'Identifier' &&
        ['FunctionExpression', 'ArrowFunctionExpression'].includes(node.init?.type)) {
      const values = functions.get(node.id.name) ?? [];
      values.push(node.init); functions.set(node.id.name, values);
    } else if (node.type === 'ClassDeclaration' && node.id) {
      const constructor = node.body.body.find(item => item.kind === 'constructor');
      if (constructor) {
        const values = functions.get(node.id.name) ?? [];
        values.push(constructor.value); functions.set(node.id.name, values);
      }
    }
  }
  const edits = [];
  for (const {parents} of helpers) {
    const fn = [...parents].reverse().find(node => node.type === 'FunctionDeclaration');
    if (!fn?.async) fail();
    const inside = entries.filter(({node}) => node.start >= fn.start && node.end <= fn.end);
    const outer = fn.body.body.find(node => node.type === 'TryStatement' && node.finalizer);
    if (!outer) fail();
    const body = outer.block.body;
    const declarations = body.filter(node => node.type === 'VariableDeclaration' &&
      node.declarations.some(item => item.id.type === 'ArrayPattern' &&
        item.id.elements.some(value => identifier(value, 'task'))));
    if (declarations.length !== 1) fail();
    const declaration = declarations[0], index = body.indexOf(declaration);
    const settings = declaration.declarations[0]?.init?.arguments?.[0];
    const component = settings?.properties?.find(item => identifier(item.key, 'componentIdx'))?.value;
    const errorMode = settings?.properties?.find(item => identifier(item.key, 'errHandling'))?.value;
    if (component?.type !== 'Literal' || !Number.isSafeInteger(component.value) || component.value < 0 ||
        errorMode?.type !== 'Literal' || !['none', 'throw-result-err'].includes(errorMode.value) ||
        !same(declaration, `const [task, _wasm_call_currentTaskID] = createNewCurrentTask({
          componentIdx: ${component.value}, isAsync: false, isManualAsync: true,
          entryFnName: '__lsfAwaitImport', getCallbackFn: () => null, callbackFnName: null,
          errHandling: ${JSON.stringify(errorMode.value)}, callingWasmExport: true });`) ||
        !same(body[index + 1], 'const started = await task.enter();') ||
        !same(body[index + 2], `if (!started) {
          _debugLog('[Instruction::AsyncTaskReturn] failed to enter task', {
            taskID: task.id(), subtaskID: currentSubtask?.id() });
          throw new Error('failed to enter task'); }`) ||
        !same(body[index + 3], `if (null !== null) {
          task.setReturnMemoryIdx(null); task.setReturnMemory(() => null()); }`)) fail();
    const localEdits = [{start: declaration.start, end: body[index + 3].end, text: ''}];
    const carriers = body.filter(node => node.type === 'TryStatement' && node.handler && !node.finalizer);
    if (carriers.length !== 1) fail();
    const carrier = carriers[0];
    if (!identifier(carrier.handler.param, 'err') || carrier.block.body.length !== 1 ||
        normalized(carrier.handler.body) !== normalized(parse(`async function __lsfPattern() {
          task.setErrored(err); task.reject(err); task.exit(); return task.completionPromise();
        }`, {ecmaVersion: 'latest', sourceType: 'module'}).body[0].body)) fail();
    const assignment = carrier.block.body[0]?.expression;
    const awaitWrapper = assignment?.right?.arguments?.[0];
    const wrapper = awaitWrapper?.argument;
    const native = wrapper?.arguments?.[0]?.properties?.[2]?.value?.body;
    if (assignment?.type !== 'AssignmentExpression' || assignment.operator !== '=' ||
        !identifier(assignment.left, 'ret') || assignment.right.type !== 'CallExpression' ||
        text(assignment.right.callee) !== '__lsfImports.lift' ||
        awaitWrapper?.type !== 'AwaitExpression' || wrapper?.type !== 'CallExpression' ||
        !identifier(wrapper.callee, '_withGlobalCurrentTaskMetaAsync') ||
        native?.type !== 'CallExpression' || !identifier(native.callee, '__lsfAwaitImport')) fail();
    localEdits.push({start: carrier.start, end: carrier.end,
      text: `ret = __lsfImports.lift(await ${text(native)});`});
    const taskCall = (node, name) => node?.type === 'ExpressionStatement' &&
      node.expression.type === 'CallExpression' && node.expression.callee.type === 'MemberExpression' &&
      !node.expression.callee.computed && identifier(node.expression.callee.object, 'task') &&
      identifier(node.expression.callee.property, name) ? node.expression : null;
    const resolves = body.filter(node => taskCall(node, 'resolve'));
    if (resolves.length !== 1) fail();
    const resolved = resolves[0], resolve = taskCall(resolved, 'resolve');
    const exited = body[body.indexOf(resolved) + 1], exit = taskCall(exited, 'exit');
    if (!exit || exit.arguments.length || resolve.arguments.length !== 1 ||
        resolve.arguments[0].type !== 'ArrayExpression' || resolve.arguments[0].elements.length !== 1) fail();
    // Preserve evaluation of the original typed result expression and array.
    // Only the unreachable surrogate completion observer is omitted.
    localEdits.push({start: resolved.start, end: resolved.end, text: `void ${text(resolve.arguments[0])};`});
    localEdits.push({start: exited.start, end: exited.end, text: ''});
    const removed = node => localEdits.some(edit => node.start >= edit.start && node.end <= edit.end);
    const remaining = inside.filter(({node}) => !removed(node));
    for (const {node} of remaining) {
      if (node.type === 'Identifier' && (forbidden.has(node.name) ||
          ['task', '_wasm_call_currentTaskID', 'started'].includes(node.name))) fail();
    }
    const pending = [...remaining], seen = new Set();
    while (pending.length) {
      const {node} = pending.pop();
      if (node.type === 'Identifier' && forbidden.has(node.name)) fail();
      if (node.type === 'MemberExpression' && node.computed && node.property.type === 'Literal' &&
          typeof node.property.value === 'string' && forbidden.has(node.property.value)) fail();
      // `postReturn: false` is only a generated log label. A callable or
      // borrowed-handle duty with that name is never silently projected away.
      if (node.type === 'Identifier' && node.name === 'postReturn') {
        const property = entries.find(entry => entry.node === node)?.parents.at(-1);
        if (property?.type !== 'Property' || property.key !== node ||
            property.value.type !== 'Literal' || property.value.value !== false) fail();
      }
      if (node.type === 'Identifier' && aliases.has(node.name)) {
        const target = aliases.get(node.name);
        if (!seen.has(target)) {
          if (seen.size >= 256) fail();
          seen.add(target);
          pending.push(...entries.filter(({node: child}) => child.start >= target.start && child.end <= target.end));
        }
      }
      let callee;
      if (['CallExpression', 'NewExpression'].includes(node.type)) {
        callee = node.callee;
        if (callee.type === 'MemberExpression' && !callee.computed &&
            ['bind', 'call', 'apply'].includes(callee.property.name)) callee = callee.object;
      }
      // Also inspect a known typed-table method reached through a maintained
      // top-level instance (including a bound method alias).
      if (callee?.type === 'MemberExpression' && !callee.computed &&
          callee.object.type === 'Identifier') {
        const instance = aliases.get(callee.object.name);
        const owner = instance?.type === 'NewExpression' && instance.callee.type === 'Identifier'
          ? classes.get(instance.callee.name) : undefined;
        if (owner) {
          const methods = owner.body.body.filter(method => !method.computed &&
            method.key.type === 'Identifier' && method.key.name === callee.property.name);
          if (methods.length !== 1 || methods[0].kind !== 'method') fail();
          const target = methods[0].value;
          if (!seen.has(target)) {
            if (seen.size >= 256) fail();
            seen.add(target);
            pending.push(...entries.filter(({node: child}) => child.start >= target.start && child.end <= target.end));
          }
        }
      }
      // This compiler-local helper was already checked against its exact
      // original native trampoline, and is local to this selected wrapper.
      if (callee?.type !== 'Identifier' || callee.name === '__lsfAwaitImport' ||
          !functions.has(callee.name)) continue;
      const targets = functions.get(callee.name);
      if (targets.length !== 1) fail();
      const target = targets[0];
      if (seen.has(target)) continue;
      if (seen.size >= 256) fail();
      seen.add(target);
      pending.push(...entries.filter(({node: child}) => child.start >= target.start && child.end <= target.end));
    }
    edits.push(...localEdits);
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
