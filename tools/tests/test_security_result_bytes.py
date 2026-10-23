"""The host-only bytes fork retains complete source and upstream advisory identity."""
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import result_owner_bytes as bounded
from tools import security_result_bytes as selected
from tools import security_advisories as advisories
from tools.security_common import SecurityError, tracked_paths
from tools.security_findings import finding
from tools.security_inventory import Package, inventory

ROOT = Path(__file__).resolve().parents[2]


class ResultBytesAdvisoryIdentity(unittest.TestCase):
    def test_complete_source_keeps_upstream_coordinate_and_unknown_or_partial_inventory_refuses(self):
        paths = tracked_paths(ROOT)
        checked = selected.origin(ROOT, paths)
        self.assertEqual((checked['name'], checked['version'], checked['checksum']),
                         ('bytes', '1.12.1', bounded.ARCHIVE_SHA256))
        self.assertEqual(len(checked['files']), 41)
        packages, records = inventory(ROOT)
        self.assertIn(Package('crates.io', 'bytes', '1.12.1', selected.MANIFEST), packages)
        self.assertEqual(next(row for row in records if row['path'] == selected.MANIFEST)['coverage'],
                         'OSV-and-RustSec-authenticated-origin')
        for changed in ([path for path in paths if path != selected.MANIFEST],
                        [*paths, bounded.PROVIDER + '/extra/Cargo.toml']):
            with self.subTest(changed=len(changed)), self.assertRaisesRegex(
                    SecurityError, 'partial-or-unreviewed-result-bytes-source'):
                selected.origin(ROOT, changed)
        with self.assertRaisesRegex(SecurityError, 'unreviewed-result-bytes-inventory'):
            selected.inventory_record(ROOT, {'path': selected.MANIFEST, 'kind': 'cargo'}, paths)

    def test_real_source_mutation_extra_files_empty_directories_and_missing_selected_fork_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / bounded.PROVIDER, root / bounded.PROVIDER)
            for name in ('Cargo.toml', 'Cargo.lock'):
                shutil.copyfile(ROOT / name, root / name)
            bounded.verify(root)
            for name in ('UPSTREAM.json', 'Cargo.toml', 'src/bytes.rs', 'tests/test_owner_retirement.rs'):
                path = root / bounded.PROVIDER / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                with self.subTest(name=name), self.assertRaises(SecurityError):
                    bounded.verify(root)
                path.write_bytes(original)
            for name in ('src/unreviewed.rs', '.cargo/config.toml'):
                path = root / bounded.PROVIDER / name
                path.parent.mkdir(exist_ok=True)
                path.write_text('unreviewed')
                with self.subTest(extra=name), self.assertRaisesRegex(SecurityError, 'membership'):
                    bounded.verify(root)
                path.unlink()
                if name.startswith('.cargo/'):
                    path.parent.rmdir()
            extra = root / bounded.PROVIDER / 'empty-unreviewed'
            extra.mkdir()
            with self.assertRaisesRegex(SecurityError, 'membership'):
                bounded.verify(root)
            extra.rmdir()
            (root / bounded.PROVIDER / 'src/bytes.rs').unlink()
            with self.assertRaisesRegex(SecurityError, 'membership'):
                bounded.verify(root)
            shutil.copyfile(ROOT / bounded.PROVIDER / 'src/bytes.rs', root / bounded.PROVIDER / 'src/bytes.rs')
            provider = root / bounded.PROVIDER
            self.assertTrue(provider.resolve().is_relative_to(root.resolve()))
            provider.rename(root / 'kept-original-bytes')
            from tools.security_inventory import cargo_inventory
            with self.assertRaisesRegex(SecurityError, 'unreviewed-result-bytes-source'):
                cargo_inventory(root, {'path': 'Cargo.toml', 'lock': 'Cargo.lock'})

    def test_future_upstream_rustsec_advisory_is_not_hidden_by_local_root_lock(self):
        paths = [path for path in tracked_paths(ROOT)
                 if path == 'Cargo.lock' or path.startswith(bounded.PROVIDER + '/')]
        observed = []
        expected = finding('rustsec', 'RUSTSEC-2099-0002', selected.MANIFEST, 'bytes@1.12.1')

        def audit(payload, path, *_):
            observed.append(path)
            if path == selected.MANIFEST:
                self.assertEqual(tomllib.loads(payload.decode())['package'], [bounded.REGISTRY_PACKAGE])
                return [expected], {'packages': 1}
            self.assertEqual(payload, (ROOT / path).read_bytes())
            return [], {'packages': 1}

        with patch.object(advisories, 'tracked_paths', return_value=paths), \
                patch.object(advisories, 'verify_tool', return_value=ROOT / 'not-executed'), \
                patch.object(advisories, 'fetch_rustsec', return_value=(ROOT, {'commit': 'a' * 40})), \
                patch.object(advisories, 'audit_lock', side_effect=audit):
            findings, receipt = advisories.rustsec(ROOT, ROOT, ROOT)
        self.assertEqual(observed, ['Cargo.lock', selected.MANIFEST])
        self.assertEqual(findings, [expected])
        self.assertTrue(receipt['locks'][-1]['notBuildLock'])


if __name__ == '__main__':
    unittest.main()
