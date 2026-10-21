"""Passive metadata and bounded reader controls; not guest execution evidence."""
import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from tools.dev_workflow.common import digest, encode
from tools.java_guest import reachability as r


class CompilerMethods(unittest.TestCase):
    def test_both_normal_cli_diagnostic_options_are_default_false_and_explicit_selection_only(self):
        import ast
        import re
        from tools.java_capsule import parser as java_parser
        from tools.dotnet_capsule import parser as dotnet_parser
        for parser, extra in ((java_parser, []), (dotnet_parser, ['--tools', 'tools'])):
            args = ['build', 'project', '--output', 'out', '--repository', 'https://example.invalid', *extra]
            self.assertIs(parser().parse_args(args).compiler_methods, False)
            self.assertIs(parser().parse_args([*args, '--compiler-methods']).compiler_methods, True)
        # This optional flag must not cross the native serde recipe boundary.
        # Inspect the real producer dicts against the real closed Rust structs;
        # parser acceptance alone previously missed an unknown-field failure.
        root = Path(__file__).resolve().parents[2]
        model = (root/'crates/latent-signing/src/provenance/model.rs').read_text()
        native_controls = (root/'crates/latent-signing/tests/guest_provenance.rs').read_text()
        for path, name, compiler in (('tools/java_capsule_build.py', 'JavaCapsuleBuildParameters', 'teavm-c'),
                ('tools/dotnet_guest/build.py', 'DotnetCapsuleBuildParameters', 'native-aot-llvm')):
            text = (root/path).read_text()
            recipes = [ast.literal_eval(node) for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Dict)
                and any(isinstance(key, ast.Constant) and key.value == 'compiler'
                    and isinstance(value, ast.Constant) and value.value == compiler for key, value in zip(node.keys, node.values))]
            self.assertEqual(len(recipes), 1)
            declaration = re.search(r'#\[serde\(rename_all = "camelCase", deny_unknown_fields\)\]\npub struct '
                + name + r' \{([^}]+)\}', model)
            self.assertIsNotNone(declaration)
            camel = lambda value: value.split('_')[0] + ''.join(part.title() for part in value.split('_')[1:])
            fields = {camel(value) for value in re.findall(r'pub ([a-z_]+):', declaration[1])}
            self.assertEqual(set(recipes[0]), fields)
            self.assertNotIn('compilerMethods', text)
            self.assertIn("'compiler-method-observation-selection'", text)
            self.assertIn("'status': 'observed' if methods_material is not None else 'unavailable'", text)
        self.assertIn('fn java_recipe_and_every_observed_compiler_input_are_closed()', native_controls)
        self.assertIn('fn dotnet_capsules_require_the_closed_native_aot_recipe_and_separate_approval()', native_controls)
        self.assertIn('"unreviewedOption"', native_controls)

    def test_project_class_queries_use_passive_source_ownership_not_a_package_name_allowlist(self):
        payload, index = r.queries(self.classes, (), application_classes={'outside.Opaque'})
        self.assertIn(b'outside.Opaque', payload)
        self.assertEqual(index['classesInspected'], 1)
        payload, index = r.queries(self.classes, (), application_classes={'some.other.Input'})
        self.assertEqual(payload, b'')
        self.assertEqual(index['queries'], [])

    @classmethod
    def setUpClass(cls):
        cls.javac = shutil.which('javac')
        if cls.javac is None: raise unittest.SkipTest('JDK is required for passive actual-class metadata controls')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / 'Opaque.java'
        # Merely defining these classes must not execute this initializer.
        cls.source.write_text('package outside; public class Opaque { '
            'static { if(System.getProperty("allow.host.initializer") == null) throw new Error("must-not-run"); } '
            'public Opaque() {} public native int unsupportedNative(); '
            '@Deprecated public native int annotatedNative(); public int callback() { return 7; } }')
        cls.classes = cls.root / 'classes'
        subprocess.run([cls.javac, '-proc:none', '-d', str(cls.classes), str(cls.source)], check=True,
                       capture_output=True, timeout=30)
        cls.raw = (cls.classes / 'outside/Opaque.class').read_bytes()

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def fixture(self):
        payload, index = r.queries(self.classes, ())
        marker = r.MARKER + 'complete;' + ','.join(row['id'] + '=not-retained' for row in index['queries'])
        return payload, index, marker

    def test_actual_javac_metadata_contains_initializer_constructor_native_and_callback_without_loading_it(self):
        owner, methods = r.class_methods(self.raw)
        self.assertEqual(owner, 'outside.Opaque')
        names = {row['method']: row for row in methods}
        self.assertEqual(names['<clinit>()V']['kind'], 'initialization')
        self.assertEqual(names['<init>()V']['kind'], 'constructor')
        self.assertTrue(names['unsupportedNative()I']['nativeWithoutAnnotations'])
        self.assertFalse(names['annotatedNative()I']['nativeWithoutAnnotations'])
        self.assertIn('callback()I', names)

    def test_transitive_captured_jar_identity_and_same_class_ambiguity_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); jar = root / 'unregistered-7.3.jar'; empty = root / 'classes'; empty.mkdir()
            with zipfile.ZipFile(jar, 'w') as archive: archive.writestr('outside/Opaque.class', self.raw)
            _, index = r.queries(empty, (jar,))
            self.assertTrue(all(row['packageDigest'] == digest(jar.read_bytes()) for row in index['queries']))
            with self.assertRaisesRegex(ValueError, 'ambiguous-class'): r.queries(self.classes, (jar,))

    def test_completed_marker_must_bind_every_exact_query_once(self):
        _, index, marker = self.fixture()
        observed = r.observation(marker, index)
        self.assertTrue(all(row['state'] == 'not-retained' for row in observed['methods']))
        for invalid in ('', marker + '\n' + marker, marker + ',invalid=linked', marker.replace('complete;', 'partial;'),
                        marker.replace('not-retained', 'executed', 1)):
            with self.subTest(invalid=invalid[:60]), self.assertRaises(ValueError): r.observation(invalid, index)

    def test_native_not_retained_does_not_claim_api_unsupported_or_execution(self):
        _, index, marker = self.fixture()
        identities = {name: digest(name.encode()) for name in ('source', 'component', 'compiler', 'recipe', 'graph')}
        value = r.bind(r.observation(marker, index), **identities)
        self.assertEqual(value['runtimeExecution'], 'not-observed')
        self.assertEqual(value['workerDrain'], 'unproven')
        self.assertTrue(all(row['apiClassification'] == 'unknown' for row in value['methods']))
        self.assertNotIn('unsupported-eliminated', encode(value).decode())
        for name in identities:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'stale'):
                r.validate(value, **{name: digest(b'detached')})

    def test_rehashed_report_cannot_turn_compiler_presence_into_api_support_or_execution(self):
        _, index, marker = self.fixture()
        value = r.bind(r.observation(marker, index), **{name: digest(name.encode())
                       for name in ('source', 'component', 'compiler', 'recipe', 'graph')})
        for field, claim in (('runtimeExecution', 'executed'), ('apiSupport', 'supported'),
                             ('workerDrain', 'retired'), ('initializersExecuted', True)):
            changed = copy.deepcopy(value); changed[field] = claim
            changed['identity'] = digest(encode({k: v for k, v in changed.items() if k != 'identity'}))
            with self.subTest(field=field), self.assertRaises(ValueError): r.validate(changed)

    def test_truncated_class_or_changed_magic_fails_before_query_generation(self):
        for invalid in (self.raw[:-1], b'x' + self.raw[1:], self.raw[:20]):
            with self.subTest(size=len(invalid)), self.assertRaises(ValueError): r.class_methods(invalid)

    def test_all_methods_are_counted_but_only_sixty_four_queries_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'Many.java'
            source.write_text('public class Many {' + ''.join('public int m' + str(i) + '(){return 1;}'
                                                             for i in range(100)) + '}')
            subprocess.run([self.javac, '-proc:none', '-d', str(root / 'classes'), str(source)],
                           check=True, capture_output=True, timeout=30)
            payload, index = r.queries(root / 'classes', ())
            self.assertEqual(len(index['queries']), 64)
            self.assertEqual(index['omittedMethods'], 37)
            self.assertLessEqual(len(payload), 65536)


if __name__ == '__main__': unittest.main()
