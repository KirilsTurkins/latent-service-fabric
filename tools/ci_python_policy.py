"""Compare test-suppression controls with a source baseline, without case catalogues.

This scanner describes only constructs that can suppress unittest discovery or
results. It does not approve changes and does not compare ordinary helper bodies.
"""
from __future__ import annotations

import ast
from collections import Counter

SUPPRESSION = frozenset({'skip', 'skipIf', 'skipUnless', 'skipTest', 'SkipTest', 'expectedFailure'})
FLAGS = frozenset({'__unittest_skip__', '__unittest_skip_why__', '__unittest_expecting_failure__'})
# Narrow controls that protect the required aggregate and suppression policy.
REQUIRED_CONTROLS = frozenset({
    'test_ci_result.ResultTests.test_every_failure_cancellation_and_unexpected_skip_is_fatal',
    'test_ci_result.ResultTests.test_missing_jobs_and_outputs_cannot_be_success',
    'test_ci_result.ResultTests.test_declared_expected_set_is_not_trusted',
    'test_ci_contracts.ContractTests.test_setup_module_hooks_and_unittest_skip_flags_need_explicit_review',
    'test_ci_contracts.ContractTests.test_new_skips_expected_failures_and_class_guards_fail',
    'test_ci_python_policy.PythonExecutionReceiptTests.test_discovery_execution_skips_and_failures_are_observed',
})


def controls(source: str) -> Counter[str]:
    """Return a multiset so duplicate new suppressions cannot reuse an old one."""
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    aliases = {name for name in SUPPRESSION}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {'unittest', 'unittest.case'}:
            aliases.update(alias.asname or alias.name for alias in node.names if alias.name in SUPPRESSION)

    def token(node: ast.AST) -> str:
        if isinstance(node, ast.Name): return node.id
        if isinstance(node, ast.Attribute): return node.attr
        return ''

    def predicate_context(node: ast.AST) -> list[ast.AST]:
        predicates = []
        parent = parents.get(node)
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if isinstance(parent, (ast.If, ast.IfExp, ast.While)):
                predicates.append(parent.test)
            parent = parents.get(parent)
        return predicates

    found: Counter[str] = Counter()
    dependencies: set[str] = set()
    local_dependencies: dict[ast.AST, set[str]] = {}
    predicate_helpers: set[str] = set()
    for node in ast.walk(tree):
        # A nested class inside a test is a test fixture, not a discoverable
        # top-level unittest class. Its sample decorators are ordinary data.
        ancestor = parents.get(node)
        nested_class = False
        while ancestor is not None and not isinstance(ancestor, ast.Module):
            if isinstance(ancestor, ast.ClassDef) and isinstance(parents.get(ancestor), (ast.FunctionDef, ast.AsyncFunctionDef)):
                nested_class = True
                break
            ancestor = parents.get(ancestor)
        if nested_class:
            continue
        sensitive = False
        if isinstance(node, ast.Call) and token(node.func) in aliases:
            sensitive = True
        elif isinstance(node, (ast.Name, ast.Attribute)) and token(node) in aliases:
            # Bare decorators, including aliases, must not bypass call scanning.
            parent = parents.get(node)
            sensitive = isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node in parent.decorator_list
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            sensitive = any(isinstance(item, (ast.Name, ast.Attribute)) and token(item) in FLAGS
                            for target in targets for item in ast.walk(target))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parent = parents.get(node)
            sensitive = (isinstance(parent, ast.Module) and node.name == 'load_tests') or (
                isinstance(parent, ast.ClassDef) and node.name in {'run', '_callTestMethod', '__call__'}
                and any(token(base) in {'TestCase', 'IsolatedAsyncioTestCase'} for base in parent.bases))
        if sensitive:
            signature = ast.dump(node, include_attributes=False)
            predicates = predicate_context(node)
            for predicate in predicates:
                predicate_helpers.update(token(call.func) for call in ast.walk(predicate)
                                         if isinstance(call, ast.Call) and token(call.func))
            if isinstance(node, ast.Call) and token(node.func) in {'skipIf', 'skipUnless'}:
                for argument in node.args[:1]:
                    predicate_helpers.update(token(call.func) for call in ast.walk(argument)
                                             if isinstance(call, ast.Call) and token(call.func))
            found[repr((signature, [ast.dump(value, include_attributes=False) for value in predicates]))] += 1
            names = {item.id for value in [node, *predicates] for item in ast.walk(value)
                     if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}
            dependencies.update(names)
            scope = parents.get(node)
            while scope is not None and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                scope = parents.get(scope)
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local_dependencies.setdefault(scope, set()).update(names)
    # Bind only assignments used in a suppression condition, including its
    # transitive local/module names. Unrelated helper bodies remain free to vary.
    def bind(scope, names, label):
        candidates = []
        for statement in ast.walk(scope):
            if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)): continue
            ancestor = parents.get(statement)
            while ancestor is not None and not isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                ancestor = parents.get(ancestor)
            if ancestor is scope: candidates.append(statement)
        seen = set()
        while True:
            changed = False
            for statement in candidates:
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                assigned = {item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name)}
                if not assigned & names or id(statement) in seen: continue
                seen.add(id(statement)); changed = True
                found[label + ':' + ast.dump(statement, include_attributes=False)] += 1
                names.update(item.id for item in ast.walk(statement) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load))
            if not changed: break
    for scope, names in local_dependencies.items():
        bind(scope, names, 'local-binding')
        dependencies.update(names)
    bind(tree, dependencies, 'module-binding')
    # A pre-existing skip must not become active merely because a local
    # predicate helper changed. Bind only helpers reachable from a suppression
    # predicate, not ordinary setup or fixture helpers.
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parent = parents.get(node)
            if isinstance(parent, (ast.Module, ast.ClassDef)):
                functions.setdefault(node.name, []).append(node)
    seen_helpers = set()
    while predicate_helpers - seen_helpers:
        name = min(predicate_helpers - seen_helpers)
        seen_helpers.add(name)
        for helper in functions.get(name, []):
            found['suppression-predicate-helper:' + ast.dump(helper, include_attributes=False)] += 1
            predicate_helpers.update(token(call.func) for call in ast.walk(helper)
                                     if isinstance(call, ast.Call) and token(call.func))
    return found


