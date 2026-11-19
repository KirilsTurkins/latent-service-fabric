"""Custody review tripwires and feature-specific runner failure behavior."""
from pathlib import Path
import json
import os
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


class CustodyRunner(unittest.TestCase):
    def run_script(self, mode="pass", system="Linux", machine="x86_64"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tools").mkdir()
            script = root / "tools/run_stack_custody_witness.sh"
            shutil.copyfile(ROOT / "tools/run_stack_custody_witness.sh", script)
            programs = {
                "uname": '''import os, sys
print(os.environ["SYSTEM"] if sys.argv[1] == "-s" else os.environ["MACHINE"])
''',
                "timeout": '''import json, os, subprocess, sys
from pathlib import Path
with Path(os.environ["TIMEOUT_CALLS"]).open("a") as output:
    output.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] != ["--kill-after=10s", "180s"]:
    sys.exit(9)
if os.environ["MODE"] == "timeout":
    sys.exit(124)
sys.exit(subprocess.run(sys.argv[3:]).returncode)
''',
                "cargo": '''import json, os, sys
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
    for suffix in ("", "_second"):
        if suffix and mode == "partial-combined" and not listing:
            continue
        case = os.environ["COMBINED"] + suffix
        ignored = mode == "ignored-combined" or (suffix and mode == "partial-ignored")
        print(case + ": test" if listing else "test " + case + " ... " + ("ignored" if ignored else "ok"))
''',
            }
            for name, source in programs.items():
                fake = root / name
                fake.write_text("#!/usr/bin/env python3\n" + source)
                fake.chmod(0o755)
            calls = root / "calls.jsonl"
            timeouts = root / "timeouts.jsonl"
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                   "MODE": mode, "CALLS": str(calls), "TIMEOUT_CALLS": str(timeouts),
                   "WITNESS": WITNESS, "COMBINED": COMBINED,
                   "SYSTEM": system, "MACHINE": machine}
            result = subprocess.run(["bash", str(script), str(root / "output")],
                                    env=env, capture_output=True, text=True, timeout=15)
            def read_calls(path):
                return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
            return result, read_calls(calls), read_calls(timeouts)

    def test_both_explicit_profiles_discover_and_execute(self):
        result, commands, timeouts = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(commands), 4)
        self.assertEqual(len(timeouts), 2)
        for timeout in timeouts:
            self.assertEqual(timeout[:3], ["--kill-after=10s", "180s", "cargo"])
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
                     "partial-combined", "partial-ignored", "list-failure", "run-failure"):
            with self.subTest(mode=mode):
                result, _, _ = self.run_script(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_timeout_stops_before_the_next_profile(self):
        result, commands, timeouts = self.run_script("timeout")
        self.assertEqual(result.returncode, 124, result.stdout + result.stderr)
        self.assertEqual(len(commands), 1)
        self.assertIn("--list", commands[0])
        self.assertEqual(len(timeouts), 1)

    def test_unsupported_platform_fails_before_invoking_cargo(self):
        for system, machine in (("Darwin", "x86_64"), ("Linux", "aarch64")):
            with self.subTest(system=system, machine=machine):
                result, commands, timeouts = self.run_script(system=system, machine=machine)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires Linux x86_64", result.stderr)
                self.assertEqual(commands, [])
                self.assertEqual(timeouts, [])

    def test_dedicated_workflow_uses_the_same_fail_closed_runner(self):
        from tools import ci_lane_inventory as lanes

        name = ".github/workflows/native-stack-custody.yml"
        model = lanes.workflow_model((ROOT / name).read_text())
        for trigger in ("pull_request", "push"):
            event = model["on"][trigger]
            self.assertEqual(event["branches"], ["development"])
            for required in (name, "tools/run_stack_custody_witness.sh",
                             "crates/latent-wasmtime/src/lib.rs",
                             "crates/latent-wasmtime/src/native_stacks/**",
                             "crates/vendor/wasmtime/**", "Cargo.toml", "Cargo.lock"):
                self.assertIn(required, event["paths"])
        self.assertEqual(model["permissions"], {"contents": "read"})
        job = model["jobs"]["custody"]
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        self.assertGreater(job["timeout-minutes"], 0)
        self.assertLessEqual(job["timeout-minutes"], 30)
        commands = [step["run"] for step in job["steps"] if "run" in step]
        self.assertEqual(commands, [
            'bash tools/run_stack_custody_witness.sh "$RUNNER_TEMP/native-stack-custody"'])
        self.assertFalse(any(step.get("continue-on-error", False) for step in job["steps"]))
        retained = [step for step in job["steps"]
                    if step.get("uses", "").startswith("KirilsTurkins/lsf-upload-artifact@")]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]["if"], "always()")
        self.assertEqual(retained[0]["with"]["path"],
                         "${{ runner.temp }}/native-stack-custody/")


if __name__ == "__main__":
    unittest.main()
