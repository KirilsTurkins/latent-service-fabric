"""Deterministic collector/restore tests; synthetic streams are not Cargo evidence."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

from tools import ci_cargo, ci_cargo_observe as observe, ci_cargo_probe as probe
from tools.owned_test_process import ProcessFailure


def stream(fresh=False):
    return (json.dumps({"reason": "compiler-artifact", "package_id": "test#0.1.0",
                       "target": {"name": "test", "kind": ["lib"]}, "profile": {"test": True},
                       "features": [], "filenames": [], "fresh": fresh}) + "\n" +
            '{"reason":"build-finished","success":true}\n').encode()


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_cargo_freshness_is_artifacts_not_compiler_processes(self):
        for fresh in (True, False):
            records, units = observe.cargo_records(b"ordinary diagnostic\n" + stream(fresh) + b"test result: ok\n")
            self.assertEqual(len(records), 2)
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0]["fresh"], fresh)
        self.assertEqual(observe.cargo_records(stream(True))[1][0]["identity"],
                         observe.cargo_records(stream(False))[1][0]["identity"])

    def test_missing_failed_duplicate_and_postcompletion_records_fail(self):
        variants = [b"", stream().splitlines()[0], stream().replace(b'"success":true', b'"success":false'),
                    stream().replace(b'"fresh": false', b'"fresh": false, "fresh": true'), stream() + stream(),
                    stream().replace(b'"fresh": false', b'"fresh": "false"')]
        for raw in variants:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                observe.cargo_records(raw)

    def test_output_and_line_bounds_are_enforced(self):
        with mock.patch.object(observe, "MAX_BYTES", 2), self.assertRaises(ValueError):
            observe.cargo_records(stream())
        with mock.patch.object(observe, "MAX_LINE", 2), self.assertRaises(ValueError):
            observe.cargo_records(stream())

    def test_message_format_and_timing_options_preserve_strict_clippy_separator(self):
        invocation = ci_cargo.RECIPES["clippy"][1]
        argv = observe.observed_argv(invocation, "current")
        self.assertLess(argv.index("--message-format=json,json-render-diagnostics"), argv.index("--"))
        self.assertLess(argv.index("--timings"), argv.index("--"))
        self.assertEqual(argv[-3:], ["--", "-D", "warnings"])
        inventory = observe.observed_argv(ci_cargo.RECIPES["prepare"][1], "current")
        self.assertEqual(sum(arg.startswith("--message-format") for arg in inventory), 1)
        with self.assertRaises(ValueError):
            observe.observed_argv(ci_cargo.RECIPES["format"][0], "current")

    def test_fingerprint_data_is_hashed_not_disclosed(self):
        target = self.root / "target"
        path = target / "debug/.fingerprint/example-abcdef/lib-example.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"env":"private-value"}')
        before = observe.fingerprint_snapshot(target)
        self.assertNotIn("private-value", json.dumps(before))
        path.write_text('{"env":"changed-value"}')
        self.assertNotEqual(before, observe.fingerprint_snapshot(target))
        with mock.patch.object(observe, "MAX_FILES", 0), self.assertRaises(ValueError):
            observe.fingerprint_snapshot(target)

    def test_fingerprint_and_output_links_are_rejected(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "linked"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError):
            observe.fingerprint_snapshot(link)
        with self.assertRaises(ValueError):
            observe.output_directory(link / "output", self.root)

    def test_observation_outputs_cannot_overwrite_sources_or_previous_runs(self):
        with self.assertRaises(ValueError):
            observe.output_directory(self.root / "source", self.root)
        output = self.root / "target/output"
        observe.output_directory(output, self.root)
        with self.assertRaises(FileExistsError):
            observe.output_directory(output, self.root)
        with self.assertRaises(ValueError):
            observe.output_directory(self.root / "target/../source", self.root)

    def test_gnu_time_requires_finite_complete_fields_and_defines_rss(self):
        path = self.root / "time.txt"
        valid = "elapsedSeconds=1.23\nuserSeconds=0.5\nsystemSeconds=0.1\nmaximumChildRssKiB=1234\nexitCode=0\n"
        path.write_text(valid)
        self.assertEqual(observe.time_metrics(path)["maximumChildRssKiB"], 1234)
        self.assertIn("not simultaneous", observe.time_metrics(path)["rssDefinition"])
        for text in (valid.replace("1.23", "nan"), valid + "exitCode=0\n", "elapsedSeconds=0\n"):
            path.write_text(text)
            with self.assertRaises(ValueError):
                observe.time_metrics(path)

    def test_inventory_destination_is_checked_even_through_python_api(self):
        invocation = ci_cargo.RECIPES["prepare"][1]
        with self.assertRaises(ValueError):
            observe.observe(invocation, repo=self.root, output=self.root / "target/output", inventory=self.root / "Cargo.toml")


class NativeObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        available = sys.platform == "linux" and Path(f"/proc/self/task/{os.getpid()}/children").is_file()
        if not available:
            if os.environ.get("LSF_REQUIRE_NATIVE_PROCESS_TESTS") == "1":
                raise AssertionError("required native Cargo observation accounting unavailable")
            raise unittest.SkipTest("native descendant accounting unavailable; not passing observation coverage")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_real_owned_failure_preserves_status_and_failed_stage_record(self):
        invocation = ci_cargo.RECIPES["workspace-check"][0]
        with mock.patch.object(observe, "observed_argv", return_value=[sys.executable, "-c", "raise SystemExit(17)"]), \
             mock.patch.object(observe.TestRun, "source_identity"), self.assertRaises(ProcessFailure) as failure:
            observe.observe(invocation, repo=self.root, output=self.root / "target/failure", timeout=10)
        self.assertEqual(failure.exception.result.returncode, 17)
        record = json.loads((self.root / "target/failure/observation.json").read_text())
        self.assertFalse(record["passed"])
        self.assertEqual(record["stageDiagnostic"]["outcome"], "failed")
        self.assertTrue(record["stageDiagnostic"]["child"]["cleanupAcknowledged"])

    def test_diagnostic_failure_does_not_replace_primary_command_failure(self):
        invocation = ci_cargo.RECIPES["workspace-check"][0]
        with mock.patch.object(observe, "observed_argv", return_value=[sys.executable, "-c", "raise SystemExit(17)"]), \
             mock.patch.object(observe.TestRun, "source_identity"), \
             mock.patch.object(observe, "time_metrics", side_effect=ValueError("controlled-diagnostic-failure")), \
             self.assertRaises(ProcessFailure) as failure:
            observe.observe(invocation, repo=self.root, output=self.root / "target/failure", timeout=10)
        self.assertEqual(failure.exception.result.returncode, 17)
        self.assertFalse(json.loads((self.root / "target/failure/observation.json").read_text())["passed"])

    def test_real_owned_success_retains_inventory_without_cache_short_circuit(self):
        invocation = ci_cargo.RECIPES["prepare"][1]
        inventory = self.root / "target/inventory.jsonl"
        with mock.patch.object(observe, "observed_argv", return_value=[sys.executable, "-c", "print(" + repr(stream().decode()) + ")"]), \
             mock.patch.object(observe.TestRun, "source_identity"):
            record = observe.observe(invocation, repo=self.root, output=self.root / "target/success", inventory=inventory, timeout=10)
        self.assertTrue(record["passed"])
        self.assertEqual(record["builtArtifactRecords"], 1)
        ci_cargo.validate_inventory(inventory)

    def test_native_split_json_writes_keep_stderr_out_of_artifact_handoff(self):
        invocation = ci_cargo.RECIPES["prepare"][1]
        inventory = self.root / "target/inventory.jsonl"
        raw = stream()
        split = raw.index(b',') + 1
        code = ("import os; os.write(1," + repr(raw[:split]) + "); "
                "os.write(2,b'fingerprint diagnostic token=private-observer-canary\\n'); "
                "os.write(1," + repr(raw[split:]) + ")")
        with mock.patch.object(observe, "observed_argv", return_value=[sys.executable, "-c", code]), \
             mock.patch.object(observe.TestRun, "source_identity"):
            record = observe.observe(invocation, repo=self.root, output=self.root / "target/split",
                                     inventory=inventory, timeout=10)
        self.assertTrue(record["passed"])
        self.assertEqual(record["builtArtifactRecords"], 1)
        self.assertEqual(len(inventory.read_text().splitlines()), 2)
        ci_cargo.validate_inventory(inventory)
        self.assertNotIn("fingerprint diagnostic", (self.root / "target/split/cargo.log").read_text())
        diagnostics = (self.root / "target/split/cargo-diagnostics.log").read_text()
        self.assertIn("fingerprint diagnostic", diagnostics)
        self.assertNotIn("private-observer-canary", diagnostics)
        self.assertTrue(record["stageDiagnostic"]["child"]["cleanupAcknowledged"])


    def test_native_stderr_case_records_validate_without_polluting_json_handoff(self):
        from tools import ci_cargo_evaluate, run_aot_tests
        invocation = ci_cargo.RECIPES["prepare"][1]
        inventory = self.root / "target/cases-inventory.jsonl"
        raw = stream()
        count = len(run_aot_tests.SUPERVISOR_CASES)
        marker = f"test result: ok. {count} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out"
        records = "\n".join(f"LSF_AOT_CASE {outcome} {name}"
                            for name in sorted(run_aot_tests.SUPERVISOR_CASES)
                            for outcome in ("started", "passed")) + "\n"
        code = ("import os; os.write(1," + repr(raw + marker.encode() + b"\n") + "); "
                "os.write(2," + repr(records.encode() + b"token=private-case-observer-canary\n") + ")")
        destination = self.root / "target/cases-observation"
        with mock.patch.object(observe, "observed_argv", return_value=[sys.executable, "-c", code]), \
             mock.patch.object(observe.TestRun, "source_identity"):
            record = observe.observe(invocation, repo=self.root, output=destination, inventory=inventory, timeout=10)
        self.assertTrue(record["passed"])
        self.assertTrue(record["stageDiagnostic"]["child"]["cleanupAcknowledged"])
        self.assertEqual(len(inventory.read_text().splitlines()), 2)
        self.assertNotIn("LSF_AOT_CASE", inventory.read_text())
        text = ci_cargo_evaluate.execution_text(destination)
        self.assertNotIn("private-case-observer-canary", text)
        run_aot_tests.validate_case_coverage(text, "aot_supervisor")
        observe.ci_cargo.validate_inventory(inventory)


class ProbeArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root / "target"
        artifact = self.target / "debug/deps/libdependency.rlib"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"synthetic-archive-control")
        self.archive = self.root / "cache.tar.gz"

    def test_dependency_only_round_trip_records_actual_local_costs(self):
        saved = probe.save_archive(self.target, self.archive)
        destination = self.root / "restored"
        restored = probe.restore_archive(destination, self.archive, saved["sha256"])
        self.assertEqual((destination / "debug/deps/libdependency.rlib").read_bytes(), b"synthetic-archive-control")
        self.assertEqual(saved["files"], restored["files"])
        self.assertGreater(saved["archiveBytes"], 0)
        self.assertGreaterEqual(restored["seconds"], 0)

    def test_workspace_products_and_links_are_not_saved(self):
        own = self.target / ("debug/deps/lib" + probe.APP.replace("-", "_") + "-123.rlib")
        own.write_bytes(b"workspace")
        with self.assertRaises(ValueError):
            probe.save_archive(self.target, self.archive)
        own.unlink()
        own.symlink_to(self.root / "secret")
        with self.assertRaises(ValueError):
            probe.save_archive(self.target, self.archive)

    def test_corruption_is_rejected_before_extraction(self):
        saved = probe.save_archive(self.target, self.archive)
        self.archive.write_bytes(self.archive.read_bytes()[:20])
        destination = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "integrity"):
            probe.restore_archive(destination, self.archive, saved["sha256"])
        self.assertFalse(destination.exists())

    def test_archive_traversal_and_duplicate_members_fail_before_writes(self):
        for names in (("../escape",), ("debug/deps/a", "debug/deps/a"), ("debug/positive-test-result.json",)):
            with tarfile.open(self.archive, "w:gz") as archive:
                for name in names:
                    info = tarfile.TarInfo(name)
                    info.size = 1
                    archive.addfile(info, io.BytesIO(b"x"))
            digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                probe.restore_archive(self.root / "restored", self.archive, digest)
            self.assertFalse((self.root / "restored").exists())

    def test_archive_expansion_limit_is_checked_before_extraction(self):
        saved = probe.save_archive(self.target, self.archive)
        with mock.patch.object(probe, "ENTRY_LIMIT", 0), self.assertRaises(ValueError):
            probe.restore_archive(self.root / "restored", self.archive, saved["sha256"])
        self.assertFalse((self.root / "restored").exists())


if __name__ == "__main__":
    unittest.main()
