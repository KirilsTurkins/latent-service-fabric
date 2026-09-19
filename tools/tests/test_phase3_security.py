"""Runner contract tests; these do not stand in for the runtime matrix."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr
import copy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools import phase3_security as security
from tools import phase3_security_artifacts as artifacts
from tools import phase3_security_cases as cases
from tools import phase3_security_container as container
from tools import phase3_security_manual as manual
from tools.build_process import BuildProcessError, run_bounded


def completed(stdout=b"", stderr=b""):
    return subprocess.CompletedProcess([], 0, stdout, stderr)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name).resolve()
        self.group = cases.guest("http", (238,), "pr selected_test\nignored fixture_test")
        self.manifest = self.repo / self.group.manifest
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text("[package]\n")
        self.source = self.manifest.parent / self.group.source
        self.source.parent.mkdir()
        self.source.write_text("fn main() {}\n")
        self.executable = self.repo / "target/debug/deps/http-current"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"fixture-binary")
        self.path = self.repo / "inventory.jsonl"
        self.entry = {"reason": "compiler-artifact", "manifest_path": str(self.manifest),
                      "target": {"name": "http", "kind": ["test"], "src_path": str(self.source)},
                      "profile": {"test": True}, "executable": str(self.executable)}

    def save(self, rows=None, finished=True):
        rows = [self.entry] if rows is None else rows
        if finished:
            rows = [*rows, {"reason": "build-finished", "success": True}]
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def read(self):
        return artifacts.read_inventory(self.path, self.repo, (self.group,))

    def test_exact_integration_owner_ignores_stale_executable_neighbours(self):
        self.executable.with_name("http-stale").write_bytes(b"old")
        self.save()
        self.assertEqual(self.read()[self.group.key].executable, self.executable)

    def test_library_and_integration_names_are_not_interchangeable(self):
        wrong = copy.deepcopy(self.entry)
        wrong["target"]["kind"] = ["lib"]
        self.save([wrong])
        with self.assertRaisesRegex(artifacts.SecurityError, "missing-successful"):
            self.read()

    def test_wrong_source_foreign_target_and_duplicate_artifacts_fail_closed(self):
        for field, value in (("src_path", str(self.manifest)), ("name", "other")):
            wrong = copy.deepcopy(self.entry)
            wrong["target"][field] = value
            self.save([wrong])
            with self.subTest(field=field), self.assertRaises(artifacts.SecurityError):
                self.read()
        self.save([self.entry, self.entry])
        with self.assertRaisesRegex(artifacts.SecurityError, "ambiguous"):
            self.read()

    def test_failed_missing_or_nonterminal_build_record_is_not_evidence(self):
        for suffix in ([], [{"reason": "build-finished", "success": False}],
                       [{"reason": "build-finished", "success": True}, {}]):
            self.save([self.entry, *suffix], finished=False)
            with self.subTest(suffix=suffix), self.assertRaises(artifacts.SecurityError):
                self.read()

    def test_non_test_profiles_and_external_executables_are_rejected(self):
        for field, value in (("profile", {"test": 1}), ("executable", str(self.source))):
            wrong = copy.deepcopy(self.entry)
            wrong[field] = value
            self.save([wrong])
            with self.subTest(field=field), self.assertRaises(artifacts.SecurityError):
                self.read()

    def test_duplicate_json_keys_and_inventory_bounds_are_rejected(self):
        self.path.write_text('{"reason":"build-finished","reason":"other"}\n')
        with self.assertRaises(artifacts.ArtifactError):
            self.read()
        self.save()
        for name in ("MAX_LINE_BYTES", "MAX_INVENTORY_BYTES", "MAX_RECORDS"):
            with patch.object(artifacts, name, 1), self.assertRaises(artifacts.SecurityError):
                self.read()

    def test_dynamic_links_stay_inside_the_owned_target_and_are_bounded(self):
        owned = self.repo / "target/debug/build/fixture/out"
        self.save([{"reason": "build-script-executed", "linked_paths": [str(self.repo), f"native={owned}"]},
                   self.entry])
        self.assertEqual(self.read()[self.group.key].link_paths, (owned,))
        self.save([{"reason": "build-script-executed", "linked_paths": ["x"] * 257}, self.entry])
        with self.assertRaisesRegex(artifacts.SecurityError, "link-limit"):
            self.read()

    def test_fixture_identity_is_bounded_nonempty_and_sensitive_to_changed_bytes(self):
        root = self.repo / "fixture"
        root.mkdir()
        with self.assertRaisesRegex(artifacts.SecurityError, "empty"):
            artifacts.tree_identity(root, time.monotonic() + 5)
        payload = root / "public-fixture"
        payload.write_bytes(b"first")
        before = artifacts.tree_identity(root, time.monotonic() + 5)
        payload.write_bytes(b"second")
        self.assertNotEqual(before, artifacts.tree_identity(root, time.monotonic() + 5))
        with self.assertRaisesRegex(artifacts.SecurityError, "file-limit"):
            artifacts.file_identity(payload, time.monotonic() + 5, maximum=1)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.group = cases.guest("http", (238,), "pr first\nignored second")

    def test_exact_listing_and_ignored_classification(self):
        listed = artifacts.listing(b"first: test\nsecond: test\n\n2 tests, 0 benchmarks\n")
        ignored = artifacts.listing(b"second: test\n\n1 test, 0 benchmarks\n")
        artifacts.validate_selection(self.group, listed, ignored)
        for available, disabled in ((listed - {"first"}, ignored), (listed, frozenset()),
                                    (listed, listed), (listed, ignored | {"foreign"})):
            with self.subTest(disabled=disabled), self.assertRaises(artifacts.SecurityError):
                artifacts.validate_selection(self.group, available, disabled)

    def test_empty_listing_duplicates_and_surplus_records_do_not_pass(self):
        for output in (b"", b"first: test\nfirst: test\n2 tests, 0 benchmarks\n",
                       b"first: benchmark\n1 test, 0 benchmarks\n",
                       b"first: test\n0 tests, 0 benchmarks\n",
                       b"0 tests, 0 benchmarks\nfirst: test\n"):
            with self.subTest(output=output), self.assertRaises(artifacts.SecurityError):
                artifacts.listing(output)

    def test_zero_ignored_wrong_name_or_extra_results_are_not_success(self):
        good = (b"running 1 test\ntest first ... ok\n\n"
                b"test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 8 filtered out; finished in 0.01s\n")
        artifacts.validate_result(good, "first")
        for bad in (good.replace(b"1 passed", b"0 passed"), good.replace(b"0 ignored", b"1 ignored"),
                    good.replace(b"test first", b"test other"), good + good,
                    b"test unexpected ... ok\n" + good):
            with self.subTest(bad=bad), self.assertRaises(artifacts.SecurityError):
                artifacts.validate_result(bad, "first")

    def test_custom_harness_never_uses_a_libtest_summary_or_unsupported_host_marker(self):
        marker = "AOT sandbox: exact owned probes passed"
        artifacts.validate_custom((marker + "\n").encode(), marker)
        for output in (b"", b"AOT sandbox: unsupported host rejected as required\n",
                       b"test result: ok. 0 passed\n", (marker + "\nextra\n").encode()):
            with self.assertRaises(artifacts.SecurityError):
                artifacts.validate_custom(output, marker)

    def test_matrix_has_fixed_pr_inventory_and_manual_superset(self):
        security.check_matrix()
        self.assertEqual(sum(case.pr for group in cases.GROUPS for case in group.cases), 27)
        self.assertEqual(sum(len(group.cases) for group in cases.selected("manual")), 184)
        self.assertTrue(set(cases.selected("pr")).issubset(cases.selected("manual")))
        self.assertEqual(sum(group.marker is not None for group in cases.GROUPS), 2)

    def test_duplicate_selection_is_not_hidden_by_a_set(self):
        with patch.object(security, "GROUPS", (self.group, replace(self.group, key="duplicate"))):
            with self.assertRaisesRegex(artifacts.SecurityError, "duplicate-case"):
                security.check_matrix()

    def test_original_deadline_and_capture_bound_reach_the_existing_owner(self):
        runner = security.Runner(Path.cwd(), "pr")
        runner.deadline = 100
        with patch.object(security.time, "monotonic", side_effect=[90, 96]), \
                patch.object(security, "run_bounded", return_value=completed()) as owned:
            runner.command(["fixture"], maximum=512)
            runner.command(["fixture"], maximum=512)
        self.assertEqual([entry.kwargs["timeout_seconds"] for entry in owned.call_args_list], [10, 4])
        self.assertTrue(all(entry.kwargs["max_output_bytes"] == 512 for entry in owned.call_args_list))

    def test_source_mismatch_or_dirty_checkout_cannot_report_current_head(self):
        runner = Mock()
        runner.repo = Path.cwd()
        for outputs in ([completed(b"b" * 40 + b"\n")],
                        [completed(b"a" * 40 + b"\n"), completed(b" M source\n")]):
            runner.command.side_effect = outputs
            with self.assertRaises(artifacts.SecurityError):
                security.verify_source(runner, "a" * 40)


class WorkflowTests(unittest.TestCase):
    def report(self):
        return {"schemaVersion": "fixture", "passed": True, "temporaryOutputsRemoved": True,
                "shutdown": [{"reaped": True, "record": {"event": "stopped", "clean": True,
                                                          "report": {"clean": True}}}] * 2}

    def test_workflow_receipts_need_two_reaped_clean_real_nodes(self):
        value = self.report()
        self.assertEqual(manual.validate_workflow(value, "publication", "fixture")["nodeShutdowns"], 2)
        for field, replacement in (("passed", False), ("shutdown", []), ("temporaryOutputsRemoved", False)):
            with self.subTest(field=field), self.assertRaises(artifacts.SecurityError):
                manual.validate_workflow({**value, field: replacement}, "publication", "fixture")
        value["shutdown"][0]["reaped"] = False
        with self.assertRaisesRegex(artifacts.SecurityError, "owner-retained"):
            manual.validate_workflow(value, "publication", "fixture")

    def test_provider_workflow_is_validated_without_inventing_its_absent_pass_flag(self):
        value = self.report()
        del value["passed"]
        del value["temporaryOutputsRemoved"]
        value.update({"grantsRevoked": True, "selectedRevisionPreservedAcrossRestart": True,
                      "angularT1Qualified": False, "activations": ["fixture"] * 9,
                      "upstream": {"requests": 4, "authorized": 4, "unexpected": 0}})
        manual.validate_workflow(value, "provider-management", "fixture")
        value["upstream"]["unexpected"] = 1
        with self.assertRaisesRegex(artifacts.SecurityError, "provider-workflow-proof"):
            manual.validate_workflow(value, "provider-management", "fixture")

    def test_raw_failure_text_is_never_returned_by_the_cli(self):
        diagnostic = io.StringIO()
        with patch.object(security, "run", side_effect=ValueError("credential-fixture-never-log")), \
                redirect_stderr(diagnostic):
            status = security.main(["--inventory", "missing", "--source-commit", "a" * 40])
        self.assertEqual(status, 1)
        self.assertNotIn("credential-fixture", diagnostic.getvalue())
        self.assertIn("fixture-or-process-error", diagnostic.getvalue())


class ContainerTests(unittest.TestCase):
    def fixture(self):
        return {"Id": "a" * 64, "Image": "sha256:" + "b" * 64,
                "Config": {"Labels": {container.LABEL: "owned-fixture"}}, "State": {"Running": True},
                "HostConfig": {"Init": True, "AutoRemove": False, "Memory": 1024**3,
                               "NanoCpus": 1_000_000_000, "PidsLimit": 256, "NetworkMode": "bridge"},
                "Mounts": [{"Type": "bind", "Destination": "/workspace", "Source": str(container.ROOT)}]}

    def test_unlabelled_unbounded_or_foreign_workspaces_are_not_owned(self):
        value = self.fixture()
        self.assertEqual(container.owned_container(value, "owned-fixture"), value["Id"])
        for field, replacement in (("Memory", 0), ("PidsLimit", -1), ("Privileged", True),
                                   ("NetworkMode", "host"), ("Init", False), ("AutoRemove", True)):
            wrong = copy.deepcopy(value)
            wrong["HostConfig"][field] = replacement
            with self.subTest(field=field), self.assertRaises(artifacts.SecurityError):
                container.owned_container(wrong, "owned-fixture")
        with self.assertRaisesRegex(artifacts.SecurityError, "not-owned"):
            container.owned_container(value, "another-owner")
        value["Mounts"][0]["Source"] = str(container.ROOT.parent)
        with self.assertRaisesRegex(artifacts.SecurityError, "workspace-owner"):
            container.owned_container(value, "owned-fixture")

    def test_failed_inner_process_still_stops_only_the_preverified_container_id(self):
        before = self.fixture()
        after = copy.deepcopy(before)
        after["State"]["Running"] = False
        args = argparse.Namespace(container="named-fixture", owner="owned-fixture",
                                  arguments=["--inventory", "/workspace/target/current.jsonl"])
        with patch.object(container, "inspect", side_effect=[before, after]), \
                patch.object(container, "command", side_effect=[BuildProcessError("command-deadline"), completed()]) as call:
            with self.assertRaisesRegex(BuildProcessError, "command-deadline"):
                container.run(args)
        self.assertEqual(call.call_args_list[-1].args[0], ["stop", "--timeout", "5", before["Id"]])

    def test_unowned_container_is_not_started_stopped_or_removed(self):
        args = argparse.Namespace(container="parent", owner="wrong-owner", arguments=["--inventory", "x"])
        with patch.object(container, "inspect", return_value=self.fixture()), \
                patch.object(container, "command") as call:
            with self.assertRaises(artifacts.SecurityError):
                container.run(args)
        call.assert_not_called()


@unittest.skipUnless(sys.platform == "linux" and sys.version_info >= (3, 13), "Linux owned-process fixture")
class ProcessTests(unittest.TestCase):
    def test_timed_out_process_group_retires_the_observed_real_descendant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "ready.pid"
            child = ("import os,time;from pathlib import Path;"
                     f"Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(30)")
            parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)"
            with self.assertRaisesRegex(BuildProcessError, "command-deadline"):
                run_bounded([sys.executable, "-c", parent], root, dict(os.environ),
                            timeout_seconds=2, max_output_bytes=1024)
            self.assertTrue(marker.is_file(), "descendant itself reached the readiness checkpoint")
            process = Path("/proc") / marker.read_text() / "stat"
            if process.exists():
                self.assertIn(process.read_bytes().rpartition(b") ")[2].split()[0], (b"Z", b"X"))


if __name__ == "__main__":
    unittest.main()