def require_no_new_controls(before: str, after: str) -> None:
    if controls(after) - controls(before):
        raise ValueError('new-python-test-suppression-requires-review')
    def test_classes(source):
        tree = ast.parse(source)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        classes = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef): continue
            bases = [ast.unparse(base) for base in node.bases]
            if not any(base.rsplit('.', 1)[-1] in {'TestCase', 'IsolatedAsyncioTestCase'} for base in bases): continue
            parent = parents.get(node)
            contexts = []
            while parent is not None and not isinstance(parent, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
                if isinstance(parent, (ast.If, ast.While)):
                    contexts.append(ast.dump(parent.test, include_attributes=False))
                parent = parents.get(parent)
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            if node.name in classes: raise ValueError('duplicate-python-test-class')
            classes[node.name] = (bases, contexts)
        return classes
    previous, current = test_classes(before), test_classes(after)
    if any(current.get(name) != value for name, value in previous.items()):
        raise ValueError('python-test-class-discovery-changed')



def imported_skip_predicates(source: str) -> set[tuple[str, str]]:
    """Find repository functions directly reachable from a skip predicate."""
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    aliases = {name: name for name in SUPPRESSION}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {'unittest', 'unittest.case'}:
            aliases.update({alias.asname or alias.name: alias.name for alias in node.names if alias.name in SUPPRESSION})
    called = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call): continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ''
        name = aliases.get(name, name)
        if name not in SUPPRESSION: continue
        predicates = list(node.args[:1]) if name in {'skipIf', 'skipUnless'} else []
        parent = parents.get(node)
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if isinstance(parent, (ast.If, ast.IfExp, ast.While)): predicates.append(parent.test)
            parent = parents.get(parent)
        called.update(ast.unparse(call.func) for predicate in predicates for call in ast.walk(predicate)
                      if isinstance(call, ast.Call))
    expanded = set()
    while called - expanded:
        name = min(called - expanded); expanded.add(name)
        if name in functions:
            called.update(ast.unparse(call.func) for call in ast.walk(functions[name]) if isinstance(call, ast.Call))
    result = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and not node.level and node.module == 'tools':
            for alias in node.names:
                prefix = alias.asname or alias.name
                for name in called:
                    if alias.name.isidentifier() and name.startswith(prefix + '.') and name[len(prefix)+1:].isidentifier():
                        result.add(('tools/' + alias.name + '.py', name[len(prefix)+1:]))
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module and node.module.startswith('tools.'):
            for alias in node.names:
                if (alias.asname or alias.name) in called and alias.name.isidentifier():
                    result.add((node.module.replace('.', '/') + '.py', alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith('tools.'):
                    prefix = alias.asname or alias.name
                    for name in called:
                        if name.startswith(prefix + '.') and name[len(prefix)+1:].isidentifier():
                            result.add((alias.name.replace('.', '/') + '.py', name[len(prefix)+1:]))
    return result


def guard_imported_skip_predicates(repo, baseline, sources):
    """Reject changed repository helpers that can activate an existing skip."""
    from tools import ci_profile, ci_contracts
    from pathlib import Path
    repo = Path(repo)
    changed = ci_profile.diff_paths(ci_profile.git_command(repo, 'diff', '--no-ext-diff', '--no-textconv',
                                                           '--name-only', '-z', '--no-renames', baseline, '--'))
    changed = {path for path in changed if path.startswith('tools/') and path.endswith('.py')}
    if not changed: return
    relevant = set().union(*(imported_skip_predicates(source) for source in sources.values()))
    for path, function in sorted(relevant):
        if path not in changed: continue
        previous = ci_profile.git_command(repo, 'show', baseline + ':' + path, allow_failure=True)
        if previous is None: raise ValueError('new-python-test-suppression-requires-review')
        current = ci_contracts.safe_path(repo, path).read_bytes()
        if len(previous) > 1024 * 1024 or len(current) > 1024 * 1024:
            raise ValueError('python-policy-source-limit')
        def reachable(raw):
            tree = ast.parse(raw.decode('utf-8-sig'))
            definitions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            pending, seen = {function}, set()
            while pending - seen:
                name = min(pending - seen); seen.add(name)
                if name not in definitions: raise ValueError('new-python-test-suppression-requires-review')
                pending.update(call.func.id for call in ast.walk(definitions[name])
                               if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                               and call.func.id in definitions)
            result = {name: ast.dump(definitions[name], include_attributes=False) for name in seen}
            dependencies = {item.id for name in seen for item in ast.walk(definitions[name])
                            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}
            bindings = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))]
            included = set()
            while True:
                added = False
                for node in bindings:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    assigned = {item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name)}
                    if not assigned & dependencies or id(node) in included: continue
                    included.add(id(node)); added = True
                    result['binding:' + ast.dump(node, include_attributes=False)] = ''
                    dependencies.update(item.id for item in ast.walk(node)
                                        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load))
                if not added: break
            return result
        if reachable(previous) != reachable(current):
            raise ValueError('new-python-test-suppression-requires-review')


