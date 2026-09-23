"""Compiler inputs must agree with both Gradle verification and OSV inventory."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SDK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('java_dependencies', SDK / 'tools/dependencies.py')
deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deps)


class DependencyTests(unittest.TestCase):
    def fixture(self, root):
        cache = root / 'cache'
        jar = cache / 'org.example/lib/1.2.3/cache-key/lib-1.2.3.jar'
        jar.parent.mkdir(parents=True)
        jar.write_bytes(b'compiler jar')
        project = root / 'project'
        (project / 'gradle').mkdir(parents=True)
        metadata = project / 'gradle/verification-metadata.xml'
        metadata.write_text(f'''<verification-metadata xmlns="https://schema.gradle.org/dependency-verification">
<configuration><verify-metadata>true</verify-metadata><verify-signatures>false</verify-signatures></configuration>
<components><component group="org.example" name="lib" version="1.2.3">
<artifact name="lib-1.2.3.jar"><sha256 value="{deps.file_identity(jar)['sha256']}"/></artifact>
</component></components></verification-metadata>''')
        lock = deps.cache_inventory(cache)
        (project / 'dependencies.lock.json').write_text(json.dumps(lock))
        return cache, jar, project, metadata, lock

    def test_actual_bytes_are_checked_and_receipted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache, jar, project, metadata, lock = self.fixture(root)
            observed = deps.cache_inventory(cache)
            deps.verify_inventory(observed, lock, metadata)
            receipt = deps.retain(cache, project, root, False)
            self.assertEqual(receipt['status'], 'checksummed-gradle-metadata')
            self.assertEqual(receipt['downloadedJars'], 1)
            self.assertTrue((root / 'dependencies.observed.json').is_file())
            jar.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'cache-lock-drift'):
                deps.verify_inventory(deps.cache_inventory(cache), lock, metadata)

    def test_bootstrap_only_writes_candidates_and_never_replaces_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache, jar, project, metadata, lock = self.fixture(root)
            original = (project / 'dependencies.lock.json').read_bytes()
            receipt = deps.retain(cache, project, root, True)
            self.assertEqual(receipt['status'], 'unreviewed-bootstrap-candidate')
            self.assertEqual((project / 'dependencies.lock.json').read_bytes(), original)
            self.assertEqual(json.loads((root / 'dependencies.candidate.json').read_text()), lock)
            self.assertEqual((root / 'verification-metadata.candidate.xml').read_bytes(), metadata.read_bytes())

    def test_missing_duplicate_unknown_or_changed_inventory_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, jar, project, metadata, lock = self.fixture(Path(tmp))
            changes = [lambda d: d['artifacts'].clear(),
                       lambda d: d['artifacts'].append(d['artifacts'][0].copy()),
                       lambda d: d['artifacts'][0].update(sha256='0' * 64),
                       lambda d: d.update(maven='https://unreviewed.example/'),
                       lambda d: d['artifacts'][0].update(size=0)]
            for change in changes:
                other = copy.deepcopy(lock)
                change(other)
                with self.subTest(other=other), self.assertRaises(ValueError):
                    deps.verify_inventory(lock, other, metadata)

    def test_trusted_metadata_jar_cannot_be_omitted_from_advisory_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, jar, project, metadata, lock = self.fixture(Path(tmp))
            metadata.write_text(metadata.read_text().replace('</components>',
                '<component group="org.other" name="other" version="2.0.0"><artifact name="other-2.0.0.jar">'
                f'<sha256 value="{"f" * 64}"/></artifact></component></components>'))
            with self.assertRaisesRegex(ValueError, 'lock-metadata-drift'):
                deps.verify_inventory(lock, lock, metadata)

    def test_metadata_bypasses_and_alternative_checksums_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, jar, project, metadata, lock = self.fixture(Path(tmp))
            original = metadata.read_text()
            changes = [original.replace('true</verify-metadata>', 'false</verify-metadata>'),
                       original.replace('</configuration>', '<trusted-artifacts/></configuration>'),
                       original.replace('/></artifact>', f'><also-trust value="{"a" * 64}"/></sha256></artifact>'),
                       '<!DOCTYPE a [<!ENTITY x "b">]>' + original]
            for changed in changes:
                metadata.write_text(changed)
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    deps.verify_inventory(lock, lock, metadata)

    def test_symlink_empty_and_duplicate_coordinates_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'cache-empty'):
                deps.cache_inventory(root)
            cache, jar, project, metadata, lock = self.fixture(root)
            other = cache / 'org.example/lib/1.2.3/different-key/lib-1.2.3.jar'
            other.parent.mkdir(parents=True)
            other.write_bytes(b'different artifact')
            with self.assertRaisesRegex(ValueError, 'coordinate-conflict'):
                deps.cache_inventory(cache)
            other.unlink()
            other.symlink_to(jar)
            with self.assertRaisesRegex(ValueError, 'dependency-symlink'):
                deps.cache_inventory(cache)


if __name__ == '__main__':
    unittest.main()
