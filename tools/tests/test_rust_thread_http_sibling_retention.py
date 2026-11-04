"""Bound and classify the public combined-diagnostic artifact."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import rust_thread_http_sibling_retention as retention


class CombinedRetention(unittest.TestCase):
    def test_only_selected_outputs_are_retained_without_the_cargo_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in {
                'rust-http-thread-owned/report.json': b'{}',
                'rust-http-thread-http/adapter.wasm': b'wasm',
                'rust-http-thread-contracts/target/private-cache': b'not-an-artifact',
                'rust-http-thread-combined/combined-component-graph.json': b'{}',
                'rust-http-thread-combined/logs/01-compile.stderr.txt': b'log',
            }.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            output = root / 'public'
            result = retention.collect(root, output)
            self.assertEqual(result['status'], 'retained')
            paths = {row['path'] for row in result['files']}
            self.assertEqual(len(paths), 4)
            self.assertNotIn('rust-http-thread-contracts/target/private-cache', paths)
            self.assertFalse(result['hostOrGuestQualified'])

    def test_overflow_refuses_and_records_failure_before_copying(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'rust-http-thread-owned'; source.mkdir()
            (source / 'one.json').write_bytes(b'1'); (source / 'two.json').write_bytes(b'2')
            output = root / 'public'
            with patch.object(retention, 'MAX_FILES', 1):
                with self.assertRaises(ValueError): retention.collect(root, output)
            self.assertEqual(json.loads((output / 'retention-FAILED.json').read_text())['status'], 'refused')
            self.assertEqual({p.name for p in output.iterdir()}, {'retention-FAILED.json'})


if __name__ == '__main__':
    unittest.main()
