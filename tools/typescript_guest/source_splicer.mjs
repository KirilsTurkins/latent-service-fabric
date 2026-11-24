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

// Closed preimage of the selected generator's private async metadata helper.
const exportTaskMetaPreimage = `async function _withGlobalCurrentTaskMetaAsync(args) {
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

// The Socket binding also verifies this whole compiler-owned block before
// placing its close drain immediately after the application call.
export function inlinedExportTaskBlock(argumentsSource) {
  const body = exportTaskMetaPreimage.slice(exportTaskMetaPreimage.indexOf('{') + 1, -1)
    .replace('return await fn();', 'ret = await fn();');
  return '{\n  const __lsfExportTaskMetaArgs = ' + argumentsSource +
    ';\n  {\n    const args = __lsfExportTaskMetaArgs;\n' + body + '\n  }\n}';
}

// The generated export already awaits its application result. Execute the
// private metadata wrapper in that frame instead of owning a second async
// Promise and its adoption reactions while the application's graph is live.
// Task entry, contention, typed lifting/lowering and terminal cleanup remain
// in their original locations. Framework callbacks keep their own wrappers.
export function inlineExportTaskMeta(source, parse) {
  const fail = () => { throw new Error('selected-runtime-export-task-meta-shape-drift'); };
  let tree;
  try { tree = parse(source, {ecmaVersion: 'latest', sourceType: 'module'}); }
  catch { fail(); }
  const entries = [];
  const isFunction = node => ['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'].includes(node?.type);
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
  const id = (node, name) => node?.type === 'Identifier' && node.name === name;
  const member = (node, object, name) => node?.type === 'MemberExpression' && !node.computed && !node.optional &&
    id(node.object, object) && id(node.property, name);
  const taskCall = (node, name, count) => node?.type === 'CallExpression' && !node.optional &&
    member(node.callee, 'task', name) && node.arguments.length === count;
  const enclosing = parents => [...parents].reverse().find(isFunction);
  const exports = entries.filter(({node, parents}) => node.type === 'FunctionDeclaration' &&
    node.id?.name.startsWith('export_') && !parents.some(isFunction)).map(({node}) => node);
  if (!exports.length) return source;
  if (exports.length > 256) fail();
  const allCalls = entries.filter(({node}) => node.type === 'CallExpression' && id(node.callee, '_withGlobalCurrentTaskMetaAsync'));
  const calls = allCalls.filter(({parents}) => exports.includes(enclosing(parents)));
  if (!calls.length) return source; // Synchronous/non-selected bindings are untouched.
  const wrappers = entries.filter(({node}) => node.type === 'FunctionDeclaration' && id(node.id, '_withGlobalCurrentTaskMetaAsync'));
  if (wrappers.length !== 1 || source.slice(wrappers[0].node.start, wrappers[0].node.end) !== exportTaskMetaPreimage ||
      entries.filter(({node}) => id(node, '_withGlobalCurrentTaskMetaAsync')).length !== allCalls.length + 1) fail();
  const edits = [];
  for (const {node: call, parents} of calls) {
    const outer = enclosing(parents), awaited = parents.at(-1), assignment = parents.at(-2), statement = parents.at(-3);
    const block = parents.at(-4), guarded = parents.at(-5), object = call.arguments[0];
    if (!outer.async || outer.generator || calls.filter(row => enclosing(row.parents) === outer).length !== 1 ||
        call.optional || call.arguments.length !== 1 || object?.type !== 'ObjectExpression' ||
        object.properties.length !== 3 || object.properties.some(p => p.type !== 'Property' || p.computed ||
          p.kind !== 'init' || p.method || p.shorthand || p.key.type !== 'Identifier') ||
        object.properties.map(p => p.key.name).join(',') !== 'componentIdx,taskID,fn' ||
        !taskCall(object.properties[0].value, 'componentIdx', 0) || !taskCall(object.properties[1].value, 'id', 0) ||
        awaited?.type !== 'AwaitExpression' || awaited.argument !== call ||
        assignment?.type !== 'AssignmentExpression' || assignment.operator !== '=' || !id(assignment.left, 'ret') ||
        assignment.right !== awaited || statement?.type !== 'ExpressionStatement' || statement.expression !== assignment ||
        block?.type !== 'BlockStatement' || block.body.length !== 1 || block.body[0] !== statement ||
        guarded?.type !== 'TryStatement' || guarded.block !== block || guarded.finalizer ||
        !outer.body.body.includes(guarded)) fail();
    const fn = object.properties[2].value;
    if (fn.type !== 'ArrowFunctionExpression' || fn.async || fn.generator || fn.params.length ||
        fn.body.type !== 'CallExpression' || fn.body.optional || fn.body.callee.type !== 'Identifier') fail();
    const catchClause = guarded.handler, catchBody = catchClause?.body.body;
    if (!id(catchClause?.param, 'err') || catchBody?.length !== 4 ||
        !taskCall(catchBody[0].expression, 'setErrored', 1) || !id(catchBody[0].expression.arguments[0], 'err') ||
        !taskCall(catchBody[1].expression, 'reject', 1) || !id(catchBody[1].expression.arguments[0], 'err') ||
        !taskCall(catchBody[2].expression, 'exit', 0) || catchBody[3].type !== 'ReturnStatement' ||
        !taskCall(catchBody[3].argument, 'completionPromise', 0)) fail();
    const inside = entries.filter(({node}) => node.start >= outer.start && node.end <= outer.end);
    const declarations = inside.filter(({node, parents: scope}) => node.type === 'VariableDeclarator' &&
      enclosing(scope) === outer && id(node.id, 'ret'));
    const enters = inside.filter(({node}) => taskCall(node, 'enter', 1));
    const creation = inside.filter(({node}) => node.type === 'CallExpression' && id(node.callee, 'createNewCurrentTask'));
    if (inside.some(({node}) => id(node, '__lsfExportTaskMetaArgs')) || declarations.length !== 1 ||
        declarations[0].node.init || declarations[0].node.end >= guarded.start || enters.length !== 1 ||
        enters[0].node.end >= guarded.start || enters[0].parents.at(-1)?.type !== 'AwaitExpression' ||
        creation.length !== 1 || creation[0].node.end >= enters[0].node.start) fail();
    // Capture the original callback outside the helper's lexical scope. This
    // preserves references named args/current/fn/etc. in generated arguments.
    edits.push({start: statement.start, end: statement.end,
      text: inlinedExportTaskBlock(source.slice(object.start, object.end))});
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

// The private task's completion capability is not observed on the normal
// export path until settlement. Create it at first observation or immediately
// before the original settlement handlers, not while the application runs.
// Keep the real intrinsic Promise: do not buffer results, emulate thenables,
// omit rejection reporting, or release an owner while an object is reachable.
export function lazyTaskCompletion(source, parse) {
  const fail = () => { throw new Error('selected-runtime-task-completion-shape-drift'); };
  let tree;
  try { tree = parse(source, {ecmaVersion: 'latest', sourceType: 'module'}); }
  catch { fail(); }
  const classes = [];
  function visit(node) {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'ClassDeclaration' && node.id?.name === 'AsyncTask') classes.push(node);
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(visit);
      else if (value && typeof value === 'object') visit(value);
    }
  }
  visit(tree);
  if (!classes.length && !source.includes('AsyncTask')) return source;
  if (classes.length !== 1 || source.includes('#completionCapability') ||
      source.includes('#ensureCompletionPromise')) fail();
  const task = classes[0];
  if (task.superClass !== null) fail();
  const members = task.body.body;
  const select = (name, privateName = false) => {
    const found = members.filter(node => node.key?.name === name &&
      (node.key.type === 'PrivateIdentifier') === privateName);
    if (found.length !== 1 || found[0].static || found[0].computed) fail();
    return found[0];
  };
  // Compare only the rewritten ownership boundary. Unrelated generator bodies
  // remain byte-for-byte original; whitespace and source offsets are irrelevant.
  const shape = node => JSON.stringify(node, (key, value) =>
    ['start', 'end', 'raw'].includes(key) ? undefined : value);
  const expected = parse(`class AsyncTask {
    #completionPromise = null;
    #onResolveHandlers = [];
    #errored = null;
    #rejected = false;
    constructor() {
      const {promise: completionPromise, resolve: resolveCompletionPromise,
        reject: rejectCompletionPromise} = promiseWithResolvers();
      this.#completionPromise = completionPromise;
      this.#onResolveHandlers.push((results) => {
        if (this.#errored !== null) {
          rejectCompletionPromise(this.#errored);
          return;
        } else if (this.#rejected) {
          rejectCompletionPromise(results);
          return;
        }
        resolveCompletionPromise(results);
      });
    }
    completionPromise() { return this.#completionPromise; }
    onResolve(taskValue) {
      const handlers = this.#onResolveHandlers;
      this.#onResolveHandlers = [];
    }
  }`, {ecmaVersion: 'latest', sourceType: 'module'}).body[0].body.body;
  const field = select('completionPromise', true), getter = select('completionPromise');
  const constructor = select('constructor'), settlement = select('onResolve');
  const expectedConstructor = expected.find(node => node.kind === 'constructor');
  const expectedGetter = expected.find(node => node.key.name === 'completionPromise' &&
    node.key.type === 'Identifier');
  const expectedSettlement = expected.find(node => node.key.name === 'onResolve');
  if (shape(select('onResolveHandlers', true)) !== shape(expected[1]) ||
      shape(select('errored', true)) !== shape(expected[2]) ||
      shape(select('rejected', true)) !== shape(expected[3]) ||
      shape(field) !== shape(expected[0]) || shape(getter) !== shape(expectedGetter) ||
      constructor.kind !== 'constructor' || settlement.kind !== 'method' ||
      settlement.value.async || settlement.value.generator ||
      shape(settlement.value.params) !== shape(expectedSettlement.value.params) ||
      shape(settlement.value.body.body.slice(0, 2)) !== shape(expectedSettlement.value.body.body)) fail();
  const statements = constructor.value.body.body;
  const pattern = expectedConstructor.value.body.body;
  const matches = statements.map((node, index) => shape(node) === shape(pattern[0]) ? index : -1)
    .filter(index => index !== -1);
  if (matches.length !== 1) fail();
  const index = matches[0], sequence = statements.slice(index, index + 3);
  if (shape(sequence) !== shape(pattern)) fail();
  const countName = (node, type, name) => {
    let count = 0;
    function countNode(value) {
      if (!value || typeof value !== 'object') return;
      if (value.type === type && value.name === name) ++count;
      for (const child of Object.values(value)) {
        if (Array.isArray(child)) child.forEach(countNode);
        else if (child && typeof child === 'object') countNode(child);
      }
    }
    countNode(node);
    return count;
  };
  if (countName(task, 'PrivateIdentifier', 'completionPromise') !== 3) fail();
  for (const name of ['completionPromise', 'resolveCompletionPromise', 'rejectCompletionPromise']) {
    if (countName(constructor, 'Identifier', name) !==
        countName(expectedConstructor, 'Identifier', name)) fail();
  }
  const handler = sequence[2].expression.arguments[0];
  const originalHandler = source.slice(handler.body.start + 1, handler.body.end - 1);
  const edits = [
    {start: field.end, end: field.end, text: '\n  #completionCapability = null;'},
    {start: sequence[0].start, end: sequence[2].end, text:
      'this.#onResolveHandlers.push((results) => {\n' +
      '  const {resolve: resolveCompletionPromise, reject: rejectCompletionPromise} = this.#completionCapability;\n' +
      '  this.#completionCapability = null; // Drop captures after this original handler returns.\n' +
      originalHandler + '\n});'},
    {start: getter.start, end: getter.end, text:
      'completionPromise() { this.#ensureCompletionPromise(); return this.#completionPromise; }\n' +
      '  #ensureCompletionPromise() {\n' +
      '    if (this.#completionPromise !== null) return;\n' +
      '    const capability = promiseWithResolvers();\n' +
      '    const promise = capability.promise;\n' +
      '    this.#completionCapability = capability;\n' +
      '    this.#completionPromise = promise;\n' +
      '  }'},
    {start: settlement.value.body.start + 1, end: settlement.value.body.start + 1,
      text: '\n    this.#ensureCompletionPromise(); // Before detaching any original settlement handler.\n'},
  ];
  // Lazy allocation adds a fallible boundary that did not exist at settlement.
  // Admit it after the original validation/no-op guards, but before publishing
  // terminal flags or rejecting children. onResolve alone is too late: resolve
  // has already marked the task resolved, and reject has already set its guard.
  const transitionBoundaries = parse(`class AsyncTask {
  #componentIdx; #id; #entryFnName; #callbackFnName; #parentSubtask;
  #state; #rejected; #subtasks;
  resolve(results) {
    _debugLog('[AsyncTask#resolve()] args', {
      componentIdx: this.#componentIdx,
      taskID: this.#id,
      entryFnName: this.entryFnName(),
      callbackFnName: this.#callbackFnName,
    });

    if (this.#state === AsyncTask.State.RESOLVED) {
      throw new Error(\`(component [\${this.#componentIdx}]) task [\${this.#id}]  is already resolved (did you forget to wait for an import?)\`);
    }

    if (this.borrowedHandles.length > 0) {
      throw new Error('task still has borrow handles');
    }

    this.#state = AsyncTask.State.RESOLVED;
  }
  reject(taskErr) {
    _debugLog('[AsyncTask#reject()] args', {
      componentIdx: this.#componentIdx,
      taskID: this.#id,
      parentSubtask: this.#parentSubtask,
      parentSubtaskID: this.#parentSubtask?.id(),
      entryFnName: this.entryFnName(),
      callbackFnName: this.#callbackFnName,
      errMsg: taskErr.message,
    });

    if (this.isResolvedState() || this.#rejected) { return; }

    for (const subtask of this.#subtasks) {
      subtask.reject(taskErr);
    }
  }
  cancel(args) {
    _debugLog('[AsyncTask#cancel()] args', { });
    if (this.taskState() !== AsyncTask.State.CANCEL_DELIVERED) {
      throw new Error(\`(component [\${this.#componentIdx}]) task [\${this.#id}] invalid task state [\${this.taskState()}] for cancellation\`);
    }
    if (this.borrowedHandles.length > 0) { throw new Error('task still has borrow handles'); }
    this.cancelled = true;
  }
}`,
    {ecmaVersion: 'latest', sourceType: 'module'}).body[0].body.body.filter(node => node.type === 'MethodDefinition');
  for (const boundary of transitionBoundaries) {
    const method = select(boundary.key.name);
    const prefix = boundary.value.body.body;
    if (method.kind !== 'method' || method.value.async || method.value.generator ||
        shape(method.value.params) !== shape(boundary.value.params) ||
        shape(method.value.body.body.slice(0, prefix.length)) !== shape(prefix)) fail();
    const transition = method.value.body.body[prefix.length - 1];
    edits.push({start: transition.start, end: transition.start,
      text: 'this.#ensureCompletionPromise(); // Before terminal state or child settlement.\n    '});
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
