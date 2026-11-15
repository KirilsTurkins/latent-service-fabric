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
  const body = exportTaskMetaPreimage.slice(exportTaskMetaPreimage.indexOf('{') + 1, -1)
    .replace('return await fn();', 'ret = await fn();');
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
    edits.push({start: statement.start, end: statement.end, text:
      '{\n  const __lsfExportTaskMetaArgs = ' + source.slice(object.start, object.end) +
      ';\n  {\n    const args = __lsfExportTaskMetaArgs;\n' + body + '\n  }\n}'});
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
