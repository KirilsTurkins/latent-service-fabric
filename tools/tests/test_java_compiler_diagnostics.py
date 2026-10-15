import json
from pathlib import Path
import tempfile
import unittest

from tools import guest_compatibility as compatibility
from tools.build_snapshot import digest
from tools.java_guest import compiler_diagnostics as diagnostics


class JavaCompilerDiagnostics(unittest.TestCase):
    SOURCE = b'{"captured":"source"}\n'
    COMPILER = b'{"captured":"compiler"}\n'
    JAR = 'sha256:' + 'a' * 64
    NATIVE = ('Method outside.owner.Surface.nativeValue()I is native but has no '
              'org.teavm.interop.Import annotation on it')
    REFLECTION = 'Method java.lang.Class.getGenericSuperclass()Ljava/lang/reflect/Type; was not found'

    def classpath(self):
        return {'artifacts': [{'id': 'arbitrary-changing-private-name/19', 'originalDigest': self.JAR,
            'entries': [{'path': 'outside/owner/Surface.class'}]}]}

    def observe(self, text, classpath=None):
        return diagnostics.findings(text.encode(), self.classpath() if classpath is None else classpath,
                                    digest(self.SOURCE))

    def test_native_method_uses_selected_original_class_owner_without_package_catalogue(self):
        found, omitted = self.observe(self.NATIVE)
        self.assertEqual(omitted, 0)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['classification'], 'target-incompatible')
        self.assertEqual(found[0]['packageDigest'], self.JAR)
        self.assertEqual(found[0]['symbol'], 'outside.owner.Surface.nativeValue')
        self.assertEqual(found[0]['sourceDigest'], digest(self.SOURCE))
        self.assertEqual(self.observe(self.NATIVE, {'artifacts': []}), ([], 0))

    def test_standard_runtime_missing_methods_and_classes_are_separate_from_missing_libraries(self):
        text = '\n'.join((self.REFLECTION, 'Class java.net.CookieManager was not found',
            'Class outside.owner.Missing was not found', 'Class javax.customer.Missing was not found',
            'Method outside.owner.Missing.value()I was not found'))
        found, omitted = self.observe(text)
        self.assertEqual(omitted, 0)
        self.assertEqual({row['symbol'] for row in found},
                         {'java.lang.Class.getGenericSuperclass', 'java.net.CookieManager'})
        self.assertTrue(all(row['classification'] == 'missing-runtime-port' and row['ownerIssue'] == 741
                            for row in found))
        self.assertTrue(all('packageDigest' not in row for row in found))

    def test_unknown_partial_and_injected_diagnostics_cannot_create_authority_or_elimination(self):
        found, omitted = self.observe('\n'.join((self.NATIVE + ' https://private.invalid/?token=secret',
            'prefix ' + self.REFLECTION, 'native method may be unsupported', 'permission-denied',
            'Method java.lang.Class.secret$token()I was not found', 'library reached unsupported operation')))
        self.assertEqual((found, omitted), ([], 0))

    def test_duplicate_omission_and_log_bounds_remain_explicit(self):
        text = '\n'.join('Class java.runtime.Missing' + str(n) + ' was not found' for n in range(70))
        found, omitted = self.observe(text + '\n' + text)
        self.assertEqual(len(found), compatibility.MAX_FINDINGS)
        self.assertEqual(omitted, 6)
        with self.assertRaisesRegex(ValueError, 'java-compiler-diagnostic-log-bound'):
            diagnostics.findings(b'x' * (diagnostics.MAX_LOG + 1), self.classpath(), digest(self.SOURCE))
        ambiguous = self.classpath()
        ambiguous['artifacts'].append(dict(ambiguous['artifacts'][0]))
        with self.assertRaisesRegex(ValueError, 'ambiguous-classpath'):
            self.observe(self.NATIVE, ambiguous)

    def fixture(self, root):
        (root / 'compiler-logs').mkdir()
        (root / 'compiler-logs/8-java-to-c.log').write_text(self.NATIVE + '\n' + self.REFLECTION,
                                                         encoding='utf-8')
        (root / 'BUILD-FAILED.json').write_text(json.dumps({'stage': 'compile', 'reason': 'original failure',
            'commands': [{'stage': 'java-to-c', 'exitCode': 1}]}), encoding='utf-8')
        (root / 'source-inputs.json').write_bytes(self.SOURCE)
        (root / 'compiler-inputs.json').write_bytes(self.COMPILER)
        (root / 'java-classpath.json').write_text(json.dumps(self.classpath()), encoding='utf-8')
        report = compatibility.report('java', digest(self.SOURCE), None, 'lsf-host-abi-phase3-v5', [],
            [compatibility.finding('unresolved-behavior', 'compile', 'not-evaluated')])
        (root / 'compatibility-report.json').write_text(json.dumps(report), encoding='utf-8')
        return {'expected_source': self.SOURCE, 'expected_compiler': self.COMPILER,
                'expected_classpath': self.classpath()}

    def test_observed_report_preserves_original_unknown_failure_and_issues_no_authority(self):
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            expected = self.fixture(root)
            before = {name: (root / name).read_bytes() for name in ('BUILD-FAILED.json', 'compatibility-report.json')}
            diagnostics.emit(root, 'compile', **expected)
            report = compatibility.read((root / 'compatibility-java-compiler-report.json').read_bytes())
            self.assertEqual(report['status'], 'blocked')
            self.assertEqual(report['authority'], 'none')
            self.assertEqual(report['componentDigest'], None)
            self.assertEqual({row['classification'] for row in report['findings']},
                             {'unresolved-behavior', 'target-incompatible', 'missing-runtime-port'})
            self.assertTrue(all((root / name).read_bytes() == raw for name, raw in before.items()))
            self.assertIn('java.lang.Class.getGenericSuperclass', compatibility.present(report))

    def test_stale_source_compiler_or_classpath_never_receives_attribution(self):
        for filename, raw in (('source-inputs.json', b'changed source'),
                              ('compiler-inputs.json', b'changed compiler'),
                              ('java-classpath.json', b'{"artifacts":[]}')):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as owned:
                root = Path(owned)
                expected = self.fixture(root)
                (root / filename).write_bytes(raw)
                diagnostics.emit(root, 'compile', **expected)
                self.assertFalse((root / 'compatibility-java-compiler-report.json').exists())
                unavailable = json.loads((root / 'compatibility-java-compiler-failed.json').read_bytes())
                self.assertEqual(unavailable['status'], 'unavailable')
                self.assertEqual(json.loads((root / 'BUILD-FAILED.json').read_bytes())['reason'], 'original failure')

    def test_unrelated_or_successful_compiler_stages_never_satisfy_native_failure_evidence(self):
        for stage, command in (('compile', {'stage': 'java-to-c', 'exitCode': 0}),
                               ('compile', {'stage': 'c-to-wasm', 'exitCode': 1}),
                               ('compile', {'stage': 'java-to-c', 'exitCode': None}),
                               ('compiler-inputs', {'stage': 'java-to-c', 'exitCode': 1})):
            with self.subTest(stage=stage, command=command), tempfile.TemporaryDirectory() as owned:
                root = Path(owned)
                expected = self.fixture(root)
                (root / 'BUILD-FAILED.json').write_text(json.dumps({'stage': stage, 'commands': [command]}))
                diagnostics.emit(root, stage, **expected)
                self.assertFalse((root / 'compatibility-java-compiler-report.json').exists())
                self.assertFalse((root / 'compatibility-java-compiler-failed.json').exists())


if __name__ == '__main__':
    unittest.main()
