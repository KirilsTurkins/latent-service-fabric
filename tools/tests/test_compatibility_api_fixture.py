"""Pure source/project/CLI-boundary controls; no compiler or guest execution."""
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import compatibility_api_fixture as fixture
from tools.rust_capsule_project import canonical, digest, inventory, read_json, snapshot


class CompatibilityApiFixture(unittest.TestCase):
    def test_only_one_fixed_root_edge_changes_and_original_transitive_api_sources_remain_identical(self):
        for language in fixture.LANGUAGES:
            with self.subTest(language=language):
                original = fixture.application_source(language)
                reached = fixture.application_source(language, reached=True)
                old, new = fixture.ROOT_EDGES[language]
                self.assertEqual(original.count(old), 1)
                self.assertEqual(reached, original.replace(old, new, 1))
                self.assertNotIn(old, reached)
                libraries = fixture.library_sources(language)
                self.assertEqual(libraries, fixture.library_sources(language))
                combined = b'\n'.join(libraries.values())
                self.assertIn({'c': b'fopen("lsf-api-fixture", "rb")',
                    'rust': b'std::fs::File::open("lsf-api-fixture")',
                    'go': b'os.Open("lsf-api-fixture")'}[language], combined)
                self.assertIn({'c': b'ENOTSUP', 'rust': b'ErrorKind::Unsupported',
                    'go': b'errors.ErrUnsupported'}[language], combined)
                self.assertIn(b'callback', combined.lower())
                self.assertNotIn(b'lsf-api-root-edge', combined)
                self.assertIn({'c': b'noinline', 'rust': b'inline(never)', 'go': b'go:noinline'}[language], original)
                self.assertIn({'c': b'noinline', 'rust': b'inline(never)', 'go': b'go:noinline'}[language], combined)
        for invalid in (None, 1, 'true'):
            with self.assertRaises(ValueError): fixture.application_source('c', reached=invalid)
        self.assertIn('volatile int baseline = 0;', fixture.C)
        self.assertIn('return baseline;', fixture.C)
        self.assertEqual(fixture.RUST.count('#[no_mangle]'), 1)
        from tools.guest_compiler_capture import automatic
        for reached in (False, True):
            raw = fixture.application_source('rust', reached=reached)
            self.assertEqual(raw.count(b'use outside_api_primary::probe;'), 1)
            self.assertNotIn(b'fn probe(', raw)
            queries = automatic({'src/lib.rs': raw}, 'rust')['queries']
            root = [q for q in queries if q['root'] == 'compatibility_root']
            self.assertEqual([(q['callee'], q['compilerTarget'], q['declarationState']) for q in root],
                [('probe', 'probe', 'unique-captured-candidate')])
            self.assertEqual(root[0]['calleeResolution'], 'unresolved-source-spelling')
        self.assertIn('#[inline(never)]\n#[no_mangle]\nfn compatibility_root()', fixture.RUST)
        with self.assertRaises(ValueError): fixture.library_sources('typescript')

    def test_actual_normal_project_creators_preserve_sdk_wit_limits_and_same_pair_library_bytes(self):
        for language in fixture.LANGUAGES:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                left = fixture.prepare(root / 'baseline', language)
                right = fixture.prepare(root / 'reached', language, reached=True)
                original = snapshot(Path(left['projectPath'])); changed = snapshot(Path(right['projectPath']))
                self.assertEqual(set(original), set(changed))
                self.assertEqual([name for name in original if original[name] != changed[name]], [fixture.SOURCES[language]])
                self.assertEqual(left['libraryIdentity'], right['libraryIdentity'])
                self.assertEqual(snapshot(Path(left['libraries'])), snapshot(Path(right['libraries'])))
                self.assertEqual(read_json(Path(left['projectPath']) / 'capsule-project.json')['name'], 'my-greeting')
                self.assertEqual(left['expectedScope'], 'exact-selected-compiler-call-edge')
                self.assertEqual(left['apiKey'], right['apiKey'])
                self.assertFalse(left['compilerExecuted'] or right['runtimeQualified'])
                self.assertEqual(left['globalApiElimination'], 'unknown')
                self.assertFalse((Path(left['projectPath']) / 'latent.dependencies.json').exists())
                with self.assertRaises(ValueError): fixture.prepare(root / 'baseline', language)

    def test_future_capture_uses_only_existing_normal_owner_steps_and_exact_candidate_review(self):
        # The actual project creator is used; the runner below only records argv
        # and writes a labelled synthetic candidate. No resolver/tool runs.
        with tempfile.TemporaryDirectory() as temporary:
            value = fixture.prepare(Path(temporary) / 'pair', 'c')
            calls = []
            def owner(label, operation, app, *args):
                calls.append((label, operation, app, args))
                if operation == 'resolve':
                    Path(args[args.index('--candidate') + 1]).write_bytes(canonical({'source-control': 'not-a-real-lock'}))
            result = fixture.capture(value, owner)
            self.assertEqual([row[1] for row in calls], ['add', 'resolve', 'review-lock', 'dependencies'])
            review = calls[2][3]
            self.assertEqual(review[-2:], ('--expect', result['candidateDigest']))
            self.assertFalse(result['componentCompiled'] or result['runtimeQualified'])
            expected = digest(canonical({'source-control': 'not-a-real-lock'}))
            self.assertEqual(result['candidateDigest'], expected)
            self.assertEqual(result['libraryIdentity'], digest(inventory(fixture.library_sources('c'))))
            # Accepted identity below is a labelled source-boundary double;
            # this does not represent a resolver or a real captured lock.
            app = Path(value['projectPath']); before = snapshot(app)
            with patch('tools.application_dependencies.verify_inputs', return_value=None):
                with self.assertRaisesRegex(ValueError, 'accepted-dependency-inputs-required'):
                    fixture.counterfactual(value)
            self.assertEqual(snapshot(app), before)
            accepted = SimpleNamespace(identity='sha256:' + 'a' * 64)
            with patch('tools.application_dependencies.verify_inputs', return_value=accepted) as verified:
                reached = fixture.counterfactual(value)
            self.assertEqual(verified.call_count, 2)
            self.assertEqual(verified.call_args_list[0].args, (app, 'c'))
            self.assertEqual(verified.call_args_list[1].args, (app, 'c'))
            after = snapshot(app)
            self.assertEqual(set(before), set(after))
            self.assertEqual([name for name in before if before[name] != after[name]], ['src/main.c'])
            self.assertEqual(after['src/main.c'], fixture.application_source('c', reached=True))
            self.assertEqual(reached['projectPath'], value['projectPath'])
            self.assertEqual(reached['libraryIdentity'], value['libraryIdentity'])
            self.assertEqual(reached['acceptedInputIdentity'], accepted.identity)
            self.assertEqual(reached['expectedResult'], [{'ok': 'api|c|unsupported'}])
            self.assertTrue(reached['reached']); self.assertFalse(value['reached'])
            self.assertEqual(len(calls), 4)  # No re-resolve or second author step.
            with self.assertRaisesRegex(ValueError, 'baseline-selection'):
                fixture.counterfactual(reached)

        # Actual ordinary C declaration/capture/review: filesystem/CAS only.
        # No mocked accepted closure, resolver, compiler or native process.
        from tools import c_capsule
        from tools.application_dependencies import verify_inputs
        with tempfile.TemporaryDirectory() as temporary:
            value = fixture.prepare(Path(temporary) / 'real-c', 'c')
            def normal_owner(_label, operation, app, *arguments):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = c_capsule.main([operation, str(app), *map(str, arguments)])
                self.assertEqual(code, 0, operation)
            fixture.capture(value, normal_owner)
            app = Path(value['projectPath']); identity = verify_inputs(app, 'c').identity
            reached = fixture.counterfactual(value)
            before = snapshot(app)
            self.assertEqual(verify_inputs(app, 'c').identity, identity)
            self.assertEqual(reached['acceptedInputIdentity'], identity)
            changed = fixture.initializer(reached)
            after = snapshot(app)
            self.assertEqual(set(before), set(after))
            self.assertEqual([name for name in before if before[name] != after[name]], ['src/main.c'])
            self.assertEqual(after['src/main.c'], fixture.initialization_source('c'))
            self.assertEqual(changed['acceptedInputIdentity'], identity)
            self.assertEqual(verify_inputs(app, 'c').identity, identity)
            self.assertEqual(changed['libraryIdentity'], value['libraryIdentity'])
            self.assertEqual(snapshot(Path(value['libraries'])), fixture.library_sources('c'))
            self.assertEqual(changed['initializationKind'], 'eager-c-constructor')
            self.assertEqual(changed['initializerExpectedCount'], 1)
            self.assertEqual(changed['expectedResult'], [{'ok': 'api|c|initialization|unsupported|result=42|count=1'}])
            with self.assertRaisesRegex(ValueError, 'reached-selection'):
                fixture.initializer(value)
            with self.assertRaisesRegex(ValueError, 'reached-source-drift'):
                fixture.initializer(changed)
        for language in fixture.LANGUAGES:
            raw = fixture.initialization_source(language)
            self.assertNotIn(b'lsf-api-root-edge', raw)
            # Original API is inside the same unmodified transitive child.
            self.assertNotIn({'c': b'fopen(', 'go': b'os.Open(', 'rust': b'File::open('}[language], raw)
            self.assertIn(b'result=42|count=1', raw)
        self.assertIn(b'__attribute__((constructor, noinline))', fixture.initialization_source('c'))
        self.assertIn(b'var initializerResult = compatibilityInitialize()', fixture.initialization_source('go'))
        rust = fixture.initialization_source('rust')
        self.assertEqual(rust.count(b'LazyLock::force(&INITIALIZER_RESULT)'), 2)
        self.assertEqual(rust.count(b'INITIALIZER_CALLS.fetch_add('), 1)
        self.assertIn(b'#[inline(never)]\n#[no_mangle]\nfn compatibility_root()', rust)
        self.assertTrue(rust.endswith(fixture.RUST[fixture.RUST.index('#[cfg(target_arch = "wasm32")]'):].encode()))

    def test_source_drift_refuses_before_any_normal_owner_command(self):
        for name, reason in (('libraries/child/child.c', 'library-source-drift'),
                             ('declarations/child.json', 'declaration-source-drift')):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                value = fixture.prepare(root / 'pair', 'c')
                selected = root / 'pair' / name
                selected.write_bytes(selected.read_bytes() + b'/* changed original */\n')
                calls = []
                with self.assertRaisesRegex(ValueError, reason):
                    fixture.capture(value, lambda *args: calls.append(args))
                self.assertEqual(calls, [])


if __name__ == '__main__': unittest.main()
