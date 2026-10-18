"""Detached Rust consent stays explicit, source-bound and private."""
from __future__ import annotations

import copy
from dataclasses import replace
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import application_dependencies as captures, application_dependency_approval as consumer
from tools import rust_capsule, rust_capsule_build, rust_capsule_project
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical
from tools.dev_workflow import build, build_cache, build_client, cli, common, paths, project, snapshot, state
from tools.dev_workflow import executable_approval as selected, executable_approval_request as viewer
from tools.guest_dependency_inputs import capture_source
from tools.tests import test_application_dependency_approval as approval_tests
from tools.tests.test_dev_contracts import descriptor


A, B = common.digest(b'approval-a'), common.digest(b'approval-b')


def maintained():
    value = descriptor()
    value['inputRoots'] = ['app']
    value['scenarios'] = ['app/tests.json']
    value['build'].update(argv=list(selected.ARGV), workingDirectory='app', outputRoot='output',
        hostTargets=['linux-x86_64'], adapter={'language': 'rust', 'ownerIssue': 544, 'version': '1'},
        inventory={'path': 'guest-tools.json', 'sha256': A}, tools=[
            {'name': 'python', 'path': 'sdk/bin/python', 'version': '3.13.5', 'sha256': common.digest(b'python')},
            {'name': 'recipe', 'path': 'recipe/tools/dev_guest_recipe.py', 'version': '1', 'sha256': common.digest(b'adapter')}])
    return project.validate(value)


