"""Current signed HTTP source inputs; no native preview or execution claims."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.java_transaction_schema import SOURCE, create
from tools.rust_capsule_project import read_file, read_json, snapshot
from tools.transaction_guest_project import CURRENT_HTTP_PROFILE, HTTP_REQUIREMENTS, package_effect_requirements


class CurrentJavaHttpInputs(unittest.TestCase):
    def test_early_http_denial_is_separate_and_retains_original_post_stage_rollback_input(self):
        from tools.compile_transaction_guests import authored_project
        from tools.java_transaction_http_denial import VARIANT
        from tools.transaction_guest_variants import create as original_variant
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = original_variant(root / 'original', 'java', 'forbidden-http')
            retained = snapshot(original)
            project = authored_project('java', VARIANT, root / 'early')
            files = snapshot(project)
            source = files[SOURCE]
            call = source.index(b'Bindings.LatentHttpClient.send(')
            self.assertLess(call, source.index(b'command.get(KEY)'))
            self.assertLess(call, source.index(b'command.put(KEY'))
            self.assertLess(call, source.index(b'.stage(command)'))
            self.assertLess(retained[SOURCE].index(b'.stage(command)'),
                            retained[SOURCE].index(b'Bindings.LatentHttpClient.send('))
            self.assertEqual(snapshot(original), retained)
            self.assertEqual(files['wit/world.wit'], retained['wit/world.wit'])
            self.assertEqual(read_json(project / 'capsule-project.json')['limits'],
                             read_json(original / 'capsule-project.json')['limits'])
            self.assertNotIn(CURRENT_HTTP_PROFILE, files)
            self.assertNotIn(HTTP_REQUIREMENTS, files)
            declaration = read_json(project / 'java-early-http-denial-input.json')
            for name in ('componentCompiled', 'signedExecutionQualified',
                         'immediateHttpDenialQualified', 'postStageRollbackQualified'):
                self.assertIs(declaration[name], False)
            for language in ('rust', 'c', 'typescript', 'go', 'dotnet'):
                with self.assertRaises(ValueError):
                    authored_project(language, VARIANT, root / ('refused-' + language))

    def test_early_http_compiler_selection_is_exclusive_before_creating_output(self):
        from tools.compile_transaction_guests import compile_guests
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'uncreated'
            for language, options in (('rust', {}), ('java', {'java_state_acceptance': True}),
                                     ('java', {'java_schema_put_once': True}),
                                     ('java', {'java_post_stage_diagnostic': True}),
                                     ('java', {'java_current_http_profile': 'qualified-http-v1:' + 'a' * 64})):
                with self.assertRaises(ValueError):
                    compile_guests(language, output, java_early_http_denial=True, **options)
                self.assertFalse(output.exists())

    def test_current_selection_changes_transport_operation_without_rewriting_legacy_custody(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = create(root / 'legacy', 'legacy-v1', effect='put-once')
            before = snapshot(legacy)
            current = create(root / 'current', 'legacy-v1', effect='current-http',
                             http_profile='qualified-http-v1:' + 'a' * 64)
            self.assertIn(b'new Intent("qualified-http", "http", effectPayload)', read_file(current / SOURCE))
            self.assertIn(b'new Intent("qualified-http", "put-once", effectPayload)', before[SOURCE])
            for path in ('wit/world.wit', 'transaction-binding.json', 'state-schema.json'):
                self.assertEqual(read_file(current / path), before[path])
            self.assertEqual(snapshot(legacy), before)
            declaration = read_json(current / HTTP_REQUIREMENTS)
            self.assertEqual(declaration['operation'], 'http')
            self.assertEqual(declaration['protocol'], 'lsf-atomic-idempotent-http-v1')
            self.assertEqual(declaration['ceiling']['maximum_payload_bytes'], 27)
            self.assertEqual(declaration['ceiling']['maximum_response_bytes'], 2048)
            self.assertEqual(read_json(current / 'capsule-project.json')['limits'],
                             read_json(legacy / 'capsule-project.json')['limits'])

    def test_packaging_keeps_exact_declared_current_native_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = create(root / 'current', 'writer-v2', effect='current-http',
                             http_profile='qualified-http-v1:' + 'b' * 64)
            output = root / 'packaged'
            output.mkdir()
            selected = package_effect_requirements(output, read_json(current / 'capsule-project.json'), snapshot(current))
            self.assertEqual(selected, (HTTP_REQUIREMENTS, 'asset', 'application/json'))
            self.assertEqual((output / HTTP_REQUIREMENTS).read_bytes(), read_file(current / HTTP_REQUIREMENTS))
            from tools.java_transaction_qualification.packaging import schema_assets
            files = snapshot(current)
            self.assertEqual(schema_assets(files)[CURRENT_HTTP_PROFILE], files[CURRENT_HTTP_PROFILE])
            missing = dict(files)
            del missing[CURRENT_HTTP_PROFILE]
            with self.assertRaises(ValueError):
                schema_assets(missing)
            changed = dict(files)
            marker = json.loads(changed[CURRENT_HTTP_PROFILE])
            marker["approved"] = True
            changed[CURRENT_HTTP_PROFILE] = json.dumps(marker).encode()
            with self.assertRaises(ValueError):
                schema_assets(changed)

    def test_changed_profile_or_added_approval_field_refuses_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = create(root / 'current', 'compatible-v2', effect='current-http',
                             http_profile='qualified-http-v1:' + 'c' * 64)
            files = snapshot(current)
            for name, change in (('profile', {'idempotencyProfile': 'qualified-http-v1:' + 'd' * 64}),
                                 ('approval', {'approved': True})):
                changed = copy.deepcopy(files)
                selected = json.loads(changed[CURRENT_HTTP_PROFILE])
                selected.update(change)
                changed[CURRENT_HTTP_PROFILE] = json.dumps(selected).encode()
                output = root / name
                output.mkdir()
                with self.assertRaises(ValueError):
                    package_effect_requirements(output, read_json(current / 'capsule-project.json'), changed)
                self.assertFalse((output / HTTP_REQUIREMENTS).exists())

    def test_profile_is_explicit_and_exclusive_before_project_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'uncreated'
            for value in (None, '', 'put-once', 'qualified-http-v1:' + 'A' * 64, True):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    create(output, 'legacy-v1', effect='current-http', http_profile=value)
                self.assertFalse(output.exists())
            with self.assertRaises(ValueError):
                create(output, 'legacy-v1', effect='put-once', http_profile='qualified-http-v1:' + 'e' * 64)
            self.assertFalse(output.exists())

    def test_compiler_profile_is_java_only_and_requires_an_explicit_selected_capture(self):
        from tools.compile_transaction_guests import compile_guests
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'uncreated'
            for language in ('rust', 'c', 'typescript', 'go', 'dotnet'):
                with self.subTest(language=language), self.assertRaises(ValueError):
                    compile_guests(language, output, java_current_http_profile='qualified-http-v1:' + 'f' * 64)
                self.assertFalse(output.exists())
            with self.assertRaises(ValueError):
                compile_guests('java', output, java_current_http_profile='qualified-http-v1:' + 'f' * 64)
            self.assertFalse(output.exists())

    def test_current_diagnostic_and_value_captures_keep_real_http_stage_and_fault_selector(self):
        from tools.compile_transaction_guests import authored_project
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for variant in ('put-once-diagnostics', 'put-once-values'):
                project = authored_project('java', variant, root / variant,
                    java_current_http_profile='qualified-http-v1:' + 'f' * 64)
                source = read_file(project / SOURCE)
                self.assertIn(b'new Intent("qualified-http", "http", effectPayload)', source)
                self.assertEqual(read_json(project / HTTP_REQUIREMENTS)['operation'], 'http')
                if variant == 'put-once-diagnostics':
                    self.assertLess(source.index(b'new Intent("qualified-http", "http"'),
                                    source.index(b'TransactionDiagnostics.afterStage'))
                    self.assertEqual(read_json(project / 'transaction-diagnostic-inputs.json')['selectors']['memoryAfterStage'],
                                     '4294967292')

    def test_read_only_cache_selection_refuses_wrong_language_missing_and_relative_roots(self):
        from tools.compile_transaction_guests import compile_guests
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / 'uncreated'
            for language, cache in (('rust', root), ('java', Path('relative')),
                                    ('java', root / 'missing'), ('java', str(root))):
                with self.subTest(language=language, cache=cache), self.assertRaises(ValueError):
                    compile_guests(language, output, java_read_only_cache=cache)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
