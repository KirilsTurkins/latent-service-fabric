"""Finite emitted-tool/source refusal controls; no Rust compiler is invoked."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import compile_rust_owned_thread_inputs as inputs
from tools.dev_workflow.common import DevError


class OwnedThreadInputs(unittest.TestCase):
    def graph(self, target):
        tool = target / 'debug/rust-context'
        tool.parent.mkdir(parents=True)
        tool.write_bytes(b'emission-parser-fixture-only')
        return [{'reason': 'compiler-artifact',
                 'manifest_path': str(inputs.ROOT / inputs.CRATE / 'Cargo.toml'),
                 'target': {'name': 'rust-context', 'kind': ['bin']},
                 'profile': {'test': False}, 'executable': str(tool)},
                {'reason': 'build-finished', 'success': True}]

    def encoded(self, rows):
        return b'\n'.join(json.dumps(row).encode() for row in rows)

    def test_only_exact_successful_emission_can_select_a_tool_despite_stale_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory); rows = self.graph(target)
            stale = target / 'debug/rust-context-stale'
            stale.write_bytes(b'earlier-failed-build')
            self.assertEqual(inputs.emitted_tool(self.encoded(rows), target), target / 'debug/rust-context')
            for changed in (rows[:-1], [*rows, rows[0]],
                            [*rows[:-1], {'reason': 'build-finished', 'success': False}],
                            [rows[0], rows[0], rows[1]]):
                with self.subTest(changed=changed), self.assertRaises(DevError):
                    inputs.emitted_tool(self.encoded(changed), target)
            for field, value in (('manifest_path', str(target / 'foreign/Cargo.toml')),
                                 ('profile', {'test': True}),
                                 ('target', {'name': 'rust-context', 'kind': ['test']}),
                                 ('executable', str(Path(__file__).resolve()))):
                changed = [{**rows[0], field: value}, rows[1]]
                with self.subTest(field=field), self.assertRaises(DevError):
                    inputs.emitted_tool(self.encoded(changed), target)

    def test_invalid_or_dirty_head_is_refused_before_any_source_or_compiler_access(self):
        with patch.object(inputs, 'git', side_effect=AssertionError('Git must not be read')):
            for value in ('', 'foreign', '0' * 39, 'A' * 40):
                with self.subTest(value=value), self.assertRaisesRegex(DevError, 'expected-head'):
                    inputs.sources(value)
        head = 'a' * 40
        for responses in ([b'b' * 40 + b'\n'],
                          [head.encode() + b'\n', b' M Cargo.toml\n']):
            with patch.object(inputs, 'git', side_effect=responses), self.assertRaisesRegex(DevError, 'clean-exact-head'):
                inputs.sources(head)


if __name__ == '__main__': unittest.main()
