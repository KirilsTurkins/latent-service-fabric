"""Bounded output trees and failed collector ownership; no guest executions."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.artifact_identity_runner import helpers
from tools.optimization_backend_revision import collect


COLD = helpers.DirectoryLimits(2, 64, 80, 16 * 1024**2)


class DirectoryWatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_real_cold_layout_is_counted_and_legacy_flat_watch_stays_strict(self):
        expected = 0
        for key in range(8):
            target = self.root / "fixtures" / f"key-{key}"
            target.mkdir(parents=True)
            for name in ("component.wasm", "capsule.json", "contracts.json", "deployment.json"):
                content = name.encode()
                (target / name).write_bytes(content)
                expected += len(content)
        for name in ("identity.json", "plan.json", "collector.log", "cold.json"):
            (self.root / name).write_bytes(b"{}")
            expected += 2
        self.assertEqual(helpers.directory_bytes(self.root, COLD), expected)
        with self.assertRaisesRegex(ValueError, "count-or-type"):
            helpers.directory_bytes(self.root)

    def test_legacy_sixteen_file_limit_is_unchanged(self):
        for index in range(16):
            (self.root / str(index)).touch()
        self.assertEqual(helpers.directory_bytes(self.root), 0)
        (self.root / "extra").touch()
        with self.assertRaisesRegex(ValueError, "count-or-type"):
            helpers.directory_bytes(self.root)

    def test_tree_depth_is_bounded_even_for_empty_directories(self):
        (self.root / "fixtures" / "key-0" / "unexpected").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "depth-bound"):
            helpers.directory_bytes(self.root, COLD)

    def test_files_and_total_entries_have_independent_bounds(self):
        for index in range(65):
            (self.root / str(index)).touch()
        with self.assertRaisesRegex(ValueError, "count-or-type"):
            helpers.directory_bytes(self.root, COLD)
        for item in self.root.iterdir():
            item.unlink()
        for index in range(81):
            (self.root / str(index)).mkdir()
        with self.assertRaisesRegex(ValueError, "count-or-type"):
            helpers.directory_bytes(self.root, COLD)

    def test_per_file_byte_bound_and_recursive_total_are_actual_sizes(self):
        item = self.root / "large"
        with item.open("wb") as output:
            output.truncate(16 * 1024**2 + 1)
        with self.assertRaisesRegex(ValueError, "byte-bound"):
            helpers.directory_bytes(self.root, COLD)
        item.unlink()
        for index in range(3):
            target = self.root / str(index)
            target.mkdir()
            with (target / "data").open("wb") as output:
                output.truncate(12 * 1024**2)
        self.assertEqual(helpers.directory_bytes(self.root, COLD), 36 * 1024**2)

    def test_symlink_and_dangling_symlink_are_rejected(self):
        link = self.root / "link"
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "count-or-type"):
            helpers.directory_bytes(self.root, COLD)
        link.unlink()
        link.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(ValueError, "count-or-type"):
            helpers.directory_bytes(self.root, COLD)

    @unittest.skipUnless(sys.platform == "linux", "Linux FIFO fixture")
    def test_special_file_is_rejected_without_opening(self):
        os.mkfifo(self.root / "fifo")
        with self.assertRaisesRegex(ValueError, "count-or-type"):
            helpers.directory_bytes(self.root, COLD)

    def test_watcher_limits_cannot_be_unbounded_or_boolean(self):
        for values in ((3, 64, 80, 1), (2, 65, 80, 1), (2, 64, 81, 1),
                       (True, 64, 80, 1), (2, 64, 80, 0)):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "directory-limits"):
                helpers.DirectoryLimits(*values)


class CollectorFailureCleanupTests(unittest.TestCase):
    def test_cold_failure_retains_actual_data_removal_and_supervision_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            builds = {"requested_refs": {"harness": "a" * 40},
                      "builds": {"control": {"executables": {"backend": {"path": "unused"}}}},
                      "harness": {"echo": {"component": {"path": "echo.wasm"}}}}
            path = output / "backend-builds.json"
            path.write_text(json.dumps(builds), encoding="utf-8")
            args = SimpleNamespace(builds=path, target_root=root / "data", profile="smoke", experiment="cold")
            observed = []
            def failed_command(*positional, **options):
                data = Path(positional[5]["LSF_PHASE1_COMPARISON_DATA_ROOT"])
                self.assertTrue(data.is_dir())
                (data / "owned").write_bytes(b"retained until context exit")
                observed.append((data, options))
                raise RuntimeError("synthetic-helper-failure")
            result = {"population_complete": False, "status": "failed"}
            with patch.object(collect.platform, "system", return_value="Linux"), \
                    patch.object(collect.os, "sysconf", return_value=100, create=True), \
                    patch.dict(os.environ, {name: "" for name in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")}), \
                    patch.object(collect, "source", return_value={"commit": "a" * 40}), \
                    patch.object(collect, "host", return_value={}), patch.object(collect, "cgroup", return_value={}), \
                    patch.object(collect.model, "population", return_value=[(1, "control")]), \
                    patch.object(collect.model, "identity", return_value={}), \
                    patch("tools.optimization_backend_revision.evidence.artifact_set", return_value={}), \
                    patch("tools.optimization_backend_revision.builds.validate_experiment"), \
                    patch("tools.optimization_backend_revision.evidence.validate_suite", return_value=result), \
                    patch.object(collect, "command", side_effect=failed_command):
                self.assertEqual(collect.execute(args, root), 1)
            self.assertTrue(observed, (output / "failure.json").read_text(encoding="utf-8"))
            data, options = observed[0]
            self.assertFalse(data.exists())
            self.assertEqual(options, {"watched": output / "runs/pair-01-control", "remaining": 32 * 1024**2,
                                       "maximum": 1024**2, "directory_limits": COLD})
            suite = json.loads((output / "suite.json").read_bytes())
            self.assertEqual(suite["runs"][0]["status"], "failed")
            cleanup = output / suite["runs"][0]["cleanup"]["path"]
            self.assertEqual(json.loads(cleanup.read_bytes()), {"removed": True})
            self.assertIsNone(suite["runs"][0]["raw"])
            self.assertIsNone(suite["runs"][0]["process"])


@unittest.skipUnless(sys.platform == "linux", "Linux bounded helper ownership")
class LiveDirectoryWatchTests(unittest.TestCase):
    def test_nested_output_total_failure_kills_and_reaps_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "helper.log"
            script = "from pathlib import Path; import time; p=Path('fixtures/key-0'); p.mkdir(parents=True); (p/'data').write_bytes(b'xx'); time.sleep(5)"
            with self.assertRaisesRegex(ValueError, "total-output-bound"):
                helpers.command([str(Path(sys.executable).resolve()), "-c", script], log, 2, root,
                                time.monotonic_ns()+5_000_000_000, watched=root, remaining=1, directory_limits=COLD)
            receipt = json.loads(log.with_suffix(".log.process.json").read_bytes())
            self.assertTrue(receipt["reaped"] and receipt["output_closed"])
            self.assertEqual(receipt["exit_code"], -9)


if __name__ == "__main__":
    unittest.main()
