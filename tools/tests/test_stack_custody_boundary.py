"""Custody review tripwires and feature-specific runner failure behavior."""
from pathlib import Path
import os
import platform
import shutil
import subprocess
import tempfile
import unittest

from tools import native_loader_boundary as boundary

ROOT = Path(__file__).resolve().parents[2]
WITNESS = ("native_stacks::tests::stack_custody_allocation::"
           "original_metadata_charge_survives_actual_stack_context_backing_deallocation")
COMBINED = "native_stacks::tests::combined::fixture_case"


class CustodyReview(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # A minimal policy fixture, not a replacement for the full workspace scan.
        self.write("Cargo.toml", '''[workspace]
members = ["crates/latent-wasmtime"]
[workspace.lints.rust]
unsafe_code = "forbid"
[workspace.lints.clippy]
all = "warn"
[workspace.dependencies.wasmtime]
version = "=48.0.8"
default-features = false
''')
        self.write(f"{boundary.CRATE}/Cargo.toml", '''[lints.rust]
unsafe_code = "deny"
[lints.clippy]
all = "warn"
''')
        self.write(f"{boundary.CRATE}/src/lib.rs", "#![deny(unsafe_code)]\n")
        self.write(boundary.LOADER, boundary.ALLOW + "\n" + boundary.FUNCTION
                   + "\nfn load_failed() {}\n")
        for relative in (boundary.NATIVE_STACK, boundary.NATIVE_STACK_COMBINED,
                         boundary.NATIVE_STACK_CUSTODY_TEST):
            self.write(relative, (ROOT / relative).read_text())

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_reviewed_custody_and_test_allocator_are_accepted(self):
        self.assertEqual(boundary.validate(self.root), [])

    def test_changed_production_custody_requires_review(self):
        for relative in (boundary.NATIVE_STACK, boundary.NATIVE_STACK_COMBINED):
            with self.subTest(relative=relative):
                original = (self.root / relative).read_text()
                self.write(relative, original + "\n// changed owner implementation\n")
                self.assertTrue(boundary.validate(self.root))
                self.write(relative, original)

    def test_changed_or_ungated_observer_requires_review(self):
        relative = boundary.NATIVE_STACK_CUSTODY_TEST
        original = (self.root / relative).read_text()
        for changed in (original.replace("    test,\n", "", 1),
                        original.replace("System.dealloc(pointer, layout)", "unreviewed_free(pointer)")):
            with self.subTest(changed=changed[:100]):
                self.assertNotEqual(changed, original)
                self.write(relative, changed)
                errors = boundary.validate(self.root)
                self.assertTrue(any("audited native-stack custody test allocator changed" in e for e in errors))
                self.assertTrue(any("unreviewed unsafe" in e for e in errors))
        self.write(relative, original)

    def test_reviewed_allocator_cannot_be_copied_to_another_path(self):
        self.write(f"{boundary.CRATE}/src/unreviewed_allocator.rs",
                   (ROOT / boundary.NATIVE_STACK_CUSTODY_TEST).read_text())
        self.assertTrue(any("unreviewed unsafe" in e for e in boundary.validate(self.root)))


@unittest.skipUnless(platform.system() == "Linux" and platform.machine() == "x86_64",
                     "runner requires Linux x86_64")
class CustodyRunner(unittest.TestCase):
    def run_script(self, mode="pass"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tools").mkdir()
            script = root / "tools/run_stack_custody_witness.sh"
            shutil.copyfile(ROOT / "tools/run_stack_custody_witness.sh", script)
            fake = root / "cargo"
            fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
with Path(os.environ["CALLS"]).open("a") as output:
    output.write(json.dumps(sys.argv[1:]) + "\\n")
mode = os.environ["MODE"]
listing = "--list" in sys.argv
combined = "development-rust-http-combined" in " ".join(sys.argv)
if mode == "list-failure" and listing:
    sys.exit(7)
if mode == "run-failure" and not listing:
    sys.exit(8)
witness = os.environ["WITNESS"]
if mode != "missing":
    print(witness + ": test" if listing else "test " + witness + " ... " + ("ignored" if mode == "ignored" else "ok"))
if combined and mode != "missing-combined":
    case = os.environ["COMBINED"]
    print(case + ": test" if listing else "test " + case + " ... " + ("ignored" if mode == "ignored-combined" else "ok"))
''')
            fake.chmod(0o755)
            calls = root / "calls.jsonl"
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                   "MODE": mode, "CALLS": str(calls), "WITNESS": WITNESS, "COMBINED": COMBINED}
            result = subprocess.run(["bash", str(script), str(root / "output")],
                                    env=env, capture_output=True, text=True, timeout=15)
            import json
            commands = [json.loads(line) for line in calls.read_text().splitlines()]
            return result, commands

    def test_both_explicit_profiles_discover_and_execute(self):
        result, commands = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(commands), 4)
        for index, command in enumerate(commands):
            self.assertIn("--locked", command)
            self.assertNotIn("--all-features", command)
            features = command[command.index("--features") + 1].split(",")
            self.assertIn("development-stack-custody-witness", features)
            self.assertNotIn("development-go-timer-overlap", features)
            self.assertEqual("development-rust-http-combined" in features, index >= 2)
            self.assertEqual("--list" in command, index % 2 == 0)

    def test_missing_ignored_or_failed_execution_never_passes(self):
        for mode in ("missing", "ignored", "missing-combined", "ignored-combined",
                     "list-failure", "run-failure"):
            with self.subTest(mode=mode):
                result, _ = self.run_script(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
