"""Evaluate only literal source-identity expressions, never arbitrary Python."""
def repair_constants(script: str) -> str:
    def change(before, after):
        nonlocal script
        assert script.count(before)==1,before
        script=script.replace(before,after)
    change('        for a,b in references.items():value=value.replace(a,b)\n        return value',
           '        for a,b in references.items():value=value.replace(a,b)\n        return identities[value]["sha256"] if value in identities else value')
    helpers='''def constant_value(node,namespace):
    if isinstance(node,ast.Constant):return node.value
    if isinstance(node,ast.Name) and node.id in namespace:return namespace[node.id]
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add):
        left=constant_value(node.left,namespace);right=constant_value(node.right,namespace)
        if isinstance(left,str) and isinstance(right,str):return left+right
        raise ValueError('not a literal string concatenation')
    if isinstance(node,ast.Dict):return {constant_value(k,namespace):constant_value(v,namespace) for k,v in zip(node.keys,node.values)}
    if isinstance(node,ast.List):return [constant_value(v,namespace) for v in node.elts]
    if isinstance(node,ast.Tuple):return tuple(constant_value(v,namespace) for v in node.elts)
    raise ValueError('not a supported literal identity expression')
def evaluated_constant(path,key):
    namespace={}
    for declaration in ast.parse(path.read_text()).body:
        if not isinstance(declaration,ast.Assign) or len(declaration.targets)!=1 or not isinstance(declaration.targets[0],ast.Name):continue
        name=declaration.targets[0].id
        try:namespace[name]=constant_value(declaration.value,namespace)
        except (ValueError,TypeError):continue
        if name==key:return namespace[name]
    raise ValueError('unsupported constant '+key)
'''
    change('def assignment(path,key,transform):\n',helpers+'def assignment(path,key,transform):\n')
    change('    value=transform(ast.literal_eval(node.value));lines=text.splitlines(True)',
           '    old=evaluated_constant(path,key);value=transform(old)\n    if value==old:return\n    lines=text.splitlines(True)')
    change('        try:ast.literal_eval(node.value)\n        except (ValueError,TypeError):continue',
           '        try:evaluated_constant(path,node.targets[0].id)\n        except (ValueError,TypeError):continue')
    return script
