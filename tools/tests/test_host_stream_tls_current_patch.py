"""Current parser capture identity is distinct from TLS/accounting qualification."""
from copy import deepcopy
from pathlib import Path
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import host_stream_tls_patch as captured
from tools import qualify_host_stream_tls_parser as reference


class CurrentTlsCapture(unittest.TestCase):
    def prepared(self, root):
        files = {name: ("original " + name + "\n").encode() for name in sorted(captured.CURRENT_FILES)}
        files["Cargo.toml"] = b'[package]\nname="rustls"\nversion="0.23.46"\n'
        archive = root / "public.crate"
        with tarfile.open(archive, "w:gz") as output:
            for name, raw in files.items():
                entry = tarfile.TarInfo("rustls-0.23.46/" + name)
                entry.size = len(raw)
                output.addfile(entry, io.BytesIO(raw))
        selected = root / "capture"
        rows = []
        for name in sorted(captured.CURRENT_FILES):
            raw = files[name]; modified = raw + b"bounded\n"
            target = selected / "modified" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(modified)
            rows.append({"path": name, "beforeSha256": hashlib.sha256(raw).hexdigest(),
                         "afterSha256": hashlib.sha256(modified).hexdigest()})
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        selected_patch = b"exact owned patch document\n"
        (selected / "rustls-0.23.46-lsf-bounds.patch").write_bytes(selected_patch)
        manifest = {"upstream": {"crate": "rustls", "version": "0.23.46",
                                "archiveSha256": checksum, "license": "Apache-2.0 OR ISC OR MIT"},
                    "patchSha256": hashlib.sha256(selected_patch).hexdigest(), "files": rows,
                    "bounds": captured.CURRENT_BOUNDS, "accountingQualified": False,
                    "nativeReferenceExecuted": False, "doesNotModifySharedRegistry": True}
        (selected / "PATCH.json").write_bytes(json.dumps(manifest).encode())
        (root / "crates/latent-streams").mkdir(parents=True)
        (root / "crates/latent-streams/Cargo.toml").write_bytes(b'[dependencies]\nrustls={version="=0.23.46"}\n')
        (root / "Cargo.lock").write_bytes((
            '[[package]]\nname="rustls"\nversion="0.23.46"\n'
            'source="registry+https://github.com/rust-lang/crates.io-index"\n'
            f'checksum="{checksum}"\n').encode())
        return archive, selected, manifest

    def test_committed_capture_binds_current_lock_and_preserves_original_amplification_vector(self):
        manifest = json.loads((captured.CURRENT_PATCH_ROOT / "PATCH.json").read_text(encoding="utf-8"))
        historical = json.loads((captured.PATCH_ROOT / "PATCH.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["upstream"], captured.current_upstream())
        self.assertEqual(manifest["bounds"], historical["bounds"])
        self.assertFalse(manifest["accountingQualified"])
        self.assertFalse(manifest["nativeReferenceExecuted"])
        self.assertEqual({row["path"] for row in manifest["files"]}, captured.CURRENT_FILES)
        for row in manifest["files"]:
            raw = (captured.CURRENT_PATCH_ROOT / "modified" / row["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["afterSha256"])
            self.assertEqual(len(raw), row["afterBytes"])
        self.assertEqual((captured.CURRENT_PATCH_ROOT / "allocation-reference.rs").read_bytes(),
                         (captured.PATCH_ROOT / "allocation-reference.rs").read_bytes())
        self.assertEqual(reference.OLD_CASE, "tls13-five-thousand-tiny-certificates-old")
        self.assertEqual(reference.CASES["tls13-five-thousand-tiny-certificates"], False)
        self.assertEqual(reference.PARSER_CEILING, 65536)

    def test_current_archive_changes_only_selected_preimages_without_enabling_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); archive, selected, _ = self.prepared(root)
            with patch.object(captured, "ROOT", root), patch.object(captured, "CURRENT_PATCH_ROOT", selected):
                result = captured.apply_current(archive, root / "owned")
                self.assertEqual(result["allOriginalFiles"]["Cargo.toml"], result["allResultFiles"]["Cargo.toml"])
                changed = {p for p in result["allOriginalFiles"]
                           if result["allOriginalFiles"][p] != result["allResultFiles"][p]}
                self.assertEqual(changed, captured.CURRENT_FILES)
                self.assertFalse(result["accountingQualified"])
                self.assertFalse(result["sharedRegistryModified"])
                with self.assertRaises(ValueError):
                    captured.apply_current(archive, root / "owned")
                with self.assertRaisesRegex(ValueError, "archive-mismatch"):
                    captured.apply(archive, root / "legacy-rejects-current")
                self.assertFalse((root / "legacy-rejects-current").exists())

    def test_unknown_version_widened_bounds_or_unqualified_claim_fails_before_output(self):
        for kind in ["version", "bound", "qualified", "files", "lock"]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); archive, selected, manifest = self.prepared(root)
                changed = deepcopy(manifest)
                if kind == "version": changed["upstream"]["version"] = "0.23.47"
                if kind == "bound": changed["bounds"]["certificateEntries"] = 9
                if kind == "qualified": changed["accountingQualified"] = True
                if kind == "files": changed["files"].pop()
                if kind == "lock": (root / "Cargo.lock").write_bytes(b"version=4\n")
                (selected / "PATCH.json").write_bytes(json.dumps(changed).encode())
                with patch.object(captured, "ROOT", root), patch.object(captured, "CURRENT_PATCH_ROOT", selected), self.assertRaises(ValueError):
                    captured.apply_current(archive, root / "rejected")
                self.assertFalse((root / "rejected").exists())

    def test_forged_preimage_postimage_or_patch_document_is_rejected(self):
        for kind in ["preimage", "postimage", "patch", "archive"]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); archive, selected, manifest = self.prepared(root)
                if kind == "preimage":
                    manifest["files"][0]["beforeSha256"] = "0" * 64
                    (selected / "PATCH.json").write_bytes(json.dumps(manifest).encode())
                elif kind == "postimage":
                    (selected / "modified" / manifest["files"][0]["path"]).write_bytes(b"forged\n")
                elif kind == "patch":
                    (selected / "rustls-0.23.46-lsf-bounds.patch").write_bytes(b"different patch\n")
                else:
                    archive.write_bytes(archive.read_bytes() + b"changed")
                with patch.object(captured, "ROOT", root), patch.object(captured, "CURRENT_PATCH_ROOT", selected), self.assertRaises(ValueError):
                    captured.apply_current(archive, root / "rejected")

    def test_reference_profiles_are_explicit_and_legacy_default_remains_available(self):
        self.assertEqual(reference.profile("0.23.45"), (captured.PATCH_ROOT, captured.apply))
        self.assertEqual(reference.profile("0.23.46"), (captured.CURRENT_PATCH_ROOT, captured.apply_current))
        for unknown in ["0.23.47", "latest", "0.23.46/../0.23.45"]:
            with self.subTest(unknown=unknown), self.assertRaisesRegex(ValueError, "reference-profile"):
                reference.profile(unknown)


if __name__ == "__main__":
    unittest.main()
