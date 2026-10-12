"""Captured patch transaction/provenance checks; genuine parser is separate."""
from pathlib import Path
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import host_stream_tls_patch as captured


class CapturedTlsPatch(unittest.TestCase):
    def prepared(self, root, *, duplicate=False, link=False):
        archive = root / "public.crate"
        with tarfile.open(archive, "w:gz") as source:
            for name, raw in (("Cargo.toml", b"[package]\n"), ("src/parser.rs", b"original parser\n")):
                item = tarfile.TarInfo("rustls-0.23.45/" + name); item.size = len(raw)
                source.addfile(item, io.BytesIO(raw))
            if duplicate:
                item = tarfile.TarInfo("rustls-0.23.45/src/parser.rs"); item.size = 1
                source.addfile(item, io.BytesIO(b"x"))
            if link:
                item = tarfile.TarInfo("rustls-0.23.45/src/link.rs"); item.type = tarfile.SYMTYPE; item.linkname = "../../escape"
                source.addfile(item)
        patch_root = root / "patch"; (patch_root / "modified/src").mkdir(parents=True)
        original, modified = b"original parser\n", b"bounded parser\n"
        (patch_root / "modified/src/parser.rs").write_bytes(modified)
        manifest = {"upstream": {"archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
            "files": [{"path": "src/parser.rs", "beforeSha256": hashlib.sha256(original).hexdigest(),
                       "afterSha256": hashlib.sha256(modified).hexdigest()}]}
        (patch_root / "PATCH.json").write_text(json.dumps(manifest), encoding="utf-8")
        return archive, patch_root

    def test_only_exact_reviewed_preimage_changes_and_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); archive, selected = self.prepared(root)
            with patch.object(captured, "PATCH_ROOT", selected):
                result = captured.apply(archive, root / "owned")
                self.assertEqual(result["allOriginalFiles"]["Cargo.toml"], result["allResultFiles"]["Cargo.toml"])
                self.assertNotEqual(result["allOriginalFiles"]["src/parser.rs"], result["allResultFiles"]["src/parser.rs"])
                self.assertFalse(result["sharedRegistryModified"])
                with self.assertRaises(ValueError): captured.apply(archive, root / "owned")
                self.assertEqual((root / "owned/src/parser.rs").read_bytes(), b"bounded parser\n")

    def test_bad_public_archive_hash_fails_before_destination_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); archive, selected = self.prepared(root)
            archive.write_bytes(archive.read_bytes() + b"different")
            with patch.object(captured, "PATCH_ROOT", selected), self.assertRaisesRegex(ValueError, "archive-mismatch"):
                captured.apply(archive, root / "owned")
            self.assertFalse((root / "owned").exists())

    def test_unreviewed_modified_bytes_or_preimage_fail_in_captured_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); archive, selected = self.prepared(root)
            (selected / "modified/src/parser.rs").write_bytes(b"other")
            with patch.object(captured, "PATCH_ROOT", selected), self.assertRaisesRegex(ValueError, "postimage"):
                captured.apply(archive, root / "owned")

    def test_duplicate_or_link_archive_entries_are_rejected(self):
        for name in ("duplicate", "link"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); archive, selected = self.prepared(root, **{name: True})
                with patch.object(captured, "PATCH_ROOT", selected), self.assertRaises(ValueError):
                    captured.apply(archive, root / "owned")


if __name__ == "__main__":
    unittest.main()
