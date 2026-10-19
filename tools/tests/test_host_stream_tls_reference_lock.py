"""A current native parser probe uses one fixed maintained dependency closure."""
from pathlib import Path
import hashlib
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import qualify_host_stream_tls_parser as reference


class CurrentParserReferenceLock(unittest.TestCase):
    def test_real_lock_is_fixed_and_all_registry_inputs_match_the_workspace(self):
        raw = reference.current_reference_lock()
        packages = tomllib.loads(raw.decode("utf-8"))["package"]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), reference.CURRENT_LOCK_SHA256)
        self.assertEqual(len(packages), 26)
        self.assertEqual(sum("source" in row for row in packages), 24)
        self.assertEqual([row["version"] for row in packages if row["name"] == "zeroize"], ["1.9.1"])
        self.assertEqual(reference.OLD_CASE, "tls13-five-thousand-tiny-certificates-old")
        self.assertEqual(len(reference.CASES), 8)

    def test_changed_lock_unknown_local_owner_and_foreign_dependency_are_refused(self):
        raw = reference.current_reference_lock()
        workspace = reference.read_file(reference.captured.ROOT / "Cargo.lock", 4 * 1024 * 1024)
        for kind in ("identity", "local", "checksum"):
            with self.subTest(kind=kind):
                changed = raw + b"\n" if kind == "identity" else raw
                if kind == "local":
                    changed = raw.replace(b'name = "tls-parser-reference"', b'name = "unreviewed-programme"')
                if kind == "checksum":
                    original = next(row["checksum"] for row in tomllib.loads(raw.decode())["package"] if "source" in row)
                    changed = raw.replace(original.encode(), b"0" * 64, 1)
                self.assertNotEqual(changed, raw)
                selected = reference.CURRENT_LOCK_SHA256 if kind == "identity" else hashlib.sha256(changed).hexdigest()
                with patch.object(reference, "CURRENT_LOCK_SHA256", selected), \
                        patch.object(reference, "read_file", side_effect=[changed, workspace]), \
                        self.assertRaises(ValueError):
                    reference.current_reference_lock()

    def test_current_manifest_is_isolated_and_legacy_template_is_unchanged(self):
        for directory in ("original-rustls", "bounded-rustls"):
            legacy = reference.project_manifest(directory, current=False)
            expected = ('[package]\nname="tls-parser-reference"\nversion="0.0.0"\nedition="2024"\n'
                        f'[dependencies]\nrustls={{path="../{directory}",default-features=false,features=["ring","std","tls12"]}}\n')
            self.assertEqual(legacy, expected.encode())
            current = reference.project_manifest(directory, current=True)
            self.assertEqual(current, legacy + b'[workspace]\nresolver="3"\n')
            model = tomllib.loads(current.decode())
            self.assertEqual(model["dependencies"]["rustls"]["features"], ["ring", "std", "tls12"])
            self.assertFalse(model["dependencies"]["rustls"]["default-features"])
        with self.assertRaisesRegex(ValueError, "reference-project"):
            reference.project_manifest("../../foreign", current=True)

    def test_legacy_fetch_and_bad_current_lock_fail_before_any_process_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(reference.subprocess, "run", side_effect=AssertionError("no native process")):
                with self.assertRaisesRegex(ValueError, "fetch-current-only"):
                    reference.qualify(root / "input", root / "legacy", root / "cargo", root / "rustc",
                                      fetch_current_dependencies=True)
                with patch.object(reference, "current_reference_lock", side_effect=ValueError("lock-refused")), \
                        self.assertRaisesRegex(ValueError, "lock-refused"):
                    reference.qualify(root / "input", root / "current", root / "cargo", root / "rustc",
                                      parser_version="0.23.46", fetch_current_dependencies=True)
            self.assertFalse((root / "legacy").exists())
            self.assertFalse((root / "current").exists())


if __name__ == "__main__":
    unittest.main()
