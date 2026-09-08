"""Collection protocol and tiny supervised helper tests; no guest/build work."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from artifact_identity_runner import build, files, helpers, model
from artifact_identity_runner.run import make_run
from optimization_runner import processes


class PopulationTests(unittest.TestCase):
    def receipt(self, profile):
        result = model.suite(profile, "a" * 40, "b" * 40)
        result["builds"] = {arm: {"binary": {"path": f"builds/{arm}/probe"}}
                            for arm in ("control", "candidate")}
        result["fixtures"] = {
            name: {"root": f"fixtures/{name}", "manifest": {"component_bytes": str(size)}}
            for name, size in (("small", 32768), ("16m", 16 * 1024 * 1024), ("64m", 64 * 1024 * 1024))}
        return result

    def test_complete_unique_population_and_alternating_pair_order(self):
        for profile, expected, pairs, sizes in (("smoke", 12, 1, 1), ("full", 252, 7, 3)):
            with self.subTest(profile=profile):
                population = list(model.population(profile))
                self.assertEqual(len(population), expected)
                self.assertEqual(len(set(population)), expected)
                self.assertEqual(Counter(row[0] for row in population),
                                 {pair: sizes * 12 for pair in range(1, pairs + 1)})
                self.assertEqual(Counter(row[1] for row in population),
                                 {"control": expected // 2, "candidate": expected // 2})
                for index in range(0, expected, 2):
                    first, second = population[index:index + 2]
                    self.assertEqual(first[:1] + first[2:], second[:1] + second[2:])
                    self.assertEqual((first[1], second[1]), ("control", "candidate")
                                     if first[0] % 2 else ("candidate", "control"))

    def test_run_commands_use_exact_population_counts_and_separate_profiling(self):
        output = Path("evidence")
        for profile in ("smoke", "full"):
            receipt = self.receipt(profile)
            directories = set()
            for row in model.population(profile):
                record, directory = make_run(*row, receipt, output, "heaptrack")
                directories.add(directory)
                pair, arm, size, operation, mode = row
                argv = record["command"]
                expected = {"small": 2048, "16m": 4, "64m": 1}[size] if profile == "full" and operation == "hash" else 1
                self.assertEqual(argv[argv.index("--iterations") + 1], str(expected))
                self.assertEqual(argv[argv.index("--fixture") + 1], str(output / "fixtures" / size))
                self.assertIn(str(output / "builds" / arm / "probe"), argv)
                self.assertEqual(argv[:2], ["heaptrack", "--output"] if mode == "allocation"
                                 else [str(output / "builds" / arm / "probe"), "measure"])
                self.assertEqual(record["status"], "failed")
                self.assertIsNone(record["cpu"])
                self.assertIsNone(record["profile_refs"])
            self.assertEqual(len(directories), 12 if profile == "smoke" else 252)

    def test_hash_iteration_cap_and_floor(self):
        receipt = self.receipt("full")
        for size, expected in ((1, "4096"), (64 * 1024 * 1024, "1")):
            receipt["fixtures"]["small"]["manifest"]["component_bytes"] = str(size)
            record, _ = make_run(1, "control", "small", "hash", "normal", receipt, Path("out"), "heaptrack")
            self.assertEqual(record["command"][-1], expected)


class ProvenanceTests(unittest.TestCase):
    def test_full_refs_require_distinct_exact_commit_identifiers(self):
        build.validate_refs("a" * 40, "a" * 40, "smoke")
        build.validate_refs("a" * 40, "b" * 40, "full")
        for control, candidate in (("HEAD", "b" * 40), ("A" * 40, "b" * 40),
                                   ("a" * 39, "b" * 40), ("a" * 40, "a" * 40)):
            with self.subTest(control=control), self.assertRaises(ValueError):
                build.validate_refs(control, candidate, "full")

    def test_dirty_source_rejected_before_recording_identity(self):
        with patch.object(build, "git", return_value=" M Cargo.lock") as git:
            with self.assertRaisesRegex(ValueError, "source-dirty"):
                build.identity(Path("source"))
            self.assertEqual(git.call_count, 1)
        with patch.object(build, "git", side_effect=["", "a" * 40, "b" * 40]):
            self.assertEqual(build.identity(Path("source")),
                             {"commit": "a" * 40, "tree": "b" * 40, "clean": True})

    def test_each_build_control_must_match_before_building(self):
        for mismatch in model.PAIRED_INPUTS:
            def git(_root, _operation, identifier):
                return "different" if identifier == f"candidate:{mismatch}" else "same"
            with self.subTest(input=mismatch), patch.object(build, "git", side_effect=git):
                with self.assertRaisesRegex(ValueError, "build-controls-differ"):
                    build.matching_controls(Path("repo"), "control", "candidate")
        with patch.object(build, "git", return_value="same"):
            build.matching_controls(Path("repo"), "control", "candidate")

    def test_entry_help_works_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / "tools/run_artifact_identity_benchmarks.py"), "--help"],
                                    cwd=directory, capture_output=True, timeout=5, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertIn(b"--control-ref", result.stdout)

    def test_owned_probe_rechecks_outer_deadline_after_executable_hashing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            order = []
            def checksum(_path):
                order.append("hash")
                return "sha256:" + "a" * 64, 1
            def clock():
                order.append("clock")
                return 101
            with patch.object(processes, "digest", side_effect=checksum), \
                    patch.object(processes.time, "monotonic_ns", side_effect=clock), \
                    patch.object(processes.subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(TimeoutError, "before spawn"):
                    processes.OwnedProcess(["never-executed"], root / "never-created.log",
                                           "probe", 1, root, overall_deadline_ns=100)
                spawn.assert_not_called()
                self.assertFalse((root / "never-created.log").exists())
                self.assertEqual(order, ["hash", "clock"])


class FixtureBoundsTests(unittest.TestCase):
    def test_warming_rejects_same_length_changed_bytes_and_added_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = root / "component.wasm"
            component.write_bytes(b"abc")
            (root / ".owner.lock").write_bytes(b"")
            expected = files.inventory(root, root)
            self.assertEqual(expected["component.wasm"]["sha256"], "sha256:" + hashlib.sha256(b"abc").hexdigest())
            self.assertEqual(files.warm(root, expected, root)["bytes"], "3")
            component.write_bytes(b"abd")
            with self.assertRaisesRegex(ValueError, "fixture-mutated"):
                files.warm(root, expected, root)
            component.write_bytes(b"abc")
            (root / "extra").write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "fixture-mutated"):
                files.warm(root, expected, root)

    def test_file_count_and_storage_bounds_apply_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = root / "one"
            item.write_bytes(b"abcd")
            with self.assertRaisesRegex(ValueError, "file-bound"):
                files.fingerprint(item, 3)
            with patch.object(files, "MAX_TOTAL_BYTES", 3), self.assertRaisesRegex(ValueError, "storage-bound"):
                files.total_bytes(root)
            (root / "two").write_bytes(b"")
            with patch.object(files, "MAX_FILES", 1), self.assertRaisesRegex(ValueError, "count-bound"):
                files.files(root)

    @unittest.skipUnless(sys.platform == "linux", "Linux filesystem fixtures")
    def test_nonregular_fixture_paths_are_rejected_without_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.mkfifo(root / "fifo")
            with self.assertRaisesRegex(ValueError, "nonregular"):
                files.files(root)
            (root / "fifo").unlink()
            (root / "link").symlink_to(root)
            with self.assertRaisesRegex(ValueError, "symlink"):
                files.files(root)


@unittest.skipUnless(sys.platform == "linux", "Linux owned process-group tests")
class HelperOwnershipTests(unittest.TestCase):
    def invoke(self, script, *, timeout=2, maximum=4096, error=None):
        with tempfile.TemporaryDirectory() as directory:
            root, log = Path(directory), Path(directory) / "child.log"
            argv = [str(Path(sys.executable).resolve()), "-c", script]
            invoke = lambda: helpers.command(argv, log, timeout, root, time.monotonic_ns() + 5_000_000_000, maximum=maximum)
            if error:
                with self.assertRaisesRegex(error[0], error[1]):
                    invoke()
            else:
                invoke()
            receipt = json.loads(log.with_suffix(".log.process.json").read_bytes())
            self.assertTrue(receipt["reaped"])
            self.assertTrue(receipt["output_closed"])
            with self.assertRaises(ChildProcessError):
                os.waitpid(receipt["process_id"], os.WNOHANG)
            self.assertLessEqual(log.stat().st_size, maximum)
            return receipt, log.read_bytes()

    def test_success_and_failure_keep_real_exit_receipts(self):
        receipt, output = self.invoke("print('completed', flush=True)")
        self.assertEqual(receipt["exit_code"], 0)
        self.assertEqual(output, b"completed\n")
        receipt, output = self.invoke("import sys; print('failed', flush=True); sys.exit(7)",
                                      error=(RuntimeError, "helper-exit-failed"))
        self.assertEqual(receipt["exit_code"], 7)
        self.assertEqual(output, b"failed\n")

    def test_timeout_and_output_overflow_kill_and_reap(self):
        receipt, _ = self.invoke("import time; time.sleep(30)", timeout=0.05,
                                 error=(TimeoutError, "helper-deadline"))
        self.assertEqual(receipt["exit_code"], -9)
        receipt, _ = self.invoke("import os,time; os.write(1,b'x'*4096); time.sleep(30)", maximum=128,
                                 error=(ValueError, "helper-output-bound"))
        self.assertEqual(receipt["exit_code"], -9)

    def test_expired_outer_deadline_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(helpers.subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(TimeoutError, "before-spawn"):
                    helpers.command([str(Path(sys.executable).resolve()), "-c", "raise AssertionError"],
                                    root / "expired.log", 5, root, time.monotonic_ns() - 1)
                spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
