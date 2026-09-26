"""The required build gates cannot succeed with missing or ambiguous harnesses."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.run_angular_build_tests import ROOT, SUITES, harnesses


class AngularHarnessTests(unittest.TestCase):
    def test_source_ownership_separates_same_named_integration_targets_and_requires_successful_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'target'
            (target / 'debug/deps').mkdir(parents=True)
            records, expected = [], {}
            for index, (source, _, _) in enumerate(SUITES):
                executable = target / f'debug/deps/angular_build-{index}'
                executable.write_bytes(b'fixture harness')
                expected[source] = executable
                records.append({'reason': 'compiler-artifact', 'profile': {'test': True},
                                'target': {'src_path': str(ROOT / source), 'name': 'angular_build'},
                                'executable': str(executable)})
            finished = {'reason': 'build-finished', 'success': True}
            manifest = root / 'build.jsonl'
            def write(rows):
                manifest.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            write([*records, finished])
            self.assertEqual(harnesses(manifest, target), expected)
            second = target / 'debug/deps/ambiguous'
            second.write_bytes(b'second harness')
            for rows in (records, [*records[:-1], finished], [*records, {'reason': 'build-finished', 'success': False}],
                         [*records, {**records[0], 'executable': str(second)}, finished],
                         [*records, finished, finished],
                         [{**row, 'profile': {'test': False}} for row in records] + [finished]):
                write(rows)
                with self.assertRaises(RuntimeError):
                    harnesses(manifest, target)


if __name__ == '__main__':
    unittest.main()
