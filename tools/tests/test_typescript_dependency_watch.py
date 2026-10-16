"""Owned original TypeScript package fixtures retain exact source/resource/version scope."""
from pathlib import Path
import tempfile
import json
import unittest

from tools import typescript_dependency_watch_fixture as fixture


class TypescriptDependencyWatchFixture(unittest.TestCase):
    def test_two_real_packages_preserve_primary_api_and_resource_across_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary, child = Path(observed['primary']), Path(observed['child'])
            v1 = json.loads((primary / 'package.json').read_text())
            self.assertEqual(v1['name'], fixture.PRIMARY)
            self.assertEqual(v1['dependencies'][fixture.CHILD], 'file:../child-v1')
            self.assertEqual((primary / 'badge.txt').read_bytes(), fixture.RESOURCE)
            original_api = (primary / 'index.mjs').read_bytes()
            self.assertIn(b'value + 39', (child / 'index.mjs').read_bytes())
            fixture.remove_original(observed, 'primary'); fixture.remove_original(observed, 'child')
            self.assertFalse(primary.exists() or child.exists())
            fixture.restore_revision(observed, 2)
            primary, child = Path(observed['primary']), Path(observed['child'])
            self.assertEqual(json.loads((primary / 'package.json').read_text())['version'], '1.0.1')
            self.assertEqual((primary / 'index.mjs').read_bytes(), original_api)
            self.assertIn(b'value + 40', (child / 'index.mjs').read_bytes())
            self.assertNotEqual(observed['inputDigests']['child-v1'], observed['inputDigests']['child-v2'])
            self.assertFalse((application / 'app').exists())

    def test_cleanup_and_restore_refuse_unknown_roots_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / 'application'; application.mkdir()
            observed = fixture.create(application)
            primary = Path(observed['primary'])
            before = (primary / 'package.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'fresh'):
                fixture.restore_revision(observed, 2)
            with self.assertRaisesRegex(ValueError, 'unknown'):
                fixture.remove_original(observed, '../application')
            changed = {**observed, 'ownedRoot': str(application.resolve())}
            with self.assertRaisesRegex(ValueError, 'escaped'):
                fixture.remove_original(changed, 'primary')
            self.assertEqual((primary / 'package.json').read_bytes(), before)
            self.assertTrue(application.is_dir())

    def test_removal_entry_has_no_library_reference_and_keeps_normal_wit(self):
        selected = fixture.application_source()
        removed = fixture.application_source(removed=True)
        self.assertIn('answer()', selected)
        self.assertNotIn('outside-watch-primary', removed)
        self.assertIn('removed/${clean}', removed)
        for source in (selected, removed):
            self.assertIn('export const api: typeof Contract', source)
            self.assertIn('calls++ !== 0', source)
            self.assertNotIn('unsafe', source)

    def test_uncertain_shutdown_is_never_replayed_and_original_failure_is_preserved(self):
        from tools.qualify_typescript_dependency_watch import ShutdownOnce
        fence = ShutdownOnce()
        calls = []
        original = RuntimeError('unknown external shutdown result')
        def uncertain():
            calls.append('down')
            self.assertTrue(fence.attempted)
            raise original
        with self.assertRaises(RuntimeError) as observed:
            fence.call(uncertain)
        self.assertIs(observed.exception, original)
        with self.assertRaisesRegex(ValueError, 'already-attempted-no-retry'):
            fence.call(lambda: calls.append('replayed'))
        self.assertEqual(calls, ['down'])

    def test_confirmed_shutdown_receipt_is_preserved_and_same_owner_is_not_replayed(self):
        from tools.qualify_typescript_dependency_watch import ShutdownOnce
        fence = ShutdownOnce()
        receipt = {'state': 'stopped', 'reaped': True, 'cleanShutdown': True}
        self.assertIs(fence.call(lambda: receipt), receipt)
        with self.assertRaisesRegex(ValueError, 'already-attempted-no-retry'):
            fence.call(lambda: self.fail('replayed confirmed mutation'))

    def test_watch_delegation_operations_exist_in_maintained_frontend(self):
        import argparse
        import ast
        import inspect
        from tools import qualify_typescript_dependency_watch as programme
        from tools.dev_workflow.cli import parser
        root = parser()
        groups = next(row for row in root._actions if isinstance(row, argparse._SubParsersAction))
        commands = next(row for row in groups.choices['dev']._actions
            if isinstance(row, argparse._SubParsersAction)).choices
        tree = ast.parse(inspect.getsource(programme))
        operations = [row.args[1].value for row in ast.walk(tree)
            if isinstance(row, ast.Call) and isinstance(row.func, ast.Name) and row.func.id == 'front'
            and len(row.args) > 1 and isinstance(row.args[1], ast.Constant)]
        self.assertTrue(operations)
        self.assertLessEqual(set(operations), set(commands))
        self.assertIn('trust', operations)
        codes = {row.value for row in ast.walk(tree) if isinstance(row, ast.Constant)
            and isinstance(row.value, str) and row.value.startswith('workspace-recipe-')}
        self.assertEqual(codes, {'workspace-recipe-trust-required'})

class FrontendRuntime(unittest.TestCase):
    def test_exact_frontend_ignores_ambient_python_inputs_and_never_writes_bytecode(self):
        import ast
        import json
        import hashlib
        import os
        import subprocess
        import sys
        from types import SimpleNamespace
        import zipfile
        from tools import qualify_typescript_dependency_watch as qualifier

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper = root / 'helper.pyz'
            with zipfile.ZipFile(helper, 'w') as archive:
                archive.writestr('tools/__init__.py', '')
                archive.writestr('tools/dev_workflow/__init__.py', '')
                archive.writestr('tools/dev_workflow/cli.py',
                    'import json,sys\n'
                    'def main():\n'
                    ' print(json.dumps({"isolated":sys.flags.isolated,'
                    '"ignoreEnvironment":sys.flags.ignore_environment,'
                    '"noBytecode":sys.dont_write_bytecode,"cachePrefix":sys.pycache_prefix}))\n'
                    ' return 0\n')
            frontend, events = root / 'frontend.py', root / 'events.jsonl'
            python = Path(sys.executable)
            args = SimpleNamespace(helper=helper,
                helper_sha256='sha256:' + hashlib.sha256(helper.read_bytes()).hexdigest())
            qualifier.write_frontend(frontend, python, args, events)
            header = frontend.read_text().splitlines()[0]
            self.assertTrue(header.startswith('#!' + str(python)))
            argument = header[len('#!' + str(python)):].strip()
            environment = {'PATH': os.defpath, 'HOME': temporary, 'TEMP': temporary, 'TMP': temporary,
                'PYTHONPATH': str(root / 'ambient-imports'),
                'PYTHONPYCACHEPREFIX': str(root / 'ambient-bytecode')}
            if sys.platform == 'win32':
                environment['SystemRoot'] = os.environ['SystemRoot']
            result = subprocess.run([str(python), *([argument] if argument else []), str(frontend)],
                cwd=root, env=environment, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
            self.assertEqual(json.loads(result.stdout), {'isolated': 1, 'ignoreEnvironment': 1,
                'noBytecode': True, 'cachePrefix': None})
            self.assertEqual(events.read_bytes(), result.stdout)
            self.assertFalse((root / 'ambient-bytecode').exists())


class DeliveredResolverOwner(unittest.TestCase):
    def layout(self, root, *, recorded=True):
        import shutil
        import stat
        import zipfile
        from tools import build_dev_frontend
        from tools.dev_workflow.common import HOST_ABI, digest, encode

        helper = root / 'actual-helper.pyz'
        helper_identity = build_dev_frontend.helper(helper)
        installed = root / 'relocated installed'
        sdk = installed / 'sdk'; sdk.mkdir(parents=True)
        owner = installed / 'recipe/tools/dev_managed_tools.py'
        owner.parent.mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / 'dev_managed_tools.py'
        shutil.copyfile(source, owner)
        files = []
        expected = {'node/bin/node': b'explicit fixture node bytes',
                    'node/lib/node_modules/npm/bin/npm-cli.js': b'explicit fixture npm bytes'}
        with zipfile.ZipFile(sdk / 'managed.zip', 'x') as archive:
            for name, raw in expected.items():
                entry = zipfile.ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o700) << 16
                archive.writestr(entry, raw)
                files.append({'path': name, 'size': len(raw), 'sha256': digest(raw), 'executable': True})
        manifest = {'schemaVersion': 'latent.dev.managed-tools.v1', 'files': files}
        manifest['identity'] = digest(encode(manifest))
        (sdk / 'managed-inputs.json').write_bytes(encode(manifest))
        inventory = {'schemaVersion': 'latent.dev.guest-tools.v1', 'language': 'typescript',
            'ownerIssue': 546, 'sourceCommit': 'a' * 40, 'hostAbi': HOST_ABI, 'host': 'linux-x86_64',
            'files': [{'path': path.relative_to(installed).as_posix(), 'size': path.stat().st_size,
                       'sha256': digest(path.read_bytes())}
                      for path in sorted(installed.rglob('*')) if path.is_file()
                      and (recorded or path != owner)]}
        inventory['identity'] = digest(encode(inventory))
        raw = encode(inventory)
        (installed / 'guest-tools.json').write_bytes(raw)
        descriptor = {'language': 'typescript', 'hostAbi': HOST_ABI,
            'template': {'ownerIssue': 546, 'revision': 'a' * 40},
            'build': {'inventory': {'path': 'guest-tools.json', 'sha256': digest(raw)}, 'tools': []}}
        (root / 'descriptor.json').write_bytes(encode(descriptor))
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'qualify_typescript_dependency_watch.py',
                        root / 'qualifier.py')
        return installed, owner, expected, helper_identity, inventory['identity']

    def run_delivered(self, root):
        import os
        import subprocess
        import sys

        runner = root / 'outside-checkout.py'
        runner.write_text('''import importlib.util,json,pathlib,sys
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(root/'actual-helper.pyz'))
try:
 from tools.dev_managed_tools import unpack
except ModuleNotFoundError as error:
 assert error.name=='tools.dev_managed_tools',error.name
else:
 raise AssertionError('actual helper unexpectedly contains recipe-only owner')
import tools
assert str(root/'actual-helper.pyz') in tools.__file__,tools.__file__
spec=importlib.util.spec_from_file_location('watch_qualifier',root/'qualifier.py')
qualifier=importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualifier)
try:
 managed,owner=qualifier.unpack_resolver(root/'relocated installed',root/'resolver-managed',
     json.loads((root/'descriptor.json').read_bytes()))
 result={'passed':True,'owner':owner,'files':{
     path.relative_to(managed).as_posix():path.read_text()
     for path in managed.rglob('*') if path.is_file()}}
except (ValueError,FileNotFoundError) as error:
 result={'passed':False,'error':str(error),'errorType':type(error).__name__}
result.update(isolated=sys.flags.isolated,noBytecode=sys.dont_write_bytecode,
              cachePrefix=sys.pycache_prefix,missingFromActualHelper=True)
print(json.dumps(result))
''', encoding='utf-8')
        environment = {'PATH': os.defpath, 'HOME': str(root), 'TEMP': str(root), 'TMP': str(root),
            'PYTHONPATH': str(root / 'ambient-imports'), 'PYTHONPYCACHEPREFIX': str(root / 'ambient-bytecode')}
        if sys.platform == 'win32':
            environment['SystemRoot'] = os.environ['SystemRoot']
        result = subprocess.run([sys.executable, '-I', '-B', str(runner)], cwd=root,
            env=environment, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        value = json.loads(result.stdout)
        self.assertEqual((value['isolated'], value['noBytecode'], value['cachePrefix']), (1, True, None))
        self.assertTrue(value['missingFromActualHelper'])
        self.assertFalse(list(root.rglob('__pycache__')))
        self.assertFalse((root / 'ambient-bytecode').exists())
        self.assertFalse((root / 'recipe-canary').exists())
        return value

    @unittest.skipUnless(__import__('sys').platform == 'linux', 'Linux helper omits Windows platform owners')
    def test_actual_helper_loads_only_recorded_installed_recipe_and_unpacks_exact_bytes(self):
        from tools.dev_workflow.common import digest
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed, owner, expected, helper_identity, inventory_identity = self.layout(root)
            before = {path.relative_to(installed).as_posix(): digest(path.read_bytes())
                      for path in installed.rglob('*') if path.is_file()}
            value = self.run_delivered(root)
            self.assertTrue(value['passed'], value)
            self.assertEqual(value['files'], {name: raw.decode() for name, raw in expected.items()})
            self.assertEqual(value['owner'], {'path': 'recipe/tools/dev_managed_tools.py',
                'sha256': digest(owner.read_bytes()), 'inventoryIdentity': inventory_identity})
            self.assertEqual(digest((root / 'actual-helper.pyz').read_bytes()), helper_identity)
            self.assertEqual({path.relative_to(installed).as_posix(): digest(path.read_bytes())
                              for path in installed.rglob('*') if path.is_file()}, before)

    @unittest.skipUnless(__import__('sys').platform == 'linux', 'Linux helper omits Windows platform owners')
    def test_altered_recipe_is_rejected_before_loading_or_creating_resolver_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, owner, _, _, _ = self.layout(root)
            owner.write_text('from pathlib import Path\nPath(' + repr(str(root / 'recipe-canary'))
                             + ').write_text("executed")\n', encoding='utf-8')
            value = self.run_delivered(root)
            self.assertFalse(value['passed'])
            self.assertEqual(value['error'], 'guest-tool-companion-modified')
            self.assertFalse((root / 'resolver-managed').exists())

    @unittest.skipUnless(__import__('sys').platform == 'linux', 'Linux helper omits Windows platform owners')
    def test_missing_recipe_is_rejected_before_creating_resolver_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, owner, _, _, _ = self.layout(root)
            owner.unlink()
            value = self.run_delivered(root)
            self.assertFalse(value['passed'])
            self.assertEqual(value['errorType'], 'FileNotFoundError')
            self.assertFalse((root / 'resolver-managed').exists())

    @unittest.skipUnless(__import__('sys').platform == 'linux', 'Linux helper omits Windows platform owners')
    def test_unrecorded_recipe_is_rejected_even_when_inventory_omits_recipe_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.layout(root, recorded=False)
            value = self.run_delivered(root)
            self.assertFalse(value['passed'])
            self.assertEqual(value['error'], 'delivered-managed-owner-outside-inventory')
            self.assertFalse((root / 'resolver-managed').exists())

    def test_source_inventory_loader_preserves_exact_inputs_and_rejects_changed_recipe_before_mutation(self):
        import sys
        from unittest.mock import patch
        from tools import qualify_typescript_dependency_watch as qualifier
        from tools.dev_workflow.common import digest
        original_no_bytecode = sys.dont_write_bytecode
        for mode in ('valid', 'altered', 'missing', 'unrecorded'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                installed, owner, expected, _, inventory_identity = self.layout(root, recorded=mode != 'unrecorded')
                descriptor = json.loads((root / 'descriptor.json').read_bytes())
                destination = root / 'resolver-managed'
                if mode == 'altered':
                    owner.write_text('from pathlib import Path\nPath(' + repr(str(root / 'recipe-canary'))
                                     + ').write_text("executed")\n', encoding='utf-8')
                elif mode == 'missing':
                    owner.unlink()
                if mode == 'valid':
                    before = {path.relative_to(installed).as_posix(): digest(path.read_bytes())
                              for path in installed.rglob('*') if path.is_file()}
                    # The maintained runuser command starts the delivered qualifier
                    # with -I -B; ordinary unittest discovery itself does not.
                    with patch.object(sys, 'dont_write_bytecode', True):
                        managed, observed = qualifier.unpack_resolver(installed, destination, descriptor)
                    self.assertEqual(managed, destination)
                    self.assertEqual(observed, {'path': 'recipe/tools/dev_managed_tools.py',
                        'sha256': digest(owner.read_bytes()), 'inventoryIdentity': inventory_identity})
                    self.assertEqual({path.relative_to(managed).as_posix(): path.read_bytes()
                                      for path in managed.rglob('*') if path.is_file()}, expected)
                    self.assertEqual({path.relative_to(installed).as_posix(): digest(path.read_bytes())
                                      for path in installed.rglob('*') if path.is_file()}, before)
                else:
                    with patch.object(sys, 'dont_write_bytecode', True):
                        with self.assertRaises((ValueError, FileNotFoundError)):
                            qualifier.unpack_resolver(installed, destination, descriptor)
                    self.assertFalse(destination.exists())
                self.assertFalse((root / 'recipe-canary').exists())
                self.assertFalse(list(installed.rglob('__pycache__')))
                self.assertIs(sys.dont_write_bytecode, original_no_bytecode)

class DeliveredTemplateCaller(unittest.TestCase):
    def run_actual_main_to_resolver_boundary(self, root, *, flat=False):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools import dev_tool_distribution as distribution
        from tools import qualify_typescript_dependency_watch as qualifier
        from tools.dev_workflow import project
        from tools.dev_workflow.common import decode, digest, encode

        installed, _, _, helper_identity, _ = DeliveredResolverOwner().layout(root)
        for name in ('sdk/bin/python', 'sdk/bin/capsule-contracts', 'sdk/bin/capsule-test-signer',
                     'sdk/bin/wasm-tools', 'sdk/bin/wit-bindgen', 'recipe/tools/dev_guest_recipe.py',
                     'recipe/tools/typescript_capsule.py'):
            selected = installed / name
            selected.parent.mkdir(parents=True, exist_ok=True)
            selected.write_bytes(b'explicit source-fixture bytes; never executed')
        distribution.compiler_inventory(installed, 'a' * 40, 'typescript')
        def minimal_source_application(destination, name):
            destination.mkdir()
            (destination / 'capsule-project.json').write_bytes(encode({
                'name': name, 'tenant': 'examples', 'service': 'examples/my-' + name}))
            return destination
        with patch.object(distribution.typescript_project, 'create', side_effect=minimal_source_application):
            catalogue = distribution.templates(installed, 'a' * 40, 'typescript')
        entry = catalogue['greeting']
        template = installed / entry['path']
        manifest = decode((template / 'template.json').read_bytes())
        self.assertEqual(set(manifest), {'schemaVersion', 'project', 'snapshot'})
        self.assertNotIn('build', manifest)
        self.assertIn('inventory', manifest['project']['build'])
        # Exercise the real producer and consumer schema/identity boundary with
        # tiny source bytes, before any resolver, compiler or guest execution.
        project.scaffold(template, root / 'verified-scaffold', manifest, entry['identity'])
        if flat:
            (template / 'template.json').write_bytes(encode(manifest['project']))
        probe, fixture = root / 'probe.py', root / 'fixture.py'
        probe.write_text('# explicit source-fixture module; no process work\n')
        fixture.write_text('# explicit source-fixture module; no process work\n')
        node = root / 'source-node'; node.mkdir()
        (node / 'source-node.json').write_bytes(b'{}')
        args = SimpleNamespace(installed=installed, helper=root / 'actual-helper.pyz',
            helper_sha256=helper_identity, source_probe=probe, source_probe_sha256=digest(probe.read_bytes()),
            source_node=node, fixture_source=fixture, fixture_sha256=digest(fixture.read_bytes()),
            output=root / 'observation')
        before = {path.relative_to(installed).as_posix(): digest(path.read_bytes())
                  for path in installed.rglob('*') if path.is_file()}
        observed = []
        def before_resolver(selected, destination, descriptor):
            observed.append(descriptor)
            self.assertEqual(descriptor, manifest['project'])
            self.assertEqual((selected, destination), (installed, args.output / 'resolver-managed'))
            raise RuntimeError('intentional-before-resolver-native-boundary')
        original_path = sys.path[:]
        try:
            with patch.object(qualifier.argparse.ArgumentParser, 'parse_args', return_value=args), \
                    patch.object(qualifier.sys, 'platform', 'linux'), \
                    patch.object(qualifier.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(qualifier, 'unpack_resolver', side_effect=before_resolver) as unpack, \
                    patch.object(qualifier.subprocess, 'run', side_effect=AssertionError('native process forbidden')), \
                    patch.object(qualifier.subprocess, 'Popen', side_effect=AssertionError('native process forbidden')):
                if flat:
                    with self.assertRaises(KeyError):
                        qualifier.main()
                    unpack.assert_not_called()
                else:
                    with self.assertRaisesRegex(RuntimeError, 'intentional-before-resolver-native-boundary'):
                        qualifier.main()
                    unpack.assert_called_once()
                    self.assertEqual(observed, [manifest['project']])
        finally:
            sys.path[:] = original_path
        self.assertFalse((args.output / 'resolver-managed').exists())
        self.assertEqual({path.relative_to(installed).as_posix(): digest(path.read_bytes())
                          for path in installed.rglob('*') if path.is_file()}, before)
        report = json.loads((args.output / 'public-qualification.json').read_bytes())
        self.assertFalse(report['passed'])
        self.assertEqual((report['phase'], report['deploymentCount'], report['stages']), ('prepare', 0, []))

    def test_actual_template_wrapper_selects_its_project_at_main_resolver_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.run_actual_main_to_resolver_boundary(Path(temporary))

    def test_flat_project_cannot_substitute_for_the_actual_template_wrapper(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.run_actual_main_to_resolver_boundary(Path(temporary), flat=True)
