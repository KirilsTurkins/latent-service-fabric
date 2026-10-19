"""Bounded source controls do not replace the signed 34-outcome replay."""
import json
from pathlib import Path
import tempfile
import unittest
from tools import replay_typescript_standard_entropy as replay
from tools.rust_capsule_project import digest, inventory


class EntropyReplay(unittest.TestCase):
    def test_fixed_selection_keeps_only_public_products_and_rejects_private_or_foreign_members(self):
        for name in (replay.NORMAL+'qualification.json', replay.NORMAL+'native-binaries/latentd',
                     replay.NORMAL+'builds/shipping/component.wasm', replay.ENTROPY+'build-greeting/package-inputs.json',
                     replay.NORMAL+'builds/http-status/wit/deps/http/package.wit'):
            self.assertTrue(replay.selected(name), name)
        for name in ('/absolute', '../escape', 'a/../escape', 'a\\escape', 'C:/escape',
                     replay.NORMAL+'native-binaries/unreviewed', replay.NORMAL+'logs/private.txt',
                     replay.ENTROPY+'project-greeting/vendor/private.json',
                     replay.NORMAL+'builds/greeting/component.wasm', replay.ENTROPY+'build-greeting/secret.key'):
            self.assertFalse(replay.selected(name), name)

    def test_actual_package_layers_require_exact_membership_and_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layers = {'package-source.json': json.dumps({'layers': [{'source': 'component.wasm'}]}).encode(),
                      'component.wasm': b'public-wasm-fixture'}
            for name, raw in layers.items(): (root/name).write_bytes(raw)
            (root/'package-inputs.json').write_bytes(inventory(layers))
            observed = replay.package_inputs(root)
            self.assertEqual(observed['sha256'], digest(inventory(layers)))
            (root/'component.wasm').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'exact-package-inputs'): replay.package_inputs(root)

    def test_package_paths_fail_closed_before_reading_an_external_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('../external', '/absolute', 'C:/external', 'nested\\file', 'a/./file'):
                (root/'package-source.json').write_text(json.dumps({'layers': [{'source': name}]}), encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'package-paths'): replay.package_inputs(root)

    def test_historical_qualification_is_pinned_before_native_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root/replay.NORMAL/'qualification.json'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"status":"passed"}')
            with self.assertRaisesRegex(RuntimeError, 'qualified-receipt-preimage'): replay.historical(root)


if __name__ == '__main__':
    unittest.main()