def flatten_suite(suite):
    """Freeze the identities returned by unittest discovery before execution."""
    import unittest
    cases = []
    def visit(item):
        if isinstance(item, unittest.TestSuite):
            for child in item: visit(child)
        elif isinstance(item, unittest.TestCase):
            cases.append(item.id())
        else:
            raise ValueError('unknown-python-test-object')
    visit(suite)
    if not cases or len(cases) != len(set(cases)):
        raise ValueError('empty-or-duplicate-python-discovery')
    return sorted(cases)


def recording_result_class(allowed_skip):
    """Construct a standard unittest result with explicit skip authorization."""
    import unittest
    class RecordingResult(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.observed = {}
            self.unauthorized = []
        def record(self, test, status):
            identity = test.id()
            if identity in self.observed:
                self.unauthorized.append('duplicate:' + identity)
            self.observed[identity] = status
        def addSuccess(self, test):
            self.record(test, 'passed'); super().addSuccess(test)
        def addFailure(self, test, err):
            self.record(test, 'failed'); super().addFailure(test, err)
        def addError(self, test, err):
            self.record(test, 'failed'); super().addError(test, err)
        def addSkip(self, test, reason):
            self.record(test, 'skipped')
            if not allowed_skip(test.id(), reason): self.unauthorized.append('skip:' + test.id())
            super().addSkip(test, reason)
        def addExpectedFailure(self, test, err):
            self.record(test, 'failed'); self.unauthorized.append('expected-failure:' + test.id())
            super().addExpectedFailure(test, err)
        def addUnexpectedSuccess(self, test):
            self.record(test, 'failed'); super().addUnexpectedSuccess(test)
    return RecordingResult


def execution_receipt(discovered, result, *, source_identity, recipe_identity):
    """Fail closed if any discovered test was omitted, duplicated, or failed."""
    if not isinstance(source_identity, dict) or not source_identity.get('revision') or not recipe_identity:
        raise ValueError('missing-python-execution-identity')
    observed = dict(result.observed)
    # unittest reports a skipped class/module fixture as one synthetic holder,
    # not as one event for each discovered case. Expand it only after the
    # caller has independently authorized that fixture skip.
    for holder, status in list(observed.items()):
        if status != 'skipped': continue
        for prefix in ('setUpClass (', 'setUpModule ('):
            if holder.startswith(prefix) and holder.endswith(')'):
                owner = holder[len(prefix):-1] + '.'
                members = [case for case in discovered if case.startswith(owner)]
                if members:
                    del observed[holder]
                    for case in members:
                        if case in observed: result.unauthorized.append('duplicate:' + case)
                        observed[case] = 'skipped'
                break
    unmatched = set(observed) ^ set(discovered)
    errors = list(result.unauthorized)
    if unmatched: errors.append('discovery-execution-mismatch')
    if not result.wasSuccessful() or 'failed' in observed.values(): errors.append('test-failure')
    return {'source': source_identity, 'recipe': recipe_identity,
            'discovered': sorted(discovered),
            'executed': sorted(name for name, value in observed.items() if value in {'passed', 'failed'}),
            'skipped': sorted(name for name, value in observed.items() if value == 'skipped'),
            'failed': sorted(name for name, value in observed.items() if value == 'failed'),
            'errors': errors}


def permitted_skip(before_source: str, class_name: str | None, method_name: str | None, reason: str) -> bool:
    """Accept a runtime skip only when its own baseline fixture declares its reason."""
    import re
    tree = ast.parse(before_source)
    scopes = [node for node in tree.body
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'setUpModule']
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    if class_name is not None and len(classes) != 1:
        return False
    if classes:
        owner = classes[0]
        scopes.extend(owner.decorator_list)
        scopes.extend(node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and node.name in {'setUp', 'setUpClass', method_name})
    # Follow direct calls to module-local prerequisite helpers, without
    # authorizing unrelated skip declarations elsewhere in the module.
    helpers = {node.name: node for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('test_')}
    visited = set()
    for scope in scopes:
        for node in ast.walk(scope):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                name = node.func.id
                if name in helpers and name not in visited:
                    visited.add(name)
                    scopes.append(helpers[name])
    for scope in scopes:
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call): continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
            if name not in SUPPRESSION: continue
            for value in node.args:
                if isinstance(value, ast.Constant) and value.value == reason:
                    return True
                if isinstance(value, ast.JoinedStr) and len(reason) <= 4096:
                    parts = [re.escape(part.value) if isinstance(part, ast.Constant) and isinstance(part.value, str)
                             else r'.*' for part in value.values]
                    if re.fullmatch(''.join(parts), reason, re.DOTALL):
                        return True
    return False