class DetachedSelection(unittest.TestCase):
    def test_default_cache_identity_is_byte_identical_and_selected_keys_are_isolated(self):
        value, record = maintained(), {'identity': common.digest(b'source')}
        recipe, host, packager = project.trust_identity(value), 'linux-x86_64', common.digest(b'packager')
        original = common.digest(common.encode({'observationProfile': 'compiler-and-controller-v1',
            'source': record['identity'], 'recipe': recipe, 'tools': value['build']['tools'],
            'hostAbi': value['hostAbi'], 'controllerHostAbi': common.HOST_ABI,
            'host': host, 'target': value['build']['target'], 'packager': packager}))
        self.assertEqual(build_cache.identity(record, value, recipe, host, packager), original)
        self.assertEqual(build_cache.identity(record, value, recipe, host, packager, executable_approval=None), original)
        self.assertEqual(len({original, *(build_cache.identity(record, value, recipe, host, packager,
            executable_approval=identity) for identity in (A, B))}), 3)

    def test_unsupported_custom_duplicate_and_malformed_selections_fail_before_process(self):
        values = []
        for mutate in (lambda v: v.update(language='java'), lambda v: v['build'].pop('adapter'),
                       lambda v: v['build']['argv'].append('--executable-approval=' + A),
                       lambda v: v['build']['argv'].extend(['--executable-approval', A]),
                       lambda v: v['build']['tools'][1].update(path='recipe/custom.py')):
            value = maintained()
            mutate(value)
            values.append(value)
        with patch.object(build.process, 'run', side_effect=AssertionError('process dispatch')):
            for value in values:
                with self.subTest(value=value), self.assertRaisesRegex(common.DevError, 'maintained-rust'):
                    build.compile_recipe(Path('/unused'), Path('/unused'), value, {}, {}, 0, lambda: None, executable_approval=A)
            for value in ('', 'a' * 64, 'sha256:' + 'A' * 64, [], False):
                with self.subTest(value=value), self.assertRaisesRegex(common.DevError, 'invalid-sha256'):
                    selected.selection(maintained(), value)
        self.assertIsNone(selected.selection(descriptor(), None))

    def test_cli_and_rust_watch_reject_duplicate_or_malformed_before_dispatch(self):
        for parser, args in ((cli.parser(), ['dev', 'build', '--workspace', 'test-rust']),
                             (rust_capsule.parser(), ['watch', '.', '--workspace', 'test-rust'])):
            self.assertIsNone(parser.parse_args(args).executable_approval)
            self.assertEqual(parser.parse_args([*args, '--executable-approval', A]).executable_approval, A)
            for extra in (['--executable-approval', 'bad'], ['--executable-approval', A, '--executable-approval', B]):
                with self.subTest(args=args, extra=extra), patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
                    parser.parse_args(args + extra)
        with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
            cli.parser().parse_args(['dev', 'executable-approval-request', '--workspace', 'test-rust', '--path', '/tmp/arbitrary'])

    def test_compiler_gets_only_typed_explicit_option_without_descriptor_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            paths.new_directory(source)
            paths.new_directory(source / 'app')
            value, before = maintained(), None
            before = copy.deepcopy(value)
            tools = {'python': root / 'python', 'recipe': root / 'recipe.py'}
            result = subprocess.CompletedProcess([], 0, common.encode({'schemaVersion': 'latent.dev.compiler-result.v1',
                'language': 'rust', 'ownerIssue': 544, 'cleanup': 'reaped', 'code': 'success'}), b'')
            with patch.object(build.process, 'run', return_value=result) as run:
                build.compile_recipe(root, source, value, {'files': [], 'identity': A}, tools, time.monotonic() + 20,
                                     lambda: None, executable_approval=A)
            self.assertEqual(run.call_args.args[0], [str(tools['python']), '-I', '-B', str(tools['recipe']),
                '--language', 'rust', '--project', '.', '--output', '../output', '--executable-approval', A])
            self.assertEqual(value, before)

    def test_client_forwards_only_explicit_selection_and_rejects_custom_before_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = maintained()
            state.atomic(root, 'trust.json', {'project': str(root), 'recipe': project.trust_identity(value)})
            connection = Mock()
            connection.call.side_effect = lambda operation, *args, **kwargs: {} if operation != 'build' else {'diagnostics': []}
            with patch.object(project, 'load', return_value=(value, A)), patch.object(snapshot, 'observe', return_value=({'identity': B}, {})):
                for approval in (None, A):
                    build_client.run(root, connection, root, '/selected-tools', executable_approval=approval)
                    payload = connection.call.call_args_list[-1].args[1]
                    self.assertEqual(payload.get('executableApproval'), approval)
                    self.assertEqual('executableApproval' in payload, approval is not None)
            connection.reset_mock()
            with patch.object(project, 'load', return_value=(descriptor(), A)), self.assertRaisesRegex(common.DevError, 'maintained-rust'):
                build_client.run(root, connection, root, '/selected-tools', executable_approval=A)
            connection.call.assert_not_called()

    def test_captured_client_rechecks_source_after_transfer_with_distinct_approval_selection(self):
        from tools.dev_workflow import assets, captured_inputs
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = maintained()
            trusted = project.trust_identity(value)
            state.atomic(root, 'trust.json', {'project': str(root), 'recipe': trusted})
            record = {'identity': B, 'capturedInputs': {'fixture': 'controlled-transfer-boundary'}}
            sources = [{'identity': A}]
            for approval in (None, A):
                connection = Mock()
                connection.call.side_effect = lambda operation, *args, **kwargs: (
                    {'diagnostics': []} if operation == 'build' else {})
                with self.subTest(approval=approval), \
                     patch.object(project, 'load', return_value=(value, A)), \
                     patch.object(snapshot, 'observe', return_value=(record, {})), \
                     patch.object(captured_inputs, 'pack', return_value=sources) as pack, \
                     patch.object(assets, 'transfer', return_value={'identity': A}) as transfer, \
                     patch.object(build_client, 'selection', wraps=build_client.selection) as source_selection, \
                     patch.object(selected, 'selection', wraps=selected.selection) as approval_selection, \
                     patch.object(subprocess, 'run', side_effect=AssertionError('process dispatch')), \
                     patch.object(subprocess, 'Popen', side_effect=AssertionError('process dispatch')):
                    result = build_client.run(root, connection, root, '/selected-tools', executable_approval=approval)
                    self.assertEqual(result, {'diagnostics': []})
                    approval_selection.assert_called_once_with(value, approval)
                    source_selection.assert_called_once_with(root)
                    self.assertEqual(pack.call_args.args[:2], (root, record['capturedInputs']))
                    transfer.assert_called_once_with(connection, sources, domain=captured_inputs.DOMAIN)
                    self.assertEqual([call.args[0] for call in connection.call.call_args_list], ['snapshot', 'build'])
                    self.assertEqual(connection.call.call_args_list[0].args[1]['captureAsset'], A)
                    payload = connection.call.call_args_list[1].args[1]
                    self.assertEqual(payload.get('executableApproval'), approval)
                    self.assertEqual('executableApproval' in payload, approval is not None)

    def test_observed_client_rechecks_original_source_selection_after_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = maintained()
            trusted = project.trust_identity(value)
            state.atomic(root, 'trust.json', {'project': str(root), 'recipe': trusted})
            record = {'identity': B}
            for approval in (None, A):
                observed = []
                def call(operation, *args, **kwargs):
                    if operation == 'build':
                        self.assertTrue(callable(kwargs['check']))
                        kwargs['check']()
                        observed.append(operation)
                        return {'diagnostics': []}
                    return {}
                connection = Mock()
                connection.call.side_effect = call
                with self.subTest(approval=approval), \
                     patch.object(project, 'load', return_value=(value, A)), \
                     patch.object(snapshot, 'observe', return_value=(record, {})), \
                     patch.object(build_client, 'selection', wraps=build_client.selection) as source_selection, \
                     patch.object(selected, 'selection', wraps=selected.selection) as approval_selection, \
                     patch.object(subprocess, 'run', side_effect=AssertionError('process dispatch')), \
                     patch.object(subprocess, 'Popen', side_effect=AssertionError('process dispatch')):
                    result = build_client.run(root, connection, root, '/selected-tools',
                                              selected=(trusted, B), executable_approval=approval)
                    self.assertEqual(result, {'diagnostics': []})
                    approval_selection.assert_called_once_with(value, approval)
                    self.assertEqual(source_selection.call_count, 2)
                    self.assertTrue(all(call.args == (root,) for call in source_selection.call_args_list))
                    self.assertEqual(observed, ['build'])
                    self.assertEqual([call.args[0] for call in connection.call.call_args_list], ['snapshot', 'build'])
                    payload = connection.call.call_args_list[1].args[1]
                    self.assertEqual(payload.get('executableApproval'), approval)
                    self.assertEqual('executableApproval' in payload, approval is not None)

    def test_helper_rejects_unsupported_or_null_before_installation_or_session(self):
        # Only import the Linux RPC dispatcher on Windows; its real OS/user
        # entry point is replaced below and no Linux behavior is simulated.
        with patch.dict(sys.modules, {'pwd': Mock()} if os.name == 'nt' else {}):
            from tools.dev_workflow import helper
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value, approval in ((descriptor(), A), (maintained(), None)):
                state.atomic(root, 'project.json', {'descriptor': value})
                with patch.object(helper, 'root_directory', return_value=root), patch.object(state, 'workspace', return_value=root), \
                     patch.object(helper, 'installation', side_effect=AssertionError('installation')), \
                     self.assertRaises(common.DevError):
                    helper.dispatch({'operation': 'build', 'workspace': 'test-rust',
                                     'arguments': {'toolRoot': '/tools', 'buildId': 'a' * 32, 'executableApproval': approval}})

    def test_real_cache_entries_never_cross_none_a_b_or_drop_receipt_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, controller = root / 'source', root / 'controller'
            for path in (source, source / 'app', controller):
                paths.new_directory(path)
            (source / 'app/main.rs').write_bytes(b'fn main() {}')
            value = maintained()
            record, content = snapshot.observe(source, ['app'])
            recipe, attempts = project.trust_identity(value), {}
            for approval in (None, A, B):
                attempt, working, receipt = build_cache.allocate(controller, source, record, value,
                    recipe, 'linux-x86_64', A, executable_approval=approval)
                self.assertIsNone(receipt)
                receipt = {'attempt': attempt.name, 'source': record['identity'], 'recipe': recipe,
                    'buildKey': build_cache.identity(record, value, recipe, 'linux-x86_64', A, executable_approval=approval)}
                if approval is not None:
                    receipt['executableApproval'] = approval
                state.atomic(working, 'build-receipt.json', receipt)
                build_cache.transition(attempt, 'complete')
                attempts[approval] = attempt
            self.assertEqual(len(set(attempts.values())), 3)
            for approval, expected in attempts.items():
                attempt, _working, receipt = build_cache.allocate(controller, source, record, value,
                    recipe, 'linux-x86_64', A, executable_approval=approval)
                self.assertEqual(attempt, expected)
                self.assertEqual(receipt.get('executableApproval'), approval)
            working = attempts[A] / 'source'
            receipt = state.load(working, 'build-receipt.json')
            del receipt['executableApproval']
            state.atomic(working, 'build-receipt.json', receipt)
            with self.assertRaisesRegex(common.DevError, 'cached-executable-approval-mismatch'):
                build_cache.allocate(controller, source, record, value, recipe, 'linux-x86_64', A, executable_approval=A)


