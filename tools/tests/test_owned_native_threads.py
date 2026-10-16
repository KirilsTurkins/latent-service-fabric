"""Keep compiler inventories and failed native runs from becoming qualification."""
import json
from pathlib import Path
import tempfile
import unittest
from tools import qualify_owned_native_threads as gate
from tools.dev_workflow.common import DevError


class OwnedNativeChildGate(unittest.TestCase):
    def test_native_inventory_requires_one_successful_exact_test_owned_by_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory).resolve()
            binary = target / 'test'; binary.write_bytes(b'controlled source-only test file')
            row = {'reason': 'compiler-artifact', 'target': {'name': 'local_service', 'kind': ['test']},
                   'manifest_path': str(gate.ROOT / 'crates/latent-wasmtime/Cargo.toml'),
                   'profile': {'test': True}, 'executable': str(binary)}
            terminal = {'reason': 'build-finished', 'success': True}
            def encode(rows):
                return b'\n'.join(json.dumps(item).encode() for item in rows)
            self.assertEqual(gate.executable(encode([row, terminal]), target), binary)
            for rows in [[row], [row, row, terminal], [row, {'reason': 'build-finished', 'success': False}],
                         [row, terminal, row], [dict(row, manifest_path='foreign'), terminal]]:
                with self.subTest(rows=rows), self.assertRaises(DevError):
                    gate.executable(encode(rows), target)

    def test_existing_output_never_runs_tools_or_signs_components(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(DevError, 'output-not-fresh'):
                gate.prepare(Path(directory), Path('absent'), Path('absent'))

    def test_actual_mechanism_gate_retains_finite_limits_and_no_standard_runtime_claim(self):
        source = (gate.ROOT / 'crates/latent-wasmtime/tests/local_service/runtime/native_threads.rs').read_text()
        self.assertIn('tasks: 3', source)
        self.assertIn('native_owners: 2', source)
        self.assertIn('resource_snapshot().stores_created, 0', source)
        self.assertIn('host_call_count', source)
        self.assertIn('denied.idle().await', source)
        self.assertIn('invalid.idle().await', source)
        self.assertIn('copied_task_token_cannot_start_another_child',
            (gate.ROOT / 'crates/latent-wasmtime/src/native_stacks/tests.rs').read_text())


if __name__ == '__main__':
    unittest.main()