def run_discovered(suite, *, baseline_sources, current_sources, source_identity, recipe_identity, stream):
    """Execute a suite selected by the existing owner and return its receipt."""
    import re
    import unittest
    if set(baseline_sources) != set(current_sources):
        raise ValueError('missing-python-policy-source')
    for module in sorted(current_sources):
        if baseline_sources[module].replace('\r\n', '\n') != current_sources[module].replace('\r\n', '\n'):
            require_no_new_controls(baseline_sources[module], current_sources[module])
    discovered = flatten_suite(suite)
    def allowed(identity, reason):
        holder = re.fullmatch(r'(setUpClass|setUpModule) \(([^)]+)\)', identity)
        try:
            if holder and holder.group(1) == 'setUpModule':
                module, owner, method = holder.group(2), None, None
            elif holder:
                module, owner = holder.group(2).rsplit('.', 1)
                method = None
            else:
                module, owner, method = identity.rsplit('.', 2)
            # A test class imported by another module retains its qualified
            # original module identity even under bare unittest discovery.
            key = module if module in baseline_sources else module.removeprefix('tools.tests.')
            before = baseline_sources[key]
        except (ValueError, KeyError):
            return False
        return permitted_skip(before, owner, method, reason)
    runner = unittest.TextTestRunner(stream=stream, resultclass=recording_result_class(allowed))
    result = runner.run(suite)
    return execution_receipt(discovered, result, source_identity=source_identity, recipe_identity=recipe_identity)