class DetachedConsumer(unittest.TestCase):
    def test_identical_captured_request_survives_distinct_owned_roots_and_consumer_rechecks(self):
        project_root, _work, _output, verified, first = approval_tests.ExecutionApproval.fixture(self)
        roots = []
        for name in ('first-owned-attempt', 'second-owned-attempt'):
            root = project_root.parent / name
            paths.new_directory(root)
            work, output = root / 'work', root / 'output'
            paths.new_directory(work)
            paths.new_directory(output)
            isolation = Mock(workspace=root.resolve(), receipt=copy.deepcopy(first.receipt))
            specification = consumer.request(verified, isolation, A)
            identity = common.digest(canonical(specification))
            roots.append(identity)
            approval = consumer.approve(verified, isolation, A, identity)
            captures.prepare(project_root, work, output, 'rust', execution_approval=approval)
            isolation.check_unchanged.assert_called_once()
            self.assertTrue((work / 'dependencies/build-tool/build.rs').is_file())
        self.assertEqual(roots[0], roots[1])
        for changed in (replace(verified, manifest_bytes=verified.manifest_bytes + b'\n'),
                        replace(verified, lock_bytes=verified.lock_bytes + b'\n')):
            with self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
                consumer.approve(changed, first, A, roots[0])
        for recipe in (B,):
            with self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
                consumer.approve(verified, first, recipe, roots[0])
        first.receipt['tools']['compiler'] = B
        with self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
            consumer.approve(verified, first, A, roots[0])

    def test_absent_wrong_and_stale_approval_cannot_materialize_executable_inputs(self):
        project_root, work, output, verified, isolation = approval_tests.ExecutionApproval.fixture(self)
        with self.assertRaisesRegex(DependencyError, 'require-isolated-stage'):
            captures.prepare(project_root, work, output, 'rust')
        with self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
            consumer.approve(verified, isolation, A, B)
        identity = common.digest(canonical(consumer.request(verified, isolation, A)))
        approval = consumer.approve(verified, isolation, A, identity)
        isolation.receipt['tools']['compiler'] = B
        with self.assertRaisesRegex(DependencyError, 'stale'):
            captures.prepare(project_root, work, output, 'rust', execution_approval=approval)
        self.assertFalse((work / 'dependencies/build-tool').exists())

    def test_watch_keeps_explicit_identity_and_stale_edit_refuses_without_deployment_or_promotion(self):
        from tools.dev_workflow import watch
        project_root, work, _output, verified, isolation = approval_tests.ExecutionApproval.fixture(self)
        # The source fixture is not private controller state. Keep real locking
        # and ownership checks active in a separate, correctly created workspace.
        workspace = project_root.parent / 'controller'
        paths.new_directory(workspace)
        source = project_root / 'main.rs'
        source.write_bytes(b'first source')
        explicit = common.digest(canonical(consumer.request(verified, isolation, common.digest(source.read_bytes()))))
        events, passed = [], []
        connection = Mock()
        status_calls = 0
        def call(operation, *args, **kwargs):
            nonlocal status_calls
            if operation == 'status':
                status_calls += 1
                self.assertLessEqual(status_calls, 4, events)
                return {'state': 'stopped' if len(passed) == 2 else 'ready'}
            return {'generation': '1'}
        connection.call.side_effect = call
        def execute(_workspace, _connection, _source, _tool_root, **kwargs):
            passed.append(kwargs['executable_approval'])
            try:
                approval = consumer.approve(verified, isolation, common.digest(source.read_bytes()), kwargs['executable_approval'])
                approval.validate(verified, work)
            except DependencyError as error:
                raise common.DevError('dependency-execution-approval-mismatch') from error
            return {'source': common.digest(source.read_bytes())}
        def emit(event):
            events.append(event)
            if event['event'] == 'deployed':
                source.write_bytes(b'new source invalidates request')
        cycles = 0
        def check_session():
            nonlocal cycles
            cycles += 1
            self.assertLessEqual(cycles, 4, f'watch fixture did not stop: {events}')
        with patch.object(project, 'load', return_value=(maintained(), A)), \
             patch.object(build_client, 'selection', side_effect=lambda _root: (A, common.digest(source.read_bytes()))), \
             patch.object(watch.time, 'sleep'):
            result = watch.run(workspace, connection, project_root, '/tools', build=execute, emit=emit,
                               executable_approval=explicit, check_session=check_session)
        self.assertEqual(result, {'state': 'stopped'})
        self.assertEqual(passed, [explicit, explicit])
        self.assertEqual(cycles, 3)
        self.assertEqual(sum(event['event'] == 'deployed' for event in events), 1)
        self.assertEqual([event['code'] for event in events if event['event'] == 'edit-failed'],
                         ['dependency-execution-approval-mismatch'])
        self.assertEqual(sum(call.args[0] == 'deploy' for call in connection.call.call_args_list), 1)


