"""Offline dependency observations for narrowly selected tooling changes.

An incomplete or dynamic edge is never evidence for a narrow selection.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re

MAX_FILES = 6000
MAX_SOURCE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class ToolGraph:
    imports: dict[str, frozenset[str]]
    unresolved: frozenset[str]

    def dependents(self, changed: set[str]) -> set[str]:
        reached = set(changed)
        while True:
            pending = {owner for owner, dependencies in self.imports.items() if dependencies & reached}
            if pending <= reached:
                return reached
            reached |= pending


def module_name(path: str) -> str:
    if not re.fullmatch(r'tools/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*\.py', path):
        raise ValueError('unsupported-python-module-path')
    pieces = path.removesuffix('.py').split('/')
    if pieces[-1] == '__init__': pieces.pop()
    return '.'.join(pieces)


def observe(root: Path, explicit_edges: dict[str, set[str]] | None = None,
            extra_inputs: set[str] | None = None) -> ToolGraph:
    """Resolve ordinary imports; preserve every unresolved dynamic owner."""
    root = root.resolve(strict=True)
    tools = root / 'tools'
    if not tools.is_dir() or tools.is_symlink(): raise ValueError('missing-tools-directory')
    files = sorted(path for path in tools.rglob('*.py') if '__pycache__' not in path.parts)
    if not 0 < len(files) <= MAX_FILES: raise ValueError('tool-file-count')
    names = {}
    paths = {}
    total = 0
    for path in files:
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent):
            raise ValueError('linked-tool-source')
        relative = path.relative_to(root).as_posix()
        try: name = module_name(relative)
        except ValueError: continue  # Non-importable filenames cannot be imported as modules.
        if name in names: raise ValueError('ambiguous-tool-module')
        with path.open('rb') as source: data = source.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES: raise ValueError('tool-source-limit')
        total += len(data)
        if total > MAX_TOTAL_BYTES: raise ValueError('tool-total-limit')
        names[name] = relative
        paths[relative] = (name, ast.parse(data.decode('utf-8-sig'), filename=relative))
    packages = {'.'.join(name.split('.')[:index]) for name in names for index in range(1, len(name.split('.')))}
    imports = {path: set() for path in paths}
    unresolved = set()
    for path, (module, tree) in paths.items():
        aliases = {'__import__': '__import__', 'eval': 'eval', 'exec': 'exec'}
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for statement in ast.walk(tree):
            if isinstance(statement, ast.ImportFrom) and statement.module == 'importlib':
                for alias in statement.names:
                    if alias.name == 'import_module': aliases[alias.asname or alias.name] = 'importlib.import_module'
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    if alias.name == 'importlib' and alias.asname:
                        aliases[alias.asname + '.import_module'] = 'importlib.import_module'
                        aliases[alias.asname + '.util.spec_from_file_location'] = 'importlib.util.spec_from_file_location'
        def add(candidate: str):
            if candidate in packages and candidate not in names: return True
            original = candidate
            while candidate.startswith('tools.'):
                if candidate in names:
                    imports[path].add(names[candidate]); return True
                candidate = candidate.rpartition('.')[0]
            if original == 'tools' and candidate in names:
                imports[path].add(names[candidate]); return True
            return False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.Attribute)):
                expression = ast.unparse(node)
                dynamic = aliases.get(expression, expression) in {
                    '__import__', 'eval', 'exec', 'importlib.import_module',
                    'importlib.util.spec_from_file_location'}
                parent = parents.get(node)
                if dynamic and not (isinstance(parent, ast.Call) and parent.func is node):
                    unresolved.add(path)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith('tools.') and not add(alias.name): unresolved.add(path)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = module if path.endswith('/__init__.py') else module.rpartition('.')[0]
                    bits = package.split('.')
                    if node.level > len(bits):
                        unresolved.add(path); continue
                    base = '.'.join(bits[:len(bits)-node.level+1])
                    name = '.'.join(filter(None, (base, node.module or '')))
                else:
                    name = node.module or ''
                if name.startswith('tools'):
                    if not add(name): unresolved.add(path)
                    for alias in node.names:
                        child = name + '.' + alias.name
                        if child in names: imports[path].add(names[child])
                        elif name == 'tools': unresolved.add(path)
            elif isinstance(node, ast.Call):
                try: call = ast.unparse(node.func)
                except ValueError: unresolved.add(path); continue
                call = aliases.get(call, call)
                if (call == 'getattr' and node.args and isinstance(node.args[0], ast.Name)
                        and node.args[0].id in {'importlib', 'builtins', '__builtins__'}):
                    unresolved.add(path)
                if call in {'eval', 'exec'}:
                    unresolved.add(path)
                elif call in {'__import__', 'importlib.import_module', 'importlib.util.spec_from_file_location'}:
                    argument = (node.args[0] if call != 'importlib.util.spec_from_file_location' else
                                node.args[1] if len(node.args) > 1 else None)
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        value = argument.value
                        if value.startswith('tools.'): add(value)
                        elif value.startswith('tools/') and value in paths: imports[path].add(value)
                    else: unresolved.add(path)
        imports[path].discard(path)
    for name in extra_inputs or set():
        candidate = root / name
        if (not name or name.startswith('/') or '\\' in name or any(part in {'', '.', '..'} for part in name.split('/'))
                or not candidate.is_file() or candidate.is_symlink() or not candidate.resolve().is_relative_to(root)):
            raise ValueError('unsafe-tool-input')
        if name in imports: raise ValueError('duplicate-tool-input')
        imports[name] = set()
    for owner, dependencies in (explicit_edges or {}).items():
        if owner not in imports or not dependencies <= imports.keys(): raise ValueError('unknown-explicit-tool-edge')
        imports[owner].update(dependencies)
        # A declared edge cannot by itself prove all dynamic sites resolved.
    return ToolGraph({name: frozenset(value) for name, value in imports.items()}, frozenset(unresolved))


def affected(graphs: tuple[ToolGraph, ...], changed: set[str], *,
             history_complete: bool = False, regular_modes: bool = False) -> tuple[set[str], str]:
    """Union old and new reverse owners; uncertainty always selects full."""
    if not graphs or not changed: return set(), 'full-empty-input'
    if not history_complete: return set(), 'full-history-unavailable'
    if not regular_modes: return set(), 'full-ambiguous-mode'
    if any(any(path not in graph.imports for graph in graphs) for path in changed):
        return set(), 'full-unknown-path'
    if any(graph.unresolved for graph in graphs):
        return set(), 'full-unresolved-dynamic-import'
    reached = set(changed)
    while True:
        expanded = reached | set().union(*(graph.dependents(reached) for graph in graphs))
        if expanded == reached: return reached, 'resolved'
        reached = expanded


def isolated_doc_test_additions(before: str, after: str) -> bool:
    """Recognize only additive, local documentation-validator test bodies."""
    import copy
    try:
        old, new = ast.parse(before), ast.parse(after)
        previous = {node.name: node for node in old.body if isinstance(node, ast.ClassDef)}
        current = {node.name: node for node in new.body if isinstance(node, ast.ClassDef)}
        if len(previous) != sum(isinstance(node, ast.ClassDef) for node in old.body): return False
        if set(previous) != set(current): return False
        old_owner, new_owner = previous.get('DocumentationValidationTests'), current.get('DocumentationValidationTests')
        if old_owner is None or new_owner is None: return False
        if [ast.unparse(base) for base in old_owner.bases] != ['unittest.TestCase']: return False
        protected = {'assertEqual', 'assertTrue', 'assertFalse', 'assertIn', 'assertNotIn'}
        if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in protected
               for node in old_owner.body): return False
        reports = [node for node in old_owner.body if isinstance(node, ast.FunctionDef) and node.name == 'report']
        if (len(reports) != 1 or len(reports[0].body) != 1 or not isinstance(reports[0].body[0], ast.Return)
                or ast.unparse(reports[0].body[0].value) != 'validator.validate_docs(self.root, self.tracked, require_documents=False)'):
            return False
        prior = {node.name for node in old_owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        additions = [node for node in new_owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name not in prior]
        if not additions or len({item.name for item in additions}) != len(additions): return False
        for method in additions:
            if (not isinstance(method, ast.FunctionDef) or not method.name.startswith('test_')
                    or method.decorator_list or method.returns is not None
                    or len(method.args.args) != 1 or method.args.args[0].arg != 'self'
                    or method.args.vararg or method.args.kwarg or method.args.kwonlyargs or method.args.defaults):
                return False
            allowed = (ast.FunctionDef, ast.arguments, ast.arg, ast.Expr, ast.Assign, ast.Name, ast.Load, ast.Store,
                       ast.Call, ast.Attribute, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript,
                       ast.Compare, ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.UnaryOp, ast.Not)
            for node in ast.walk(method):
                if not isinstance(node, allowed): return False
                if isinstance(node, ast.Name) and node.id not in {'self', 'report'}: return False
                if isinstance(node, ast.Attribute) and not (isinstance(node.value, ast.Name) and node.value.id == 'self'
                        and node.attr in {'report', 'assertEqual', 'assertTrue', 'assertFalse', 'assertIn', 'assertNotIn'}):
                    return False
                if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Attribute) or node.keywords): return False
        scrubbed = copy.deepcopy(new)
        owner = next(node for node in scrubbed.body if isinstance(node, ast.ClassDef)
                     and node.name == 'DocumentationValidationTests')
        names = {method.name for method in additions}
        owner.body = [node for node in owner.body if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                      or node.name not in names]
        return ast.dump(old, include_attributes=False) == ast.dump(scrubbed, include_attributes=False)
    except (SyntaxError, ValueError, TypeError, StopIteration):
        return False


def resolved_dynamic_exclusions(root: Path, candidate: str, unresolved: set[str]) -> set[str]:
    """Prove three documented dynamic loader families cannot consume a candidate.

    Unrecognized source shapes remain unresolved. This is deliberately a
    targeted control over loader inputs, not a hash of their containing files.
    """
    root = root.resolve(strict=True)
    resolved = set()
    def dynamic_count(tree):
        aliases = {'__import__', 'eval', 'exec', 'importlib.import_module', 'importlib.util.spec_from_file_location'}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'importlib':
                aliases.update(alias.asname or alias.name for alias in node.names if alias.name == 'import_module')
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'importlib' and alias.asname:
                        aliases.update({alias.asname + '.import_module', alias.asname + '.util.spec_from_file_location'})
        return sum(isinstance(node, ast.Call) and ast.unparse(node.func) in aliases for node in ast.walk(tree))
    transaction = 'tools/compile_transaction_guests.py'
    if transaction in unresolved:
        tree = ast.parse((root / transaction).read_text(encoding='utf-8'))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'importlib.import_module']
        assignments = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'owner' for t in n.targets)]
        stores = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == 'owner' and isinstance(n.ctx, ast.Store)]
        if (dynamic_count(tree) == 1 and len(calls) == len(assignments) == len(stores) == 1 and len(calls[0].args) == 1
                and isinstance(calls[0].args[0], ast.Name) and calls[0].args[0].id == 'owner'
                and isinstance(assignments[0].value, ast.Subscript)
                and isinstance(assignments[0].value.value, ast.Dict)
                and isinstance(assignments[0].value.slice, ast.Name) and assignments[0].value.slice.id == 'language'):
            values = assignments[0].value.value.values
            names = [v.value for v in values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            if len(names) == len(values) and all(n.startswith('tools.') for n in names):
                targets = {n.replace('.', '/') + '.py' for n in names}
                if candidate not in targets: resolved.add(transaction)
    dotnet = 'tools/dotnet_guest_bindings.py'
    if dotnet in unresolved:
        tree = ast.parse((root / dotnet).read_text(encoding='utf-8'))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and ast.unparse(n.func) == 'importlib.util.spec_from_file_location']
        function = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'async_export_support'), None)
        if function is not None:
            stores = [n for n in ast.walk(function) if isinstance(n, ast.Name) and n.id == 'path' and isinstance(n.ctx, ast.Store)]
            assignments = [n for n in ast.walk(function) if isinstance(n, ast.Assign)
                           and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'path']
            expected = "Path(__file__).resolve().parent / 'dotnet_guest/async_exports.py'"
            if (dynamic_count(tree) == 1 and len(calls) == len(stores) == len(assignments) == 1 and len(calls[0].args) >= 2
                    and isinstance(calls[0].args[1], ast.Name) and calls[0].args[1].id == 'path'
                    and ast.unparse(assignments[0].value) == expected
                    and candidate != 'tools/dotnet_guest/async_exports.py'):
                resolved.add(dotnet)
    return resolved


def java_loader_excludes(root: Path, candidate: str) -> bool:
    """Recognize fixed SDK-helper suffixes and isolated temporary test files."""
    import os
    root = root.resolve(strict=True)
    owner = root / 'tools/java_guest/compiler.py'
    try:
        tree = ast.parse(owner.read_text(encoding='utf-8'))
        dynamic = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and ast.unparse(node.func) in {'importlib.util.spec_from_file_location', 'importlib.import_module', '__import__', 'eval', 'exec'}]
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'source_module')
        if (len(dynamic) != 1 or dynamic[0] not in list(ast.walk(function))
                or len(dynamic[0].args) < 2 or not isinstance(dynamic[0].args[1], ast.Name)
                or dynamic[0].args[1].id != 'path'):
            return False
        checked = 0
        for area in ('tools', 'sdk'):
            directory = root / area
            if not directory.is_dir() or directory.is_symlink(): return False
            for folder, dirs, files in os.walk(directory, followlinks=False):
                if any((Path(folder) / item).is_symlink() for item in dirs): return False
                dirs[:] = [name for name in dirs if name not in {'__pycache__', 'target', 'node_modules', '.git'}]
                for name in files:
                    if not name.endswith('.py'): continue
                    path = Path(folder) / name
                    if path.relative_to(root).as_posix() in {'tools/ci_tool_graph.py', 'tools/tests/test_ci_tool_graph.py'}:
                        continue
                    if path.is_symlink(): return False
                    with path.open('rb') as source: data = source.read(MAX_SOURCE_BYTES + 1)
                    if len(data) > MAX_SOURCE_BYTES: return False
                    if b'source_module' not in data: continue
                    parsed = ast.parse(data.decode('utf-8-sig'))
                    parents = {child: node for node in ast.walk(parsed) for child in ast.iter_child_nodes(node)}
                    aliases = {'source_module'}
                    for item in ast.walk(parsed):
                        if isinstance(item, ast.ImportFrom):
                            aliases.update(alias.asname or alias.name for alias in item.names if alias.name == 'source_module')
                        if isinstance(item, ast.Constant) and item.value == 'source_module':
                            parent = parents.get(item)
                            # A unittest mock explicitly replaces the loader;
                            # all other reflective references remain unresolved.
                            if not (isinstance(parent, ast.Call) and ast.unparse(parent.func) == 'patch.object'
                                    and len(parent.args) >= 2 and parent.args[1] is item
                                    and any(k.arg == 'return_value' for k in parent.keywords)):
                                return False
                    for item in ast.walk(parsed):
                        if ((isinstance(item, ast.Name) and item.id in aliases and isinstance(item.ctx, ast.Load))
                                or (isinstance(item, ast.Attribute) and item.attr == 'source_module' and isinstance(item.ctx, ast.Load))):
                            parent = parents.get(item)
                            if not isinstance(parent, ast.Call) or parent.func is not item or len(parent.args) != 1:
                                return False
                            argument = parent.args[0]
                            suffix = argument.right.value if (isinstance(argument, ast.BinOp)
                                and isinstance(argument.op, ast.Div) and isinstance(argument.right, ast.Constant)
                                and isinstance(argument.right.value, str)) else None
                            if suffix is None and path.relative_to(root).as_posix() == 'sdk/java-guest/tests/test_projects.py' and isinstance(argument, ast.Name):
                                stores = [n for n in ast.walk(parsed) if isinstance(n, ast.Name)
                                          and n.id == argument.id and isinstance(n.ctx, ast.Store)]
                                assignments = [n for n in ast.walk(parsed) if isinstance(n, ast.Assign)
                                               and len(n.targets) == 1 and isinstance(n.targets[0], ast.Tuple)
                                               and isinstance(n.value, ast.Tuple)]
                                for assignment in assignments:
                                    for target, value in zip(assignment.targets[0].elts, assignment.value.elts):
                                        if (isinstance(target, ast.Name) and target.id == argument.id
                                                and isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div)
                                                and isinstance(value.right, ast.Constant) and isinstance(value.right.value, str)
                                                and len(stores) == 1):
                                            suffix = value.right.value
                            if not suffix or Path(suffix).name == Path(candidate).name:
                                return False
                            checked += 1
        return checked > 0
    except (OSError, UnicodeError, SyntaxError, ValueError, StopIteration):
        return False


def sdk_dynamic_excludes(root: Path, candidate: str) -> bool:
    """Reject SDK loader sites unless their file target is a fixed other basename."""
    import os
    root = root.resolve(strict=True)
    directory = root / 'sdk'
    if not directory.is_dir() or directory.is_symlink(): return False
    token = candidate.removesuffix('.py').replace('/', '.')
    try:
        for folder, dirs, files in os.walk(directory, followlinks=False):
            if any((Path(folder) / item).is_symlink() for item in dirs): return False
            dirs[:] = [name for name in dirs if name not in {'__pycache__', 'target', 'node_modules', '.git'}]
            for name in files:
                if not name.endswith('.py'): continue
                path = Path(folder) / name
                if path.is_symlink(): return False
                with path.open('rb') as source: data = source.read(MAX_SOURCE_BYTES + 1)
                if len(data) > MAX_SOURCE_BYTES: return False
                text = data.decode('utf-8-sig')
                if token in text or candidate in text: return False
                if not any(value in text for value in ('importlib', '__import__', 'exec(', 'eval(')): continue
                tree = ast.parse(text)
                aliases = {'__import__', 'eval', 'exec', 'importlib.import_module', 'importlib.util.spec_from_file_location'}
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module == 'importlib':
                        aliases.update(alias.asname or alias.name for alias in node.names if alias.name == 'import_module')
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == 'importlib' and alias.asname:
                                aliases.update({alias.asname + '.import_module', alias.asname + '.util.spec_from_file_location'})
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call): continue
                    call = ast.unparse(node.func)
                    if call not in aliases: continue
                    if call.endswith('spec_from_file_location') and len(node.args) >= 2:
                        value = node.args[1]
                        if (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div)
                                and isinstance(value.right, ast.Constant) and isinstance(value.right.value, str)
                                and Path(value.right.value).name != Path(candidate).name):
                            continue
                    if call in {'__import__', 'importlib.import_module'} and node.args and isinstance(node.args[0], ast.Constant):
                        if node.args[0].value != token: continue
                    return False
        return True
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return False


def pull_request_paths(text: str) -> list[str] | None | bool:
    """Read the narrow conventional event-filter subset; unknown YAML raises."""
    import json
    if text.lstrip().startswith('{'):
        # YAML permits comments in otherwise JSON-shaped workflow files.
        clean, quoted, escaped, comment = [], False, False, False
        for char in text:
            if comment:
                if char == '\n': comment = False; clean.append(char)
                continue
            if not quoted and char == '#': comment = True; continue
            clean.append(char)
            if quoted and char == '\\' and not escaped: escaped = True; continue
            if char == '"' and not escaped: quoted = not quoted
            escaped = False
        document = json.loads(''.join(clean))
        on = document.get('on')
        if not isinstance(on, dict): raise ValueError('unknown-workflow-trigger')
        if 'pull_request' not in on: return False
        event = on['pull_request']
        if event is None: return None
        if not isinstance(event, dict): raise ValueError('unknown-pull-request-trigger')
        if 'paths' not in event: return None
        values = event['paths']
        if not isinstance(values, list) or not values or any(not isinstance(x, str) or not x for x in values):
            raise ValueError('unknown-path-filter')
        return values
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r'''(?:on|'on'|"on"):\s*''', line)]
    if len(starts) != 1: raise ValueError('unknown-workflow-trigger')
    block = []
    for line in lines[starts[0] + 1:]:
        if line and not line[0].isspace() and not line.startswith('#'): break
        block.append(line)
    events = [i for i, line in enumerate(block) if re.fullmatch(r'  pull_request:\s*(?:#.*)?', line)]
    if not events:
        if any(re.match(r"\s+['\"]?pull_request\b", line) for line in block): raise ValueError('unknown-pull-request-trigger')
        return False
    if len(events) != 1: raise ValueError('duplicate-pull-request-trigger')
    event = []
    for line in block[events[0] + 1:]:
        if re.match(r'^  [A-Za-z_][A-Za-z0-9_-]*:', line): break
        event.append(line)
    path_lines = [i for i, line in enumerate(event) if re.match(r'^    paths:', line)]
    if not path_lines: return None  # unfiltered PR workflow
    if len(path_lines) != 1: raise ValueError('duplicate-path-filter')
    line = event[path_lines[0]].split(':', 1)[1].strip()
    values = []
    if line:
        if not (line.startswith('[') and line.endswith(']')): raise ValueError('unknown-path-filter')
        values = [value.strip().strip("'\"") for value in line[1:-1].split(',')]
    else:
        for item in event[path_lines[0] + 1:]:
            if re.match(r'^    [A-Za-z_][A-Za-z0-9_-]*:', item): break
            if not item.strip() or item.lstrip().startswith('#'): continue
            match = re.fullmatch(r"\s{6}-\s+(['\"]?)([^'\"#]+)\1\s*(?:#.*)?", item)
            if not match: raise ValueError('unknown-path-entry')
            values.append(match.group(2).strip())
    if not values or any(not value or any(char in value for char in '{}[]&*?') and value != '**'
                         for value in values):
        # Standard glob wildcards are allowed below; YAML metacharacters are not.
        if not values or any(not value or any(char in value for char in '{}[]&') for value in values):
            raise ValueError('unknown-path-filter')
    return values


def workflow_triggers_are_scoped(root: Path, candidate: str) -> bool:
    import fnmatch
    allowed = {'ci.yml', 'security-baseline.yml', 'intellij.yml', 'c-guest-authoring.yml',
               'java-guest-feasibility.yml', 'rust-capsule-authoring.yml'}
    try:
        directory = root / '.github/workflows'
        if not directory.is_dir() or directory.is_symlink(): return False
        for path in sorted(directory.iterdir()):
            if path.suffix not in {'.yml', '.yaml'}: continue
            if path.is_symlink() or path.stat().st_size > MAX_SOURCE_BYTES: return False
            filters = pull_request_paths(path.read_text(encoding='utf-8'))
            if filters is False: continue
            triggered = filters is None or any(not pattern.startswith('!') and fnmatch.fnmatchcase(candidate, pattern)
                                               for pattern in filters)
            if triggered and path.name not in allowed: return False
        return True
    except (OSError, UnicodeError, ValueError):
        return False


def qualification_roots(root: Path, graph: ToolGraph) -> set[str]:
    """Collect direct Python/shell owners and SDK Python imports from current sources."""
    import os
    root = root.resolve(strict=True)
    modules = {module_name(path): path for path in graph.imports if path.endswith('.py')}
    packages = {'.'.join(name.split('.')[:index]) for name in modules for index in range(1, len(name.split('.')))}
    roots, shells = set(), []
    def add_module(name):
        if not name.startswith('tools.'): return
        original = name
        while name.startswith('tools.'):
            if name in modules:
                roots.add(modules[name]); return
            if name in packages: return
            name = name.rpartition('.')[0]
        raise ValueError('unknown-tool-module:' + original)
    def inspect_text(text):
        for name in re.findall(r'(?<![A-Za-z0-9_./-])tools/[A-Za-z0-9_./-]+\.py\b', text):
            if name not in graph.imports: raise ValueError('unknown-tool-script:' + name)
            roots.add(name)
        for name in re.findall(r'(?<![A-Za-z0-9_./-])tools/[A-Za-z0-9_./-]+\.sh\b', text):
            if name not in shells: shells.append(name)
        for name in re.findall(r'\btools(?:\.[A-Za-z_][A-Za-z0-9_]*)+', text): add_module(name)
    for workflow in ('c-guest-authoring.yml', 'java-guest-feasibility.yml', 'rust-capsule-authoring.yml'):
        path = root / '.github/workflows' / workflow
        if path.is_symlink() or not path.is_file(): raise ValueError('missing-qualification-workflow')
        inspect_text(path.read_text(encoding='utf-8'))
    scanned = set()
    while shells:
        name = shells.pop()
        if name in scanned: continue
        scanned.add(name)
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('missing-tool-shell')
        inspect_text(path.read_text(encoding='utf-8'))
    for folder, dirs, files in os.walk(root / 'sdk', followlinks=False):
        if any((Path(folder) / name).is_symlink() for name in dirs): raise ValueError('linked-sdk-directory')
        dirs[:] = [name for name in dirs if name not in {'__pycache__', 'target', 'node_modules', '.git'}]
        for name in files:
            if not name.endswith('.py'): continue
            path = Path(folder) / name
            if path.is_symlink() or path.stat().st_size > MAX_SOURCE_BYTES: raise ValueError('unsafe-sdk-source')
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names: add_module(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    add_module(node.module)
                    for alias in node.names: add_module(node.module + '.' + alias.name)
    return roots


def forward_dependencies(graph: ToolGraph, roots: set[str]) -> set[str]:
    reached = set(roots)
    while True:
        dependencies = set().union(*(graph.imports.get(name, frozenset()) for name in reached))
        if dependencies <= reached: return reached
        reached |= dependencies


def isolated_qualification_scope(root: Path, candidate: str) -> tuple[bool, str]:
    """Prove a single documented test owner has no SDK qualification consumers."""
    if candidate != 'tools/tests/test_validate_docs.py': return False, 'unowned-tooling-path'
    try:
        if not workflow_triggers_are_scoped(root, candidate): return False, 'unresolved-workflow-trigger'
        if not sdk_dynamic_excludes(root, candidate): return False, 'unresolved-sdk-loader'
        graph = observe(root)
        roots = qualification_roots(root, graph)
        reachable = forward_dependencies(graph, roots)
        unknown = set(graph.unresolved & reachable)
        unknown -= resolved_dynamic_exclusions(root, candidate, unknown)
        java = 'tools/java_guest/compiler.py'
        if java in unknown and java_loader_excludes(root, candidate): unknown.remove(java)
        if unknown: return False, 'unresolved-qualification-loader'
        if graph.dependents({candidate}) & reachable: return False, 'qualification-consumer'
        return True, 'documentation-validator-tests'
    except (OSError, UnicodeError, SyntaxError, ValueError, KeyError, TypeError):
        return False, 'tool-dependency-graph-unavailable'
