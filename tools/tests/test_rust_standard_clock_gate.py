"""A native gate must bind successful exact harness and compiler source inputs."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_rust_standard_clocks as gate
from tools.dev_workflow.common import DevError


class ClockGateInputs(unittest.TestCase):
    def records(self, target):
        native = target / 'debug/deps/clock_admission-current'
        native.parent.mkdir(parents=True)
        native.write_bytes(b'current actual executable')
        return [{'reason': 'compiler-artifact', 'manifest_path': str(
            gate.ROOT / 'crates/latent-wasmtime/Cargo.toml'),
            'target': {'name': 'clock_admission', 'kind': ['test']},
            'profile': {'test': True}, 'executable': str(native)},
            {'reason': 'build-finished', 'success': True}]

    def raw(self, rows):
        return b'\n'.join(json.dumps(row).encode() for row in rows)

    def test_current_successful_exact_target_is_selected_without_globbing_stale_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            rows = self.records(target)
            (target / 'debug/deps/clock_admission-stale').write_bytes(b'failed earlier executable')
            self.assertEqual(gate.test_executable(self.raw(rows), target),
                             Path(rows[0]['executable']))

    def test_failed_incomplete_duplicate_and_postterminal_inventories_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            rows = self.records(target)
            for changed in (rows[:-1], [rows[0], {'reason': 'build-finished', 'success': False}],
                            [rows[0], *rows], [*rows, rows[0]]):
                with self.subTest(changed=changed), self.assertRaises(DevError):
                    gate.test_executable(self.raw(changed), target)

    def test_wrong_manifest_kind_profile_and_outside_executables_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target'
            rows = self.records(target)
            outside = root / 'outside'
            outside.write_bytes(b'not an output')
            for changes in ({'manifest_path': str(root / 'Cargo.toml')},
                            {'target': {'name': 'clock_admission', 'kind': ['bin']}},
                            {'profile': {'test': False}}, {'executable': str(outside)}):
                with self.subTest(changes=changes), self.assertRaises(DevError):
                    gate.test_executable(self.raw([{**rows[0], **changes}, rows[1]]), target)

    def test_source_download_identity_rejects_before_any_archive_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.tar.xz'
            with patch.object(gate.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong')) as fetch:
                with self.assertRaisesRegex(DevError, 'download-identity'):
                    gate.source_archive(path)
            fetch.assert_called_once_with(gate.URL, timeout=30)
            self.assertFalse(path.exists())

    def test_source_download_bound_and_authenticated_bytes_preserve_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.tar.xz'
            with patch.object(gate, 'MAX_SOURCE', 3), patch.object(gate.urllib.request, 'urlopen',
                    return_value=io.BytesIO(b'1234')):
                with self.assertRaisesRegex(DevError, 'download-bound'):
                    gate.source_archive(path)
            self.assertFalse(path.exists())
            raw = b'exact authenticated public compiler source'
            with patch.object(gate.clock.std.clock, 'SOURCE_ARCHIVE_SHA256', hashlib.sha256(raw).hexdigest()):
                with patch.object(gate.urllib.request, 'urlopen', return_value=io.BytesIO(raw)):
                    gate.source_archive(path)
                with patch.object(gate.urllib.request, 'urlopen', return_value=io.BytesIO(raw)):
                    with self.assertRaises(FileExistsError):
                        gate.source_archive(path)
            self.assertEqual(path.read_bytes(), raw)

    def test_unsupported_clock_kind_rejects_before_compiler_source_or_output_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(DevError, 'clock-kind'):
                gate.clock.run(root / 'absent', root / 'output', root / 'rust-bin',
                               root / 'wasm-tools', clock_kind='ambient')
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
