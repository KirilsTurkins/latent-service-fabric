"""Validator reruns remove only recognized bounded generated echo fixtures."""
from pathlib import Path
import json
import os
import tempfile
import unittest

from tools.build_snapshot import SnapshotError, digest
from tools.reset_validation_echo import reset_validation_echo


def fixture(root: Path, *, package: bool) -> Path:
    directory = root / "capsules" / ("echo-provenance" if package else "echo")
    names = ["echo-capsule.wasm", "capsule.json"]
    if package:
        names += ["observation.json", "package-source.json", "contracts.json", "wit-lock.json",
                  "wit/context.wit", "wit/echo.wit", "wit/log.wit"]
    else:
        # Older maintained legacy fixtures legitimately lack CLI metadata files.
        names += ["build.json", "interface.json", "sha256.txt", "interface/component.wit",
                  "interface/deps/context.wit", "interface/deps/echo.wit", "interface/deps/log.wit"]
    for name in names:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tiny generated fixture")
    component = (directory / "echo-capsule.wasm").read_bytes()
    (directory / "capsule.json").write_text(json.dumps({"component": {"digest": digest(component)}}))
    if package:
        (directory / "observation.json").write_text(json.dumps({"formatVersion": 1,
            "buildType": "https://latent.dev/build/echo-capsule/v1",
            "componentDigest": digest(component), "componentSize": len(component)}))
        (directory / "package-source.json").write_text(json.dumps({"formatVersion": 1,
            "kind": "capsule", "name": "echo-provenance", "entrypoint": "echo-capsule.wasm"}))
    else:
        (directory / "build.json").write_text(json.dumps({"schemaVersion": 1,
            "artifact": "echo-capsule.wasm", "cargoPackage": "latent-toolchain-smoke",
            "cargoTarget": "echo-capsule", "contentDigest": digest(component), "sizeBytes": len(component)}))
    return directory


class ResetValidationEchoTests(unittest.TestCase):
    def test_absent_output_is_a_noop_and_other_capsules_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(reset_validation_echo(root / "absent"), 0)
            other = root / "capsules/other"
            other.mkdir(parents=True)
            (other / "keep").write_bytes(b"user output")
            fixture(root, package=False)
            fixture(root, package=True)
            self.assertEqual(reset_validation_echo(root), 2)
            self.assertEqual((other / "keep").read_bytes(), b"user output")
            self.assertEqual(reset_validation_echo(root), 0)

    def test_unknown_file_or_missing_required_file_preserves_both_owners(self):
        for unknown in (True, False):
            with self.subTest(unknown=unknown), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                legacy = fixture(root, package=False)
                package = fixture(root, package=True)
                if unknown:
                    (package / "user-notes.txt").write_bytes(b"keep")
                else:
                    (package / "wit/echo.wit").unlink()
                with self.assertRaises(SnapshotError):
                    reset_validation_echo(root)
                self.assertTrue(legacy.exists())
                self.assertTrue(package.exists())

    def test_changed_component_or_foreign_or_duplicate_marker_is_preserved(self):
        for change in ("component", "foreign", "duplicate"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                legacy = fixture(root, package=False)
                if change == "component":
                    (legacy / "echo-capsule.wasm").write_bytes(b"different")
                elif change == "foreign":
                    (legacy / "build.json").write_text('{"schemaVersion":1,"artifact":"other.wasm"}')
                else:
                    marker = legacy / "build.json"
                    marker.write_text(marker.read_text().replace('{', '{"schemaVersion":1,', 1))
                with self.assertRaises(SnapshotError):
                    reset_validation_echo(root)
                self.assertTrue(legacy.exists())

    def test_linked_output_cannot_delete_another_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            (outside / "keep").write_bytes(b"keep")
            target = root / "target"
            (target / "capsules").mkdir(parents=True)
            try:
                os.symlink(outside, target / "capsules/echo", target_is_directory=True)
            except OSError:
                self.skipTest("creating filesystem links requires host privileges")
            with self.assertRaises(SnapshotError):
                reset_validation_echo(target)
            self.assertEqual((outside / "keep").read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
