"""Tests for the probe, not evidence of Java execution in LSF."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SDK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('java_feasibility', SDK / 'tools/feasibility.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class EvidenceTests(unittest.TestCase):
    def test_identity_is_from_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input'
            path.write_bytes(b'abc')
            self.assertEqual(probe.identity(path), {
                'sha256': 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
                'size': 3})
            path.write_bytes(b'abcd')
            self.assertEqual(probe.identity(path)['size'], 4)

    def test_source_directories_are_protected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'repo'
            root.mkdir()
            for path in (root, root / 'sdk', root / 'docs', root / 'tools'):
                with self.subTest(path=path), self.assertRaises(probe.ProbeFailure):
                    probe.new_output(path, root)
            self.assertEqual(probe.new_output(root / 'target/first', root), root / 'target/first')

    def test_previous_attempt_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'repo'
            path = probe.new_output(Path(temp) / 'attempt', root)
            receipt = path / 'report.json'
            receipt.write_text('retained failure')
            with self.assertRaises(FileExistsError):
                probe.new_output(path, root)
            self.assertEqual(receipt.read_text(), 'retained failure')

    def test_symlink_back_into_source_is_not_an_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'repo'
            root.mkdir()
            link = Path(temp) / 'outside'
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(probe.ProbeFailure):
                probe.new_output(link / 'sdk/output', root)

    def test_exact_tool_versions(self):
        cases = [('java-version', 'OpenJDK Runtime Environment (build 25.0.4.1+1-LTS)', '25.0.4.1+1'),
                 ('gradle-version', 'Gradle 9.1.0\n', '9.1.0'),
                 ('zig-version', '0.16.0\n', '0.16.0'),
                 ('wit-bindgen-version', 'wit-bindgen-cli 0.62.0\n', '0.62.0'),
                 ('wasm-tools-version', 'wasm-tools 1.254.0\n', '1.254.0')]
        for stage, log, expected in cases:
            with self.subTest(stage=stage):
                probe.verify_version(stage, log, expected)
                with self.assertRaises(probe.ProbeFailure):
                    probe.verify_version(stage, log.replace(expected, expected + '9'), expected)
                with self.assertRaises(probe.ProbeFailure):
                    probe.verify_version(stage, '', expected)

    def test_actual_temurin_multiline_version(self):
        probe.verify_version('java-version',
            'OpenJDK Runtime Environment Temurin-25.0.4.1+1 (build 25.0.4.1+1-LTS)\n'
            'OpenJDK 64-Bit Server VM Temurin-25.0.4.1+1 (build 25.0.4.1+1-LTS, mixed mode, sharing)\n',
            '25.0.4.1+1')

    def test_infrastructure_failure_is_not_compiler_incompatibility(self):
        self.assertEqual(probe.failure_kind('java-version', {'exit': {'returncode': 1}}), 'toolchain-preflight')
        self.assertEqual(probe.failure_kind('java-to-c', {'exit': {'spawnError': 'FileNotFoundError'}}), 'toolchain-preflight')
        self.assertEqual(probe.failure_kind('c-to-wasm', {'error': 'command-deadline'}), 'probe-infrastructure')
        self.assertEqual(probe.failure_kind('java-source-test', {'exit': {'returncode': 1}}), 'source-self-test')
        self.assertEqual(probe.failure_kind('c-to-wasm', {'exit': {'returncode': 1}}), 'candidate-stage-failure')


class CaptureTests(unittest.TestCase):
    def invoke(self, path: Path, *command: str):
        return subprocess.run([sys.executable, str(SDK / 'tools/capture.py'), str(path), *command],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)

    def test_success_preserves_streams(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'status.json'
            result = self.invoke(path, sys.executable, '-c', 'import sys; print("output"); print("diagnostic", file=sys.stderr)')
            self.assertEqual(result.returncode, 0)
            self.assertIn(b'output', result.stdout)
            self.assertIn(b'diagnostic', result.stderr)
            self.assertEqual(json.loads(path.read_text()), {'returncode': 0})

    def test_failed_compiler_retains_original_nonzero_status_and_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'status.json'
            result = self.invoke(path, sys.executable, '-c', 'import sys; print("compiler error", file=sys.stderr); sys.exit(7)')
            self.assertEqual(result.returncode, 0)  # outer owner can return bounded logs
            self.assertIn(b'compiler error', result.stderr)
            self.assertEqual(json.loads(path.read_text()), {'returncode': 7})

    def test_stdout_cannot_spoof_a_success_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'status.json'
            self.invoke(path, sys.executable, '-c', 'import sys; print(\'{"returncode":0}\'); sys.exit(2)')
            self.assertEqual(json.loads(path.read_text()), {'returncode': 2})

    def test_spawn_error_is_not_a_compiler_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'status.json'
            result = self.invoke(path, str(Path(temp) / 'nonexistent-compiler'))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(path.read_text()), {'spawnError': 'FileNotFoundError'})

    def test_existing_receipt_prevents_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'status.json'
            path.write_text('previous')
            marker = Path(temp) / 'effect'
            result = self.invoke(path, sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).touch()')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())
            self.assertEqual(path.read_text(), 'previous')


if __name__ == '__main__':
    unittest.main()
