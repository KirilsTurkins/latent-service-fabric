"""Owned-stack acceptance cannot substitute unrelated or failed clock inputs."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import qualify_owned_native_stacks as gate
from tools.dev_workflow.common import DevError


class OwnedStackInputs(unittest.TestCase):
    def fixture(self, root):
        path = root / 'wall'
        path.mkdir()
        raw = b'actual component bytes'
        marker = {'clockKind': 'wall', 'profile': gate.clocks.clock.std.PROFILE,
                  'applicationClockSdkCalled': False, 'componentDigest': gate.digest(raw),
                  'sysrootIdentity': 'exact-built-source-identity'}
        result = {'status': 'passed', 'component': marker,
                  'nativeFixture': {'testDigest': 'exact-current-test'}}
        summary = {'schemaVersion': 'latent.rust.standard-clocks-gate.v1', 'status': 'passed',
                   'clocks': {'wall': {'componentDigest': marker['componentDigest'],
                                       'sysrootIdentity': marker['sysrootIdentity']}}}
        (path / 'component.wasm').write_bytes(raw)
        self.write(root / 'report.json', summary)
        self.write(path / 'qualification.json', result)
        self.write(path / 'clock-guest.json', marker)
        return marker, result, summary

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def test_exact_passed_component_and_native_identity_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker, _, _ = self.fixture(root)
            self.assertEqual(gate.clock_input(root, 'wall', 'exact-current-test'), marker)
            with self.assertRaisesRegex(DevError, 'native-source-identity'):
                gate.clock_input(root, 'wall', 'earlier-native-test')
            (root / 'wall/component.wasm').write_bytes(b'mutated')
            with self.assertRaisesRegex(DevError, 'component-identity'):
                gate.clock_input(root, 'wall', 'exact-current-test')

    def test_failed_baseline_or_result_and_mismatched_sysroot_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, result, summary = self.fixture(root)
            for location, original in ((root / 'report.json', summary),
                                        (root / 'wall/qualification.json', result)):
                self.write(location, {**original, 'status': 'component-prepared'})
                with self.assertRaisesRegex(DevError, 'baseline-not-passed'):
                    gate.clock_input(root, 'wall', 'exact-current-test')
                self.write(location, original)
            summary['clocks']['wall']['sysrootIdentity'] = 'other-source'
            self.write(root / 'report.json', summary)
            with self.assertRaisesRegex(DevError, 'native-source-identity'):
                gate.clock_input(root, 'wall', 'exact-current-test')

    def test_unknown_profile_kind_rejects_before_accessing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(DevError, 'clock-kind'):
                gate.clock_input(Path(directory) / 'absent', 'threads', 'exact-current-test')


if __name__ == '__main__':
    unittest.main()
