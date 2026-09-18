"""Resource fixture staging preserves Cargo outputs and the frozen byte limit."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import phase2_resource_binaries as binaries


class ResourceBinaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.build = self.root / "debug"
        self.build.mkdir()
        self.destination = self.root / "resource-binaries"
        for name in binaries.NAMES:
            path = self.build / name
            path.write_bytes(b"executable-with-debug-data")
            path.chmod(0o700)

    def copy(self, command, **kwargs):
        self.assertEqual(command[:2], ["objcopy", "--strip-debug"])
        self.assertEqual(kwargs["timeout"], 60)
        self.assertTrue(kwargs["check"])
        source, target = map(Path, command[2:])
        self.assertEqual(source.parent, self.build)
        self.assertEqual(target.parent, self.destination)
        self.assertNotEqual(source, target)
        target.write_bytes(b"code")
        target.chmod(0o700)

    def test_copies_at_the_exact_limit_preserve_original_bytes_and_modes(self):
        original = {p.name: (p.read_bytes(), p.stat().st_mode) for p in self.build.iterdir()}
        with patch.object(binaries.subprocess, "run", side_effect=self.copy) as run:
            self.assertEqual(binaries.prepare(self.build, self.destination, 4),
                             {"latent": 4, "latentd": 4})
        self.assertEqual(run.call_count, 2)
        self.assertEqual(original, {p.name: (p.read_bytes(), p.stat().st_mode)
                                    for p in self.build.iterdir()})

    def test_oversized_copy_fails_without_raising_the_limit(self):
        with patch.object(binaries.subprocess, "run", side_effect=self.copy) as run:
            with self.assertRaisesRegex(ValueError, "resource-binary-output-bound"):
                binaries.prepare(self.build, self.destination, 3)
        self.assertEqual(run.call_count, 1)

    def test_existing_destination_cannot_overwrite_a_cargo_binary(self):
        with patch.object(binaries.subprocess, "run") as run:
            with self.assertRaises(FileExistsError):
                binaries.prepare(self.build, self.build, 1024)
        run.assert_not_called()
        self.assertEqual((self.build / "latent").read_bytes(), b"executable-with-debug-data")

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks")
    def test_symlink_source_is_rejected_before_staging(self):
        source = self.build / "latent"
        source.unlink()
        source.symlink_to(self.build / "latentd")
        with patch.object(binaries.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "resource-binary-source"):
                binaries.prepare(self.build, self.destination, 1024)
        run.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_objcopy_failure_and_timeout_are_not_successful_preparation(self):
        for error in (subprocess.CalledProcessError(1, "objcopy"),
                      subprocess.TimeoutExpired("objcopy", 60)):
            with self.subTest(error=type(error).__name__):
                with patch.object(binaries.subprocess, "run", side_effect=error) as run:
                    with self.assertRaises(subprocess.SubprocessError):
                        binaries.prepare(self.build, self.destination, 1024)
                self.assertEqual(run.call_count, 1)
                self.destination.rmdir()

    def test_empty_or_nonexecutable_output_is_rejected(self):
        for executable in (False, True):
            def invalid_copy(command, **kwargs):
                target = Path(command[-1])
                target.write_bytes(b"" if executable else b"code")
                target.chmod(0o700 if executable else 0o600)
            with self.subTest(executable=executable):
                with patch.object(binaries.subprocess, "run", side_effect=invalid_copy):
                    with self.assertRaisesRegex(ValueError, "resource-binary-output-bound"):
                        binaries.prepare(self.build, self.destination, 1024)
                shutil.rmtree(self.destination)

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("cc") and shutil.which("objcopy"),
                         "Linux C compiler and objcopy required")
    def test_real_debug_sections_are_removed_without_changing_executable_behavior(self):
        source = self.root / "main.c"
        source.write_text("int main(void) { return 23; }\n")
        subprocess.run(["cc", "-g", str(source), "-o", str(self.build / "latent")],
                       check=True, timeout=30, capture_output=True)
        shutil.copy2(self.build / "latent", self.build / "latentd")
        original = (self.build / "latent").read_bytes()
        sizes = binaries.prepare(self.build, self.destination, len(original) - 1)
        for name in binaries.NAMES:
            self.assertLess(sizes[name], len(original))
            self.assertEqual((self.build / name).read_bytes(), original)
            self.assertEqual(subprocess.run([str(self.destination / name)],
                                           timeout=5, check=False).returncode, 23)

    def test_ci_hashes_and_launches_the_staged_pair_not_cargo_outputs(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / ".github/workflows/ci.yml").read_text()
        resource = text.split('resource_bins="${fixture_root}/resource-binaries"', 1)[1]
        resource = resource.split("      - name: Retain compact Phase 2 gate receipts", 1)[0]
        self.assertIn('tools/phase2_resource_binaries.py --build-directory "${PWD}/target/debug" '
                      '--output-directory "${resource_bins}"', resource)
        identity = resource.split("identity = {", 1)[1].split("PY", 1)[0]
        self.assertIn('"cliSha256": digest(binaries / "latent")', identity)
        self.assertIn('"nodeSha256": digest(binaries / "latentd")', identity)
        self.assertNotIn("target/debug", identity)
        self.assertIn('tools/phase2_gate_resource.py --cli "${resource_bins}/latent" '
                      '--node "${resource_bins}/latentd"', resource)
        self.assertIn('"buildProfile": "debug"', identity)


if __name__ == "__main__":
    unittest.main()
