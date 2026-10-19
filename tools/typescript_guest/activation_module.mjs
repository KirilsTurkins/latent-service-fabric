// Only the explicit standard-console profile uses activation-time module init.
export function activationModule(source, exports, parse) {
  const ast = parse(source, {ecmaVersion: 2022, sourceType: 'module'});
  if (source.length > 32 * 1024 * 1024 || !Array.isArray(exports) || !exports.length || exports.length > 64) {
    throw new Error('console-activation-module-limit');
  }
  const imports = [], removed = [], bindings = new Map();
  for (const node of ast.body) {
    if (node.type === 'ImportDeclaration') {
      if (node.specifiers.some(item => item.local.name.startsWith('__lsf'))) throw new Error('console-activation-import-binding');
      imports.push(source.slice(node.start, node.end));
      removed.push(node);
    }
    else if (node.type === 'ExportNamedDeclaration' && node.declaration === null && node.source === null) {
      for (const item of node.specifiers) {
        if (item.type !== 'ExportSpecifier' || item.local.type !== 'Identifier' || item.exported.type !== 'Identifier' ||
            bindings.has(item.exported.name)) throw new Error('console-activation-export-shape');
        bindings.set(item.exported.name, item.local.name);
      }
      removed.push(node);
    } else {
      if (node.type.startsWith('Export')) throw new Error('console-activation-export-shape');
    }
  }
  let nodes = 0;
  function visit(node, depth) {
    if (++nodes > 1000000) throw new Error('console-activation-syntax-limit');
    if (!depth && (node.type === 'AwaitExpression' || node.type === 'ForOfStatement' && node.await)) {
      throw new Error('console-activation-top-level-await-unsupported');
    }
    if (['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'].includes(node.type)) depth++;
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) {
        for (const child of value) if (child && typeof child.type === 'string') visit(child, depth);
      } else if (value && typeof value.type === 'string') visit(value, depth);
    }
  }
  visit(ast, 0);
  const identifier = name => typeof name === 'string' && /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(name) && !name.startsWith('__lsf');
  if (bindings.size !== exports.length || exports.some(item => !identifier(item.name) || !bindings.has(item.name)) ||
      new Set(exports.map(item => item.name)).size !== exports.length) throw new Error('console-activation-export-set');
  const wrappers = [];
  function method(owner, item) {
    if (!identifier(item.name) || !Number.isInteger(item.parameters) || item.parameters < 0 || item.parameters > 32) {
      throw new Error('console-activation-function-shape');
    }
    const args = Array.from({length: item.parameters}, (_, index) => 'a' + index);
    return `${item.name}(${args}) {const original = __lsfInitializeApplication();return ${owner(args)};}`;
  }
  for (const item of exports) {
    if (item.functions === null) {
      const code = method(args => `Reflect.apply(original.${item.name}, undefined, [${args}])`, item);
      wrappers.push(`export const ${item.name} = ({${code}}).${item.name};`);
    } else {
      if (!Array.isArray(item.functions) || !item.functions.length || item.functions.length > 64 ||
          new Set(item.functions.map(fn => fn.name)).size !== item.functions.length) throw new Error('console-activation-function-set');
      wrappers.push(`export const ${item.name} = {${item.functions.map(fn => method(args =>
        `((receiver) => Reflect.apply(receiver.${fn.name}, receiver, [${args}]))(original.${item.name})`, fn)).join(',')}};`);
    }
  }
  let body = source;
  for (const node of [...removed].reverse()) {
    body = body.slice(0, node.start) + body.slice(node.start, node.end).replace(/[^\r\n]/g, ' ') + body.slice(node.end);
  }
  const prefix = imports.join('\n') + `
let __lsfModuleState = 0, __lsfModuleValue, __lsfModuleFailure;
function __lsfInitializeApplication() {
  if (__lsfModuleState === 2) return __lsfModuleValue;
  if (__lsfModuleState === 3) throw __lsfModuleFailure;
  if (__lsfModuleState === 1) throw new Error('console-activation-initializer-reentry');
  __lsfModuleState = 1;
  try {
    __lsfModuleValue = (() => {
`;
  return {source: prefix + body + `
return {${[...bindings].map(([name, local]) => `get ${name}(){return ${local};}`).join(',')}};
    })();
    __lsfModuleState = 2;
    return __lsfModuleValue;
  } catch (error) {__lsfModuleFailure = error;__lsfModuleState = 3;throw error;}
}
${wrappers.join('\n')}
`, lineShift: prefix.split('\n').length - 1,
    erasedLines: removed.flatMap(node => Array.from({length: source.slice(node.start, node.end).split('\n').length},
      (_, index) => source.slice(0, node.start).split('\n').length - 1 + index))
      .filter(line => !body.split('\n')[line].trim())};
}
