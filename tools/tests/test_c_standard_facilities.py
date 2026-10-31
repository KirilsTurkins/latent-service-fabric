"""Profile authority, derived contracts and retained original input identities."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import c_capsule_project as project, guest_runtime_receipts as receipts
from tools.c_guest import standard_facilities as facilities
from tools.dev_workflow.common import DevError, digest
from tools.rust_capsule_project import ROOT, inventory


class StandardFacilities(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)

    def test_missing_runtime_grant_requires_rejected_zero_execution_receipt(self):
        from tools.c_standard_facilities_probe import require_denied_before_guest
        from tools.phase2_operator_process import WorkflowError
        denied = {'exitCode': 4, 'response': {'outcomeKnown': True, 'error': {'code': 'permission-denied'},
            'data': {'terminalState': 'rejected', 'consumption': {'cpuFuel': '0', 'peakMemoryBytes': '0'}}}}
        require_denied_before_guest(denied)
        for field, value in (('exit', 3), ('outcome', False), ('error', 'unavailable'),
                             ('state', 'failed'), ('fuel', '1'), ('memory', '1')):
            changed = json.loads(json.dumps(denied))
            if field == 'exit': changed['exitCode'] = value
            elif field == 'outcome': changed['response']['outcomeKnown'] = value
            elif field == 'error': changed['response']['error']['code'] = value
            elif field == 'state': changed['response']['data']['terminalState'] = value
            elif field == 'fuel': changed['response']['data']['consumption']['cpuFuel'] = value
            else: changed['response']['data']['consumption']['peakMemoryBytes'] = value
            with self.subTest(field=field), self.assertRaisesRegex(WorkflowError, 'reject-before-guest'):
                require_denied_before_guest(changed)

    def test_profile_is_explicit_closed_and_part_of_original_source(self):
        root = project.create(self.root / 'project', 'greeting')
        files = project.snapshot(root)
        value, _, _ = project.validate(files)
        self.assertEqual(facilities.selected_profile(value), facilities.DEFAULT)
        for invalid in (None, True, [], 'ambient-wasi', ''):
            changed = dict(files)
            changed['capsule-project.json'] = json.dumps({**value, 'runtimeProfile': invalid}).encode()
            with self.subTest(profile=invalid), self.assertRaisesRegex(ValueError, 'unsupported-c-standard-runtime-profile'):
                project.validate(changed)
        changed = dict(files)
        changed['capsule-project.json'] = json.dumps({**value, 'runtimeProfile': facilities.PROFILE}).encode()
        selected, _, _ = project.validate(changed)
        self.assertEqual(facilities.selected_profile(selected), facilities.PROFILE)
        self.assertNotEqual(inventory(files), inventory(changed))
        changed['vendor/lsf/sdk/c-guest/src/standard-clock-entropy.c'] += b'\n'
        with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
            project.validate(changed)

    def test_derived_world_retains_originals_and_exact_typed_dependency_closure(self):
        root = project.create(self.root / 'project', 'greeting')
        source = root / 'wit'
        original = project.snapshot(source)
        destination = self.root / 'derived'
        facilities.stage(source, 'examples:greeting/service@1.0.0', destination, ROOT / 'wit/platform')
        self.assertEqual(project.snapshot(source), original)
        text = '\n'.join(path.read_text() for path in destination.glob('*.wit'))
        for name in facilities.IMPORTS:
            self.assertEqual(text.count('import ' + name + ';'), 1)
        self.assertEqual({path.name for path in (destination / 'deps').iterdir()}, {'clock', 'random'})
        self.assertIn('export api;', text)
        with self.assertRaisesRegex(ValueError, 'fresh-derived-wit'):
            facilities.stage(source, 'service', destination, ROOT / 'wit/platform')

    def test_ambiguous_world_and_explicit_profile_import_cannot_gain_duplicate_contracts(self):
        source = self.root / 'wit'; source.mkdir()
        path = source / 'app.wit'
        for text in ('package test:app; world other {}',
                     'package test:app; world service {} world service {}',
                     'package test:app; world service { import latent:clock/wall@0.1.0; }'):
            path.write_text(text)
            destination = self.root / 'derived'
            with self.subTest(text=text), self.assertRaises(ValueError):
                facilities.stage(source, 'service', destination, ROOT / 'wit/platform')
            self.assertFalse(destination.exists())

    def test_commented_worlds_do_not_replace_or_duplicate_the_actual_selected_world(self):
        source = self.root / 'wit'; source.mkdir()
        path = source / 'app.wit'
        for number, (comment, declaration) in enumerate((
                ('// world service { export fake; }\n', 'world service {'),
                ('/* world service { export fake; } */\n', 'world service {'),
                ('/* outer /* world service {} */ world service {} */\n', 'world service {'),
                ('', 'world /* note */ service /* selected */ {'))):
            text = 'package test:app;\n' + comment + declaration + ' export api; }\ninterface api { run: func(); }\n'
            path.write_text(text, encoding='utf-8')
            original = path.read_bytes()
            destination = self.root / f'derived-{number}'
            facilities.stage(source, 'test:app/service', destination, ROOT / 'wit/platform')
            # The insertion point belongs to the actual declaration, not documentation.
            offset = text.index(declaration, len('package test:app;\n') + len(comment)) + len(declaration)
            additions = ''.join('\n    import ' + name + ';' for name in facilities.IMPORTS) + '\n'
            self.assertEqual((destination / path.name).read_text(encoding='utf-8'),
                             text[:offset] + additions + text[offset:])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual({p.name for p in (destination / 'deps').iterdir()}, {'clock', 'random'})

    def test_comment_imports_cannot_claim_standard_profile_authority(self):
        source = self.root / 'wit'; source.mkdir()
        path = source / 'app.wit'
        for number, profile in enumerate((facilities.PROFILE, facilities.LOGGING_PROFILE)):
            imports = facilities.PROFILE_IMPORTS[profile]
            comment = ('// import ' + imports[0] + ';\n'
                       '/* examples /* import ' + imports[-1] + '; */ end */\n')
            text = 'package test:app;\n' + comment + 'world service { export api; }\ninterface api { run: func(); }\n'
            path.write_text(text, encoding='utf-8')
            original = path.read_bytes()
            destination = self.root / f'derived-{number}'
            facilities.stage(source, 'test:app/service', destination, ROOT / 'wit/platform', profile=profile)
            offset = text.index('world service {') + len('world service {')
            additions = ''.join('\n    import ' + name + ';' for name in imports) + '\n'
            self.assertEqual((destination / path.name).read_text(encoding='utf-8'),
                             text[:offset] + additions + text[offset:])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual({p.name for p in (destination / 'deps').iterdir()},
                             {'clock', 'random'} if profile == facilities.PROFILE else {'log'})

    def test_comments_cannot_hide_real_profile_imports_or_ambiguous_worlds(self):
        source = self.root / 'wit'; source.mkdir()
        path = source / 'app.wit'
        for number, (body, reason) in enumerate((
                ('world service { import /* standard */ latent:clock/wall@0.1.0; }',
                 'imports-must-be-owned-by-profile'),
                ('world service {} /* world service {} */ world service {}',
                 'requires-one-selected-world-declaration'),
                ('/* world service { import latent:clock/wall@0.1.0; } */',
                 'requires-one-selected-world-declaration'))):
            path.write_text('package test:app;\n' + body, encoding='utf-8')
            original = path.read_bytes()
            destination = self.root / f'derived-{number}'
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, reason):
                facilities.stage(source, 'test:app/service', destination, ROOT / 'wit/platform')
            self.assertFalse(destination.exists())
            self.assertEqual(path.read_bytes(), original)

    def test_unterminated_block_comment_cannot_publish_a_derived_world(self):
        source = self.root / 'wit'; source.mkdir()
        path = source / 'app.wit'
        for number, suffix in enumerate(('/* unfinished', '/* outer /* nested */ unfinished')):
            path.write_text('package test:app; world service {}\n' + suffix, encoding='utf-8')
            original = path.read_bytes()
            destination = self.root / f'derived-{number}'
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'unterminated-wit-comment'):
                facilities.stage(source, 'test:app/service', destination, ROOT / 'wit/platform')
            self.assertFalse(destination.exists())
            self.assertEqual(path.read_bytes(), original)

    def test_quoted_comment_markers_and_escapes_cannot_hide_following_code(self):
        literal = '"world service {} /* not a comment \\" // still quoted */"'
        declaration = '\r\nworld service { import latent:clock/wall@0.1.0; }\n'
        text = literal + declaration
        visible = facilities.code_view(text)
        self.assertEqual(len(visible), len(text))
        self.assertEqual(visible[:len(literal)], ' ' * len(literal))
        self.assertEqual(visible[len(literal):], declaration)
        for text in ('"unterminated', '"escaped ending \\"'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'unterminated-wit-string'):
                facilities.code_view(text)

    def test_dependency_graph_must_select_same_runtime_as_captured_application(self):
        from tools.application_dependency_store import DependencyError
        from tools.c_dependency_authoring import manifest
        selected = {'runtimeProfile': facilities.PROFILE}
        self.assertEqual(facilities.selected_profile(selected, {'selection': selected}), facilities.PROFILE)
        for graph in ({'selection': {'runtimeProfile': facilities.DEFAULT}},
                      {'selection': {'runtimeProfile': 'unknown'}}):
            with self.subTest(graph=graph), self.assertRaisesRegex(ValueError, 'selection-mismatch'):
                facilities.selected_profile(selected, graph)
        declaration = {'formatVersion': 1, 'language': 'c', 'selection': selected,
                       'nativeLocks': [], 'artifacts': [], 'transformations': []}
        self.assertEqual(manifest(declaration)['selection'], selected)
        for invalid in (None, True, [], {}, 'unknown'):
            with self.subTest(profile=invalid), self.assertRaisesRegex(DependencyError, 'runtime-profile-not-installed'):
                manifest({**declaration, 'selection': {'runtimeProfile': invalid}})

    def test_derived_contracts_cannot_modify_captured_source_or_platform_inputs(self):
        root = project.create(self.root / 'project', 'greeting')
        before = project.snapshot(root)
        source, platform = root / 'wit', root / 'vendor/lsf/wit/platform'
        for destination in (source, source / 'derived', platform / 'derived', root):
            with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, 'must-not-overlap'):
                facilities.stage(source, 'service', destination, platform)
            self.assertEqual(project.snapshot(root), before)

    def test_external_standard_library_probe_compiles_only_captured_closure_and_explicit_profile(self):
        from tools import application_dependencies as dependencies
        from tools.c_standard_facilities_probe import prepare
        from tools.c_application_dependencies import selected
        from tools.guest_runtime_profiles import profiles
        root = project.create(self.root / 'project', 'greeting')
        proof = prepare(root)
        self.assertTrue(proof['originalLibraryRemoved'])
        files = project.snapshot(root)
        value, _, _ = project.validate(files)
        self.assertEqual(value['runtimeProfile'], facilities.PROFILE)
        output, work = self.root / 'output', self.root / 'work'
        output.mkdir(); work.mkdir()
        closure = dependencies.prepare(root, work, output, 'c')
        observed = selected(closure, compiler_digest=digest(b'compiler'), runtime_digest=digest(b'runtime'),
                            runtime_profile=facilities.PROFILE)
        self.assertEqual(observed.receipt['runtimeProfile'], facilities.PROFILE)
        self.assertEqual(observed.sources[0].name, 'clock_probe.c')
        self.assertIn(b'getentropy(bytes, 256)', observed.sources[0].read_bytes())
        self.assertNotIn(b'latent_', observed.sources[0].read_bytes())
        self.assertEqual(profiles('c')['random'][2], 'bytes')
        self.assertEqual(profiles('go')['random'][2], 'u64-value')
        self.assertEqual(profiles('dotnet'), {'clockMonotonic': profiles('c')['clockMonotonic']})
        closure.check_unchanged()

    def test_c_execution_profile_cannot_be_selected_for_another_language_or_with_implicit_consent(self):
        from tools.run_rust_capsule_workflow import run
        for language, selected in (('java', True), ('c', 1), ('c', 'yes')):
            destination = self.root / 'must-not-exist'
            with self.subTest(language=language, selected=selected), self.assertRaisesRegex(RuntimeError, 'c-standard-facilities-language'):
                run(Path('missing'), Path('missing'), Path('missing'), destination,
                    language=language, c_standard_facilities=selected)
            self.assertFalse(destination.exists())

    def test_receipt_cannot_borrow_profile_or_original_runtime_after_rehash(self):
        root = project.create(self.root / 'project', 'greeting')
        files = project.snapshot(root)
        value = json.loads(files['capsule-project.json'])
        files['capsule-project.json'] = json.dumps({**value, 'runtimeProfile': facilities.PROFILE}).encode()
        component = b'controlled component identity, not runtime qualification'
        materials = [{'name': 'build-recipe', 'digest': digest(b'actual recipe'), 'size': 13}]
        receipts.emit(self.root, 'c', facilities.PROFILE, files, inventory(files), component, materials,
                      graph=None, binding_digest=digest(b'actual derived bindings'), configuration={})
        receipt = receipts.read((self.root / 'standard-runtime-selection.json').read_bytes())
        receipts.verify_build(receipt, 'c', files, inventory(files), component, materials)
        self.assertEqual((receipt['qualification'], receipt['apiSupport'], receipt['authority']),
                         ('unknown', 'not-evaluated', 'none'))
        changed = dict(files)
        changed['capsule-project.json'] = json.dumps({**value, 'runtimeProfile': facilities.DEFAULT}).encode()
        receipt['sourceDigest'] = digest(inventory(changed))
        receipt['identity'] = digest(receipts.encode({k: v for k, v in receipt.items() if k != 'identity'}))
        with self.assertRaisesRegex(DevError, 'stale-profile'):
            receipts.verify_build(receipt, 'c', changed, inventory(changed), component, materials)


    def test_libfetch_profile_derives_only_typed_streams_and_preserves_dependency_selection(self):
        from tools.c_dependency_authoring import manifest
        profile = facilities.FETCH_PROFILE
        original_defines = ('_POSIX_C_SOURCE=200809L',)
        self.assertEqual(facilities.compiler_defines(profile, original_defines),
                         (*original_defines, '_GNU_SOURCE=1', '_WASI_EMULATED_MMAN=1'))
        selected_defines = ('_GNU_SOURCE=1', '_POSIX_C_SOURCE=200809L', '_WASI_EMULATED_MMAN=1')
        self.assertIs(facilities.compiler_defines(profile, selected_defines), selected_defines)
        for old_profile in (facilities.DEFAULT, facilities.PROFILE,
                            facilities.LOGGING_PROFILE, facilities.COMBINED_PROFILE):
            self.assertIs(facilities.compiler_defines(old_profile, original_defines), original_defines)
        declaration = {'formatVersion': 1, 'language': 'c', 'selection': {'runtimeProfile': profile},
                       'nativeLocks': [], 'artifacts': [], 'transformations': []}
        self.assertEqual(manifest(declaration)['selection'], declaration['selection'])
        self.assertEqual(facilities.selected_profile({'runtimeProfile': profile},
                         {'selection': declaration['selection']}), profile)
        with self.assertRaisesRegex(ValueError, 'selection-mismatch'):
            facilities.selected_profile({'runtimeProfile': profile},
                                        {'selection': {'runtimeProfile': facilities.DEFAULT}})
        source = self.root / 'source'; source.mkdir()
        original = b'package example:client; world service { export api; } interface api { run: func(); }\n'
        (source / 'world.wit').write_bytes(original)
        selected = facilities.stage(source, 'service', self.root / 'derived', ROOT / 'wit/platform', profile=profile)
        text = (selected / 'world.wit').read_text()
        self.assertEqual(text.count('import latent:http/streaming@0.3.0;'), 1)
        self.assertNotIn('latent:http/client@', text)
        self.assertNotIn('wasi:', text)
        self.assertEqual((source / 'world.wit').read_bytes(), original)
        self.assertEqual({path.name for path in (selected / 'deps').iterdir()}, {'http-v3'})

        expanded = facilities.FETCH_STANDARD_PROFILE
        self.assertEqual(facilities.PROFILE_IMPORTS[expanded],
                         (*facilities.PROFILE_IMPORTS[profile], *facilities.IMPORTS))
        self.assertEqual(facilities.PROFILE_SOURCES[expanded],
                         (*facilities.PROFILE_SOURCES[profile], 'standard-clock-entropy.c'))
        self.assertEqual(facilities.compiler_defines(expanded, original_defines),
                         facilities.compiler_defines(profile, original_defines))
        self.assertEqual(facilities.selected_profile({'runtimeProfile': expanded}), expanded)
        with_clock = facilities.stage(source, 'service', self.root / 'derived-clock',
                                      ROOT / 'wit/platform', profile=expanded)
        clock_text = (with_clock / 'world.wit').read_text()
        for contract in facilities.PROFILE_IMPORTS[expanded]:
            self.assertEqual(clock_text.count('import ' + contract + ';'), 1)
        self.assertNotIn('latent:log/log@', clock_text)
        self.assertNotIn('wasi:', clock_text)
        self.assertEqual((source / 'world.wit').read_bytes(), original)

        # Exercise the real command builder, stopping before any external tool.
        # A client that calls no clock/entropy API still has this exact profile.
        from unittest.mock import patch
        from tools.c_guest.compiler import Compiler
        from tools.tests.test_c_threading_profile import graph
        from tools.c_guest.threading import PROFILE as threading_profile
        class CommandCaptured(Exception):
            pass
        source = self.root / 'unused-standard-api.c'
        source.write_bytes(b'int ordinary_library_value;\n')
        compiler = Compiler.__new__(Compiler)
        compiler.paths = {'zig': self.root / 'zig',
                          'c-threading-transformer': self.root / 'transformer'}
        compiler.sdk, compiler.platform = ROOT / 'sdk/c-guest', None
        compiler.commands, compiler.isolation = None, None
        compiler.validate_static_libraries = lambda *args: None
        compiler.select_threading_clock_inputs = lambda: None
        calls = []
        def run(tool, *arguments):
            if tool == 'zig':
                calls.append(arguments)
                raise CommandCaptured()
            self.assertEqual((tool, arguments[:2]), ('wasm-tools', ('component', 'wit')))
            return json.dumps(graph())
        compiler.run = run
        def generate(_run, _wit, _world, destination, _platform, *, sync_core_abi=False):
            self.assertTrue(sync_core_abi)
            destination.mkdir()
            return destination, {'source': 'controlled-binding-boundary'}
        expected = ('-Wl,--undefined=__imported_wasi_snapshot_preview1_clock_time_get',
                    '-Wl,--undefined=__imported_wasi_snapshot_preview1_random_get')
        lowering = (ROOT / 'sdk/c-guest/src/standard-clock-entropy.c').read_text()
        for symbol in expected:
            self.assertIn('int32_t ' + symbol.split('=', 1)[1] + '(', lowering)
        for ordinal, selected in enumerate(sorted(facilities.SUPPORTED)):
            with self.subTest(selected=selected), patch('tools.c_guest.compiler.generate', generate):
                with self.assertRaises(CommandCaptured):
                    compiler.compile([source], self.root / 'unused-wit', 'service',
                        self.root / ('command-' + str(ordinal)), runtime_profile=selected, memory_bytes=32 * 1024 * 1024,
                        threading_profile=threading_profile)
            command = calls[-1]
            self.assertEqual(tuple(item for item in command if item.startswith('-Wl,--undefined=')),
                             expected if selected == expanded else ())
            self.assertIn('-Wl,--max-memory=33554432', command)
            self.assertIn('-Wl,-z,stack-size=135168', command)
            self.assertNotIn('--allow-undefined', command)
            self.assertFalse(any(item.startswith('-Wl,--export=__imported_wasi_') for item in command))

    def test_libfetch_unthreaded_build_refuses_before_binding_generation_or_output(self):
        from unittest import mock
        from tools.c_guest.compiler import Compiler
        compiler = Compiler.__new__(Compiler)
        output = self.root / 'must-not-exist'
        for profile in facilities.FETCH_PROFILES:
            with self.subTest(profile=profile), mock.patch('tools.c_guest.compiler.generate') as generate:
                with self.assertRaisesRegex(ValueError, 'libfetch-http-requires-cooperative-threading'):
                    compiler.compile([self.root / 'missing.c'], self.root / 'missing-wit',
                                     'service', output, runtime_profile=profile)
                generate.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
