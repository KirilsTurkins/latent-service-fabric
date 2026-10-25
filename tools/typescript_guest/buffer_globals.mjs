// Data-only selection over bounded compiler-emitted ES2022, never execution or
// a library reachability certificate. Final code keeps ordinary global reads.
export const BUFFER_GLOBAL_PROFILE = 'lsf-node-buffer-global-v1';
export const BUFFER_GLOBAL_PRIVATE = 'lsf:typescript-buffer-global-initializer';

export function bufferGlobalReferences(source, parse) {
  if (typeof source !== 'string' || source.length > 32 * 1024 * 1024)
    throw new Error('buffer-global-selection-source-bound');
  const tree = parse(source, {ecmaVersion: 2022, sourceType: 'module'});
  const scopes = [], references = [];
  let count = 0;
  function budget() {
    if (++count > 1000000) throw new Error('buffer-global-selection-node-bound');
  }
  const scope = (parent, variable = false) => {
    const value = {parent, variable, names: new Set()}; scopes.push(value); return value;
  };
  function variableScope(owner) { while (!owner.variable) owner = owner.parent; return owner; }
  function pattern(node, owner, evaluation) {
    if (!node) return;
    budget();
    switch (node.type) {
      case 'Identifier': owner.names.add(node.name); return;
      case 'RestElement': pattern(node.argument, owner, evaluation); return;
      case 'AssignmentPattern': pattern(node.left, owner, evaluation); visit(node.right, evaluation); return;
      case 'ArrayPattern': for (const item of node.elements) pattern(item, owner, evaluation); return;
      case 'ObjectPattern':
        for (const item of node.properties) {
          budget();
          if (item.type === 'RestElement') pattern(item.argument, owner, evaluation);
          else { if (item.computed) visit(item.key, evaluation); pattern(item.value, owner, evaluation); }
        }
        return;
      default: throw new Error('buffer-global-binding-pattern');
    }
  }
  function visit(node, owner) {
    if (!node) return;
    budget();
    switch (node.type) {
      case 'Identifier':
        if (node.name === 'Buffer') references.push({name: 'Buffer', form: 'Buffer', owner});
        return;
      case 'ImportDeclaration':
        for (const item of node.specifiers) owner.names.add(item.local.name);
        return;
      case 'VariableDeclaration':
        for (const item of node.declarations) {
          pattern(item.id, node.kind === 'var' ? variableScope(owner) : owner, owner);
          visit(item.init, owner);
        }
        return;
      case 'FunctionDeclaration': case 'FunctionExpression': case 'ArrowFunctionExpression': {
        if (node.type === 'FunctionDeclaration' && node.id) owner.names.add(node.id.name);
        const parameters = scope(owner, true);
        if (node.id) parameters.names.add(node.id.name);
        for (const item of node.params) pattern(item, parameters, parameters);
        // Body var declarations do not bind parameter default expressions.
        const body = scope(parameters, true);
        visit(node.body, body);
        return;
      }
      case 'ClassDeclaration': case 'ClassExpression': {
        if (node.type === 'ClassDeclaration' && node.id) owner.names.add(node.id.name);
        const local = scope(owner);
        if (node.id) local.names.add(node.id.name);
        visit(node.superClass, local); visit(node.body, local); return;
      }
      case 'BlockStatement': case 'StaticBlock': {
        const local = scope(owner, node.type === 'StaticBlock');
        for (const item of node.body) visit(item, local);
        return;
      }
      case 'ForStatement': case 'ForInStatement': case 'ForOfStatement': {
        const local = scope(owner);
        for (const key of ['init', 'left', 'right', 'test', 'update', 'body']) visit(node[key], local);
        return;
      }
      case 'SwitchStatement': {
        visit(node.discriminant, owner);
        const local = scope(owner);
        for (const item of node.cases) { visit(item.test, local); for (const child of item.consequent) visit(child, local); }
        return;
      }
      case 'CatchClause': {
        const local = scope(owner); pattern(node.param, local, local); visit(node.body, local); return;
      }
      case 'MemberExpression':
        if (node.object.type === 'Identifier' && node.object.name === 'globalThis' &&
            ((!node.computed && node.property.name === 'Buffer') ||
             (node.computed && node.property.type === 'Literal' && node.property.value === 'Buffer')))
          references.push({name: 'globalThis', form: 'globalThis.Buffer', owner});
        visit(node.object, owner); if (node.computed) visit(node.property, owner); return;
      case 'Property': case 'MethodDefinition': case 'PropertyDefinition':
        if (node.computed) visit(node.key, owner);
        visit(node.value, owner); return;
      case 'ExportNamedDeclaration':
        visit(node.declaration, owner);
        if (!node.source) for (const item of node.specifiers) visit(item.local, owner);
        return;
      case 'ExportAllDeclaration': case 'MetaProperty': case 'BreakStatement': case 'ContinueStatement':
        return;
      case 'LabeledStatement': visit(node.body, owner); return;
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) { for (const child of value) if (child?.type) visit(child, owner); }
      else if (value?.type) visit(value, owner);
    }
  }
  visit(tree, scope(null, true));
  const forms = new Set();
  for (const ref of references) {
    let owner = ref.owner;
    while (owner && !owner.names.has(ref.name)) owner = owner.parent;
    if (!owner) forms.add(ref.form);
  }
  return [...forms].sort();
}

export function bufferGlobalBuiltin(source) {
  if (typeof source !== 'string' || !source.length || source.length > 4096)
    throw new Error('buffer-global-initializer-source-bound');
  let enabled = false;
  return {
    enable() { enabled = true; },
    resolve(args) {
      if (args.path !== BUFFER_GLOBAL_PRIVATE) return undefined;
      if (!enabled || args.kind !== 'entry-point' || args.importer !== '')
        return {errors: [{text: 'compiler-private-buffer-global-initializer'}]};
      return {path: BUFFER_GLOBAL_PRIVATE, namespace: 'lsf-owned-buffer-global', sideEffects: true};
    },
    load(args) {
      if (!enabled || args.path !== BUFFER_GLOBAL_PRIVATE || args.namespace !== 'lsf-owned-buffer-global')
        throw new Error('compiler-private-buffer-global-identity');
      return {contents: source, loader: 'js'};
    },
    verify(metafile, output) {
      const key = 'lsf-owned-buffer-global:' + BUFFER_GLOBAL_PRIVATE;
      const linked = metafile.outputs[output]?.inputs?.[key]?.bytesInOutput;
      if (!enabled || !Object.hasOwn(metafile.inputs, key) || !Number.isInteger(linked) || linked <= 0)
        throw new Error('compiler-owned-buffer-global-link-missing');
    },
  };
}
