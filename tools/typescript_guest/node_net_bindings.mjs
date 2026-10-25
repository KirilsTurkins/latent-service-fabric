import { borrowReleaseHandoff } from './import_cancellation.mjs';
import { createNodeNetTransport } from './node_net_transport.mjs';

export const NET_PROFILE = 'lsf-node-net-tcp-v1';
export const NET_PRIVATE = 'lsf:typescript-node-net-transport';
const prefix = 'import_latent_network_streams_0_1_0$';
const operations = Object.freeze(['connect', 'read', 'write', 'ready', 'chunkBytes', 'shutdown', 'close']);

// This projection changes no public call, typed lift/lower, task exit or native
// owner. Its one root assertion stays within the ORIGINAL error-handling try.
export function nodeNetBindings(source, parse, profile, exported) {
  if (profile === undefined) return source;
  const fail = () => { throw new Error('compiler-owned-node-net-binding-shape'); };
  if (profile !== NET_PROFILE || source.includes('__lsfNodeNet') ||
      !Array.isArray(exported) || exported.length < 1 || exported.length > 64) fail();
  const selected = operations.map(alias => ({binding: prefix + alias, alias}));
  source = borrowReleaseHandoff(source, parse, selected);
  const tree = parse(source, {ecmaVersion: 'latest', sourceType: 'module'});
  // The real initializer is a closed script with builtin registration, not an
  // ESM module whose static dependencies could run before these declarations.
  if (tree.body.some(node => node.type.startsWith('Import') || node.type.startsWith('Export'))) fail();
  const functions = tree.body.filter(node => node.type === 'FunctionDeclaration');
  const id = (node, name) => node?.type === 'Identifier' && node.name === name;
  const member = (node, object, name) => node?.type === 'MemberExpression' && !node.computed &&
    id(node.object, object) && id(node.property, name);
  const taskCall = (statement, name) => statement?.type === 'ExpressionStatement' &&
    statement.expression.type === 'CallExpression' && member(statement.expression.callee, 'task', name) &&
    (name === 'exit' ? statement.expression.arguments.length === 0 :
      statement.expression.arguments.length === 1 && id(statement.expression.arguments[0], 'err'));
  const names = new Set();
  for (const row of exported) {
    if (!Array.isArray(row) || row.length !== 2 || typeof row[0] !== 'string' ||
        !/^export_[A-Za-z0-9_$]+$/.test(row[0]) || names.has(row[0]) ||
        !row[1] || !Array.isArray(row[1].params) || row[1].paramptr !== false ||
        typeof row[1].retptr !== 'boolean') fail();
    names.add(row[0]);
  }
  if (functions.filter(node => node.id?.name.startsWith('export_')).length !== names.size) fail();
  const edits = [];
  for (const [name, abi] of exported) {
    const found = functions.filter(node => id(node.id, name));
    if (found.length !== 1) fail();
    const fn = found[0];
    if (!fn.async || fn.generator || fn.params.some(node => node.type !== 'Identifier') ||
        fn.params.length !== abi.params.length + Number(abi.retptr)) fail();
    const tries = fn.body.body.filter(node => node.type === 'TryStatement');
    if (tries.length !== 1) fail();
    const original = tries[0], statement = original.block.body[0];
    if (original.finalizer || original.block.body.length !== 1 ||
        statement?.type !== 'ExpressionStatement' || statement.expression.type !== 'AssignmentExpression' ||
        statement.expression.operator !== '=' || !id(statement.expression.left, 'ret') ||
        statement.expression.right.type !== 'AwaitExpression') fail();
    const awaited = statement.expression.right.argument;
    if (awaited.type !== 'CallExpression' || !id(awaited.callee, '_withGlobalCurrentTaskMetaAsync') ||
        awaited.arguments.length !== 1 || awaited.arguments[0].type !== 'ObjectExpression') fail();
    const properties = awaited.arguments[0].properties;
    if (properties.length !== 3 || properties.some(node => node.type !== 'Property' || node.computed || node.kind !== 'init') ||
        properties.map(node => node.key.name).sort().join(',') !== 'componentIdx,fn,taskID') fail();
    const caller = properties.find(node => id(node.key, 'fn')).value;
    if (caller.type !== 'ArrowFunctionExpression' || caller.async || caller.params.length ||
        caller.body.type !== 'CallExpression' || caller.body.callee.type !== 'Identifier') fail();
    const caught = original.handler;
    if (caught?.type !== 'CatchClause' || !id(caught.param, 'err') || caught.body.body.length !== 4 ||
        !taskCall(caught.body.body[0], 'setErrored') || !taskCall(caught.body.body[1], 'reject') ||
        !taskCall(caught.body.body[2], 'exit') || caught.body.body[3].type !== 'ReturnStatement' ||
        caught.body.body[3].argument?.type !== 'CallExpression' ||
        !member(caught.body.body[3].argument.callee, 'task', 'completionPromise') ||
        caught.body.body[3].argument.arguments.length !== 0) fail();
    const enter = fn.body.body.filter(node => node.type === 'VariableDeclaration' && node.declarations.length === 1 &&
      id(node.declarations[0].id, 'started'));
    if (enter.length !== 1 || enter[0].declarations[0].init?.type !== 'AwaitExpression' ||
        !member(enter[0].declarations[0].init.argument?.callee, 'task', 'enter') || enter[0].end >= original.start) fail();
    // Publication may run result getters, coercion helpers, or onResolve hooks.
    // Fence new Socket admission through that ORIGINAL synchronous tail.
    const tail = fn.body.body.slice(fn.body.body.indexOf(original) + 1);
    const terminal = tail.at(-2), exit = tail.at(-1);
    if (tail.length < 2 || terminal?.type !== 'ExpressionStatement' ||
        terminal.expression.type !== 'CallExpression' ||
        !member(terminal.expression.callee, 'task', 'resolve') ||
        terminal.expression.arguments.length !== 1 ||
        terminal.expression.arguments[0].type !== 'ArrayExpression' ||
        terminal.expression.arguments[0].elements.length !== 1 ||
        !id(terminal.expression.arguments[0].elements[0], 'ret') || !taskCall(exit, 'exit')) fail();
    let resolves = 0;
    function inspectTail(node) {
      if (!node || typeof node !== 'object') return;
      if (['AwaitExpression', 'YieldExpression', 'ReturnStatement'].includes(node.type)) fail();
      if (node.type === 'CallExpression' && member(node.callee, 'task', 'resolve')) ++resolves;
      for (const value of Object.values(node)) {
        if (Array.isArray(value)) { for (const child of value) inspectTail(child); }
        else if (value && typeof value === 'object') inspectTail(value);
      }
    }
    for (const node of tail) inspectTail(node);
    if (resolves !== 1) fail();
    edits.push({start: statement.end, text: '\n    __lsfNodeNetRootCheck();'});
    edits.push({start: original.end, text: '\n  __lsfNodeNetTransport.beginRootReturn();\n  try {'});
    edits.push({start: terminal.start, text: '__lsfNodeNetRootCheck();\n  '});
    edits.push({start: fn.body.end - 1, text: '\n  } finally { __lsfNodeNetTransport.endRootReturn(); }\n'});
  }
  const inspections = functions.filter(node => id(node.id, prefix + 'inspect'));
  if (inspections.length !== 1 || inspections[0].async || inspections[0].params.length !== 1) fail();
  edits.sort((a, b) => b.start - a.start);
  for (const edit of edits) source = source.slice(0, edit.start) + edit.text + source.slice(edit.start);
  // Tail registration is after every real CAP/task/resource initializer. The
  // private module cannot resolve until this exact factory/registry is ready.
  source += '\nconst __lsfNodeNetTransport = (' + createNodeNetTransport.toString() +
    ')(__lsfBorrowCalls, contentGlobal, ' + prefix + 'inspect);\n' +
    'const __lsfNodeNetRootCheck = Object.getOwnPropertyDescriptor(contentGlobal, "__lsfNodeNetRootCheck").value;\n' +
    'defineBuiltinModule(' + JSON.stringify(NET_PRIVATE) + ', __lsfNodeNetTransport);\n';
  parse(source, {ecmaVersion: 'latest', sourceType: 'module'});
  return source;
}