class PrivateRequestViewer(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.controller, self.original = self.root / 'controller', self.root / 'original'
        for path in (self.controller, self.original, self.original / 'app'):
            paths.new_directory(path)
        (self.original / 'app/main.rs').write_bytes(b'fn main() {}')
        (self.original / 'app/sdk-lock.json').write_bytes(b'unchanged sdk lock\n')
        library = self.root / 'outside-build-tool'
        paths.new_directory(library)
        (library / 'build.rs').write_bytes(b'fn main() {}')
        manifest = {'formatVersion': 1, 'language': 'rust', 'selection': {'runtimeProfile': 'closed'},
            'nativeLocks': [], 'artifacts': [{'id': 'outside/tool/1', 'role': 'build-tool', 'format': 'directory',
                'mount': 'dependencies/build-tool', 'source': {'path': str(library)}, 'dependencies': [], 'metadata': {}}], 'transformations': []}
        (self.original / captures.MANIFEST).write_bytes(canonical(manifest))
        (self.original / captures.LOCK).write_bytes(canonical(captures.capture(self.original)))
        self.value = maintained()
        names = set(rust_capsule_build.RECIPE) | {'examples/echo-contract/capsule.json', 'examples/echo-contract/deployment.json'}
        files = {name: (rust_capsule_project.ROOT / name).read_bytes() for name in names}
        self.recipe_raw = rust_capsule_project.inventory(files)
        entries = [{'path': 'recipe/' + name, 'sha256': common.digest(raw), 'size': len(raw)} for name, raw in sorted(files.items())]
        entries += [{'path': 'sdk/bin/python', 'sha256': common.digest(b'python'), 'size': 6},
                    {'path': 'recipe/tools/dev_guest_recipe.py', 'sha256': common.digest(b'adapter'), 'size': 7}]
        self.inventory = {'schemaVersion': 'latent.dev.guest-tools.v1', 'language': 'rust', 'ownerIssue': 544,
            'sourceCommit': self.value['template']['revision'], 'hostAbi': self.value['hostAbi'], 'host': 'linux-x86_64', 'files': entries}
        self.inventory['identity'] = common.digest(common.encode(self.inventory))
        inventory_raw = common.encode(self.inventory)
        self.value['build']['inventory']['sha256'] = common.digest(inventory_raw)
        (self.original / 'latent.project.json').write_bytes(common.encode(self.value))
        self.value = project.load(self.original)[0]
        self.record, content = snapshot.observe(self.original, self.value['inputRoots'], tuple(self.value['exclude']))
        paths.new_directory(self.controller / 'snapshots')
        source = self.controller / 'snapshots' / self.record['identity'][7:]
        snapshot.materialize(source, self.record, content)
        self.trust = project.trust_identity(self.value)
        self.attempt, self.working, _ = build_cache.allocate(self.controller, source, self.record, self.value,
            self.trust, 'linux-x86_64', A)
        paths.write_new(self.attempt / 'tool-inventory.json', inventory_raw)
        build_cache.transition(self.attempt, 'failed')
        state.atomic(self.controller, 'project.json', {'descriptor': self.value, 'trust': self.trust,
            'source': str(source), 'snapshot': self.record['identity']})
        state.atomic(self.controller, 'active-build.json', {'id': 'a' * 32, 'state': 'reaped', 'guestInstance': 'owned',
            'attempt': self.attempt.name, 'reason': 'guest-build-failed-last-deployment-retained'})
        self.output = self.working / 'output'
        paths.new_directory(self.output)
        (self.output / 'recipe-inputs.json').write_bytes(self.recipe_raw)
        source_raw = rust_capsule_project.inventory(capture_source(self.working / 'app', 'rust').files)
        (self.output / 'source-inputs.json').write_bytes(source_raw)
        file = lambda name: {'name': name, 'digest': common.digest(name.encode()), 'size': 1}
        self.compiler = {'formatVersion': 1, 'profile': viewer.PROFILE,
            'distributions': {name: [{'path': 'owned/file', 'digest': A, 'size': 1}]
                              for name in ('rust-compiler-and-sysroot', 'zig-host-linker-and-sysroot')},
            'tools': {name: file(name) for name in ('cargo', 'rustc', 'wasm-tools', 'wit-bindgen', 'zig', 'shell', 'linker')},
            'sandbox': file('build-sandbox'), 'loaderObserver': file('loader-dependency-observer'), 'hostRuntimeLibraries': {},
            'network': 'denied', 'ambientHome': 'absent', 'credentials': 'not-inherited',
            'boundary': 'trusted-single-user-compiler-host-not-hardened-multitenant-vm'}
        (self.output / 'rust-compiler-inputs.json').write_bytes(canonical(self.compiler))
        verified = captures.verify_inputs(self.working, 'rust')
        recipe = common.digest(canonical({'recipe': common.digest(self.recipe_raw), 'sourceSnapshot': common.digest(source_raw)}))
        specification = consumer.request(verified, SimpleNamespace(receipt=self.compiler), recipe)
        self.request = {'formatVersion': 1, 'identity': common.digest(canonical(specification)), 'specification': specification}
        self.request_path = self.output / 'executable-input-approval-request.json'
        self.request_path.write_bytes(canonical(self.request))

    def observe(self):
        with state.lock(self.controller), state.lock(self.controller, 'build-control.lock', timeout=1):
            return viewer.read(self.controller)

    def test_explicit_private_view_recomputes_real_producer_without_approval_or_source_mutation(self):
        watched = [self.original / 'latent.project.json', self.original / 'app/sdk-lock.json',
                   self.working / 'latent.project.json', self.working / 'app/sdk-lock.json',
                   self.controller / 'active-build.json', self.attempt / 'attempt.json', self.request_path]
        before = {path: path.read_bytes() for path in watched}
        with patch.object(consumer, 'approve', side_effect=AssertionError('automatic approval')), \
             patch.object(build.process, 'run', side_effect=AssertionError('native process')):
            result = self.observe()
        self.assertEqual(result['request'], self.request)
        self.assertIs(result['executionApproved'], False)
        self.assertEqual({path: path.read_bytes() for path in watched}, before)
        self.assertNotIn('request', build.build_cache.owner(self.attempt))

    def test_current_source_or_trust_and_active_ownership_must_match(self):
        mutations = [('active-build.json', 'state', 'running'), ('active-build.json', 'state', 'uncertain'),
                     ('active-build.json', 'attempt', 'f' * 32), ('project.json', 'trust', B),
                     ('project.json', 'snapshot', B), ('project.json', 'source', str(self.root))]
        for name, key, value in mutations:
            before = state.load(self.controller, name)
            state.atomic(self.controller, name, {**before, key: value})
            with self.subTest(name=name, key=key, value=value), self.assertRaises((common.DevError, OSError)):
                self.observe()
            state.atomic(self.controller, name, before)
        build_cache.transition(self.attempt, 'complete')
        with self.assertRaisesRegex(common.DevError, 'failed-reaped'):
            self.observe()

    def test_changed_working_source_or_sdk_lock_is_refused(self):
        for name in ('app/main.rs', 'app/sdk-lock.json'):
            target = self.working / name
            before = target.read_bytes()
            target.write_bytes(before + b'changed')
            with self.subTest(name=name), self.assertRaises(common.DevError):
                self.observe()
            target.write_bytes(before)

    def test_canonical_hash_alone_cannot_replace_input_recipe_compiler_or_profile(self):
        for name, value in (('inputIdentity', B), ('recipeDigest', B), ('compilerInputsDigest', B),
                            ('isolationProfile', 'other'), ('network', 'allowed'), ('executableInputs', [])):
            changed = copy.deepcopy(self.request)
            changed['specification'][name] = value
            changed['identity'] = common.digest(canonical(changed['specification']))
            self.request_path.write_bytes(canonical(changed))
            with self.subTest(name=name), self.assertRaisesRegex(common.DevError, 'producer-mismatch'):
                self.observe()

    def test_request_duplicate_nonfinite_depth_size_and_hardlink_are_refused(self):
        for raw in (b'{"formatVersion":1,"formatVersion":1}', b'{"x":NaN}',
                    b'[' * 16384 + b'0' + b']' * 16384, b' ' * (viewer.MAX_REQUEST + 1)):
            self.request_path.write_bytes(raw)
            with self.subTest(size=len(raw)), self.assertRaises(common.DevError):
                self.observe()
        self.request_path.write_bytes(canonical(self.request))
        alias = self.root / 'hardlinked-request'
        os.link(self.request_path, alias)
        with self.assertRaisesRegex(common.DevError, 'single-link-regular-file'):
            self.observe()

    def test_retained_recipe_inventory_and_compiler_schema_cannot_be_substituted(self):
        for name, raw in (('tool-inventory.json', b'{}'), ('source-inputs.json', b'{}'),
                          ('recipe-inputs.json', b'{}'), ('rust-compiler-inputs.json', b'{}')):
            target = self.attempt / name if name == 'tool-inventory.json' else self.output / name
            before = target.read_bytes()
            target.write_bytes(raw)
            with self.subTest(name=name), self.assertRaises(common.DevError):
                self.observe()
            target.write_bytes(before)


if __name__ == '__main__':
    unittest.main()