def source_pairs(repo, baseline_revision: str, module_names):
    """Read current and baseline module sources using bounded offline Git only."""
    import hashlib
    import re
    from pathlib import Path
    from tools import ci_profile, ci_contracts
    repo = Path(repo)
    revision = ci_profile.sha(baseline_revision)
    if not ci_profile.commit_exists(repo, revision):
        raise ValueError('python-policy-baseline-unavailable')
    raw = ci_profile.git_command(repo, 'ls-tree', '-r', '-z', revision, '--', 'tools/tests')
    if raw and not raw.endswith(b'\0'):
        raise ValueError('python-policy-invalid-tree')
    objects = {}
    for entry in raw[:-1].split(b'\0') if raw else []:
        metadata, encoded_name = entry.split(b'\t', 1)
        mode, kind, identity = metadata.split(b' ')
        if mode != b'100644' or kind != b'blob':
            raise ValueError('python-policy-invalid-tree-entry')
        objects[encoded_name.decode('utf-8')] = identity.decode('ascii')
    before, current = {}, {}
    for module in sorted(set(module_names)):
        if re.fullmatch(r'(?:tools\.tests\.)?test_[A-Za-z0-9_]+', module) is None:
            raise ValueError('python-policy-unregistered-module')
        path = 'tools/tests/' + module.rsplit('.', 1)[-1] + '.py'
        with ci_contracts.safe_path(repo, path).open('rb') as source:
            actual = source.read(1024 * 1024 + 1)
        if len(actual) > 1024 * 1024:
            raise ValueError('python-policy-source-limit')
        current[module] = actual.decode('utf-8-sig')
        # Most modules are unchanged. Reuse their bytes only after verifying
        # the Git blob identity; no hundreds of extra Git processes are needed.
        def blob_identity(data):
            blob = b'blob ' + str(len(data)).encode('ascii') + b'\0' + data
            return (hashlib.sha1(blob).hexdigest() if len(revision) == 40 else hashlib.sha256(blob).hexdigest())
        normalized = actual.replace(b'\r\n', b'\n')
        if objects.get(path) == blob_identity(actual):
            prior = actual
        elif objects.get(path) == blob_identity(normalized):
            prior = normalized
        else:
            prior = ci_profile.git_command(repo, 'show', revision + ':' + path) if path in objects else b''
        if len(prior) > 1024 * 1024:
            raise ValueError('python-policy-source-limit')
        before[module] = prior.decode('utf-8-sig')
    return before, current


