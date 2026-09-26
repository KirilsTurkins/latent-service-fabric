from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.security_common import ROOT, SecurityError, digest
from tools.security_native_aot import packages


class NativeAotInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        policy = json.loads((ROOT / '.github/security/inventory.json').read_text())
        self.entry = copy.deepcopy(next(x for x in policy['manifests'] if x['kind'] == 'nuget-aot-locked'))
        for name in [self.entry['path'], self.entry['lock'],
                     *(item['path'] for item in self.entry['configuration'])]:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())

    def rewrite_lock(self, change):
        path = self.root / self.entry['lock']
        value = json.loads(path.read_text())
        change(value)
        path.write_bytes(json.dumps(value).encode())
        self.entry['lock_sha256'] = digest(path.read_bytes())

    def test_every_resolved_compiler_runtime_and_linker_package_is_scanned(self):
        result = packages(self.root, self.entry)
        lock = json.loads((self.root / self.entry['lock']).read_text())
        expected = {('NuGet', name, item['resolved']) for group in lock['dependencies'].values()
                    for name, item in group.items()}
        self.assertEqual(set(result), expected)
        self.assertEqual(len(result), 6)

    def test_project_lock_and_both_configuration_changes_fail_closed(self):
        for name in [self.entry['path'], self.entry['lock'],
                     *(item['path'] for item in self.entry['configuration'])]:
            with self.subTest(path=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                with self.assertRaisesRegex(SecurityError, 'unreviewed-native-aot-input'):
                    packages(self.root, self.entry)
                path.write_bytes(original)

    def test_unknown_rid_cannot_hide_in_a_reviewed_lock(self):
        self.rewrite_lock(lambda doc: doc['dependencies'].update({'net10.0/linux-x64': {}}))
        with self.assertRaisesRegex(SecurityError, 'unreviewed-native-aot-target'):
            packages(self.root, self.entry)

    def test_unresolved_versions_and_missing_checksums_fail(self):
        for field, value in [('resolved', '*'), ('contentHash', 'not-a-hash')]:
            with self.subTest(field=field):
                self.rewrite_lock(lambda doc: next(iter(doc['dependencies']['net10.0'].values())).update({field: value}))
                with self.assertRaises(SecurityError):
                    packages(self.root, self.entry)

    def test_missing_transitive_package_is_not_an_empty_success(self):
        self.rewrite_lock(lambda doc: doc['dependencies']['net10.0/wasi-wasm'].pop(
            'runtime.wasi-wasm.Microsoft.DotNet.ILCompiler.LLVM'))
        with self.assertRaisesRegex(SecurityError, 'incomplete-native-aot-graph'):
            packages(self.root, self.entry)


if __name__ == '__main__':
    unittest.main()