def execute_python(repo, baseline_revision, *, module=None, case=None, stream=None, required_controls=REQUIRED_CONTROLS):
    """Discover through unittest inside the maintained local-test owner."""
    import hashlib
    import json
    import os
    import re
    import sys
    import unittest
    from pathlib import Path
    from tools import ci_profile
    repo = Path(repo)
    if module is not None and re.fullmatch(r'(?:tools\.tests\.)?test_[A-Za-z0-9_]+', module) is None:
        raise ValueError('invalid-python-module')
    if case is not None and (module is None or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?', case) is None):
        raise ValueError('invalid-python-case')
    before, current = verify_source_tree(repo, baseline_revision,
                                        qualified=bool(module and module.startswith('tools.tests.')))
    identity = python_source_identity(repo)
    if module:
        if module not in current: raise ValueError('unknown-python-module')
        selection = module + ('.' + case if case else '')
        suite = unittest.defaultTestLoader.loadTestsFromName(selection)
    else:
        suite = unittest.defaultTestLoader.discover(str(repo / 'tools/tests'))
    context = {key: value for key, value in os.environ.items() if key.startswith('LSF_REQUIRE_')}
    recipe = hashlib.sha256(json.dumps({'module': module, 'case': case, 'python': sys.version,
                                        'platform': sys.platform, 'requirements': context,
                                        'discovery': 'unittest'}, sort_keys=True).encode()).hexdigest()
    receipt = run_discovered(suite, baseline_sources=before, current_sources=current,
                             source_identity=identity, recipe_identity='sha256:' + recipe,
                             stream=stream or sys.stderr)
    if module is None:
        observed_modules = {name.split('.', 1)[0] for name in receipt['discovered']}
        missing_modules = sorted(set(current) - observed_modules)
        if missing_modules:
            receipt['errors'].append('empty-python-modules:' + ','.join(missing_modules))
        if not required_controls <= set(receipt['executed']):
            receipt['errors'].append('missing-required-python-controls')
    if python_source_identity(repo) != identity:
        receipt['errors'].append('python-source-changed-during-execution')
    return receipt


def python_source_identity(repo):
    """Bind the checked-out commit and tracked changes with bounded offline Git."""
    import hashlib
    from tools import ci_profile
    revision = ci_profile.sha(ci_profile.git_command(repo, 'rev-parse', '--verify', 'HEAD').decode('ascii').strip())
    status = ci_profile.git_command(repo, 'status', '--porcelain=v1', '-z', '--untracked-files=normal')
    if any(entry.startswith(b'?? ') for entry in status.split(b'\0')):
        raise ValueError('untracked-python-source-identity')
    diff = ci_profile.git_command(repo, 'diff', '--binary', 'HEAD', '--')
    return {'revision': revision, 'trackedChangesSha256': hashlib.sha256(diff).hexdigest(),
            'workingTreeModified': bool(status)}


def write_execution_receipt(repo, destination, receipt):
    """Atomically retain bounded observations without overwriting tracked files."""
    import json
    import os
    from pathlib import Path
    import tempfile
    from tools import ci_contracts, ci_profile
    repo = Path(repo).absolute()
    destination = Path(destination)
    destination = destination if destination.is_absolute() else repo / destination
    destination = destination.absolute()
    if not destination.is_relative_to(repo / 'target/ci'):
        raise ValueError('python-receipt-outside-target-ci')
    relative = destination.relative_to(repo).as_posix()
    ci_contracts.safe_path(repo, relative, regular=False)
    tracked = ci_profile.git_command(repo, 'ls-files', '-z', '--', relative)
    if tracked:
        raise ValueError('python-receipt-would-overwrite-source')
    encoded = json.dumps(receipt, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode() + b'\n'
    if len(encoded) > 8 * 1024 * 1024:
        raise ValueError('python-receipt-byte-limit')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(encoded)
        os.replace(temporary, destination)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def event_baseline(event_name, event, head):
    """Choose a GitHub-supplied comparison commit, never a PR-controlled label."""
    from tools.ci_profile import ProfileError, sha
    if event_name == 'pull_request':
        try: value = event['pull_request']['base']['sha']
        except (KeyError, TypeError): raise ValueError('missing-python-policy-base') from None
    elif event_name == 'push':
        try: value = event['before']
        except (KeyError, TypeError): raise ValueError('missing-python-policy-base') from None
    elif event_name == 'workflow_dispatch':
        value = head
    else:
        raise ValueError('unsupported-python-policy-event')
    try: value = sha(value)
    except ProfileError: raise ValueError('invalid-python-policy-base') from None
    if int(value, 16) == 0:
        raise ValueError('missing-python-policy-base')
    return value


def verify_source_tree(repo, baseline_revision, *, qualified=False):
    """Check changed discoverable test modules before importing any of them."""
    import re
    from pathlib import Path
    from tools import ci_profile
    repo = Path(repo)
    if not isinstance(baseline_revision, str) or re.fullmatch(r'HEAD|[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', baseline_revision) is None:
        raise ValueError('invalid-python-policy-baseline')
    raw = ci_profile.git_command(repo, 'rev-parse', '--verify', baseline_revision + '^{commit}')
    baseline = ci_profile.sha(raw.decode('ascii').strip())
    names = sorted(path.stem for path in (repo / 'tools/tests').glob('test_*.py'))
    if not names or len(names) != len(set(names)):
        raise ValueError('empty-or-duplicate-python-modules')
    modules = [('tools.tests.' + name) if qualified else name for name in names]
    before, current = source_pairs(repo, baseline, modules)
    guard_imported_skip_predicates(repo, baseline, current)
    for name in modules:
        if before[name].replace('\r\n', '\n') != current[name].replace('\r\n', '\n'):
            require_no_new_controls(before[name], current[name])
    return before, current


def validate_python_modules(repo):
    """Validate discoverable module paths and duplicate top-level test methods."""
    from pathlib import Path
    from tools import ci_contracts
    repo = Path(repo)
    directory = ci_contracts.safe_path(repo, 'tools/tests', regular=False)
    found = {}
    for path in sorted(directory.glob('test_*.py')):
        relative = path.relative_to(repo).as_posix()
        safe = ci_contracts.safe_path(repo, relative)
        with safe.open('rb') as source: raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024: raise ValueError('python-policy-source-limit')
        tree = ast.parse(raw.decode('utf-8-sig'), filename=relative)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        names = []
        for owner in ast.walk(tree):
            if not isinstance(owner, ast.ClassDef): continue
            ancestor = parents.get(owner)
            nested = False
            while ancestor is not None and not isinstance(ancestor, ast.Module):
                if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    nested = True; break
                ancestor = parents.get(ancestor)
            if nested: continue
            for method in owner.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith('test_'):
                    names.append(owner.name + '.' + method.name)
        if not names or len(names) != len(set(names)):
            raise ValueError('empty-or-duplicate-python-test-module:' + relative)
        found[relative] = sorted(names)
    if not found: raise ValueError('empty-python-test-directory')
    return found
