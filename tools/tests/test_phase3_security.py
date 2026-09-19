"""Runner contract tests; these do not stand in for the runtime matrix."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
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

    def test_supervisor_requires_both_exact_completion_records_in_order(self):
        readiness = "isolated AOT readiness: six bounded success/rejection/reap scenarios passed"
        ownership = "isolated AOT supervisor: 16 bounded protocol/ownership scenarios passed"
        marker = readiness + "\n" + ownership
        group = next(group for group in cases.GROUPS if group.key == "compiler-supervisor")
        self.assertEqual(group.marker, marker)
        artifacts.validate_custom((marker + "\n").encode(), marker)
        for output in (readiness, ownership, ownership + "\n" + readiness,
                       readiness + "\n" + marker, marker + "\nextra", marker + "\n" + ownership):
            with self.subTest(output=output), self.assertRaises(artifacts.SecurityError):
                artifacts.validate_custom((output + "\n").encode(), marker)
        for invalid in ("", readiness + "\n", marker + "\nextra"):
            with self.subTest(marker=invalid), self.assertRaisesRegex(artifacts.SecurityError, "marker"):
                artifacts.validate_custom(b"", invalid)

    def test_inherited_child_output_must_match_one_exact_bounded_receipt(self):
        record = b'{"controlled":true}'
        output = (b"running 1 test\ntest first ... " + record + b"\nok\n\n"
                  b"test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 8 filtered out; finished in 3.04s\n")
        with self.assertRaisesRegex(artifacts.SecurityError, "missing-exact"):
            artifacts.validate_result(output, "first")
        artifacts.validate_result(output, "first", emitted_record=record)
        for invalid in (output.replace(record, b'{"controlled":false}'), output + record,
                        output.replace(b"\nok\n", b"\nignored\n"), output.replace(b"1 passed", b"0 passed"),
                        b"test unexpected ... ok\n" + output):
            with self.subTest(invalid=invalid), self.assertRaises(artifacts.SecurityError):
                artifacts.validate_result(invalid, "first", emitted_record=record)
        for invalid in (b"", record + b"\n", b"x" * 4097):
            with self.assertRaises(artifacts.SecurityError):
                artifacts.validate_result(output, "first", emitted_record=invalid)

    def test_matrix_has_fixed_pr_inventory_and_manual_superset(self):
        security.check_matrix()
        self.assertEqual(sum(case.pr for group in cases.GROUPS for case in group.cases), 27)
        self.assertEqual(sum(len(group.cases) for group in cases.selected("manual")), 186)
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

    def test_negative_receipt_separates_validated_active_and_unexecuted_cases(self):
        runner = security.Runner(Path.cwd(), "manual")
        first, second = cases.GROUPS[:2]
        runner.validated_cases.append(first.key + ":" + first.cases[0].name)
        runner.active_case = second.key + ":" + second.cases[0].name
        runner.active_case_completed = True
        runner.current = runner.active_case
        arguments = argparse.Namespace(profile="manual", source_commit="a" * 40, container_owner="owned-fixture")
        report = security.failure_report(arguments, runner, artifacts.SecurityError("test-result-count"))
        self.assertIs(report["passed"], False)
        self.assertIs(report["activeCaseCommandAccepted"], True)
        self.assertEqual(report["validatedCases"], runner.validated_cases)
        self.assertEqual(report["activeCase"], runner.active_case)
        self.assertEqual(len(report["notExecutedCases"]), 186)
        self.assertNotIn(runner.active_case, report["notExecutedCases"])
        self.assertNotIn(runner.validated_cases[0], report["notExecutedCases"])
        self.assertEqual(report["notExecutedWorkflows"],
                         ["publication", "security-profile", "provider-management", "angular-t1"])

    def test_private_envelope_keeps_failures_explicit_and_diagnostics_redacted(self):
        output = io.StringIO()
        with patch.object(security, "run", side_effect=ValueError("credential-fixture")), redirect_stdout(output):
            security.container_entry(["--profile", "manual", "--inventory", "unused",
                                      "--source-commit", "a" * 40, "--container-owner", "owned-fixture"])
        report = json.loads(output.getvalue())
        self.assertEqual(report["schemaVersion"], "latent.phase3.security.failure.v1")
        self.assertIs(report["passed"], False)
        self.assertEqual(report["validatedCases"], [])
        self.assertEqual(len(report["notExecutedCases"]), 188)
        self.assertEqual(report["classification"], "fixture-or-process-error")
        self.assertNotIn("credential-fixture", output.getvalue())


class WorkflowTests(unittest.TestCase):
    def report(self, node_shutdowns=2):
        return {"schemaVersion": "fixture", "passed": True, "temporaryOutputsRemoved": True,
                "shutdown": [{"reaped": True, "record": {"event": "stopped", "clean": True,
                                                          "report": {"clean": True}}}] * node_shutdowns}

    def test_workflow_receipts_need_the_exact_reaped_clean_node_lifetimes(self):
        for name, node_shutdowns in (("publication", 3), ("security-profile", 2)):
            value = self.report(node_shutdowns)
            self.assertEqual(manual.validate_workflow(value, name, "fixture")["nodeShutdowns"], node_shutdowns)
            for count in (0, node_shutdowns - 1, node_shutdowns + 1):
                with self.subTest(name=name, count=count), self.assertRaisesRegex(artifacts.SecurityError, "shutdown-count"):
                    manual.validate_workflow(self.report(count), name, "fixture")
            for field, replacement in (("passed", False), ("temporaryOutputsRemoved", False)):
                with self.subTest(name=name, field=field), self.assertRaises(artifacts.SecurityError):
                    manual.validate_workflow({**value, field: replacement}, name, "fixture")
            value["shutdown"][0]["reaped"] = False
            with self.assertRaisesRegex(artifacts.SecurityError, "owner-retained"):
                manual.validate_workflow(value, name, "fixture")

    def test_unknown_workflow_cannot_claim_a_shutdown_profile(self):
        with self.assertRaisesRegex(artifacts.SecurityError, "workflow-name"):
            manual.validate_workflow(self.report(), "unexpected", "fixture")

    def angular_report(self):
        value = self.report()
        value.update({"actualAngularBuild": True, "reproducibility": "not-checked",
                      "buildObservationDigest": "sha256:" + "a" * 64,
                      "nativeCacheFilesUnchangedOnRestart": True,
                      "preRestartNativeCacheHitHighWatermark": "19",
                      "authenticatedNativeCacheHits": [{"sequence": "35"}],
                      "cancellations": [{"disconnect": False, "terminal": "cancelled"},
                                        {"disconnect": True, "terminal": "cancelled"}],
                      "profile": {"profile": "external-capsule-v1", "threatClass": "T1",
                                  "admission": "enforced", "protectedCredentialFile": True,
                                  "compiler": "isolated-aot-compiler-v1", "authenticatedNativeLoading": True}})
        return value

    def test_actual_angular_requires_protected_t1_not_a_t0_or_partial_receipt(self):
        value = self.angular_report()
        summary = manual.validate_workflow(value, "angular-t1", "fixture")
        self.assertEqual(summary["nodeShutdowns"], 2)
        self.assertEqual(summary["qualification"]["buildObservationDigest"], value["buildObservationDigest"])
        for field, replacement in (("profile", "local-experimental-v1"), ("threatClass", "T0"),
                                   ("admission", "trusted-local"), ("protectedCredentialFile", False),
                                   ("compiler", "in-process"), ("authenticatedNativeLoading", False)):
            wrong = copy.deepcopy(value)
            wrong["profile"][field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(artifacts.SecurityError, "angular-t1-profile"):
                manual.validate_workflow(wrong, "angular-t1", "fixture")
        for field, replacement in (("actualAngularBuild", False), ("buildObservationDigest", "not-observed"),
                                   ("nativeCacheFilesUnchangedOnRestart", False), ("passed", False),
                                   ("temporaryOutputsRemoved", False), ("shutdown", [])):
            with self.subTest(field=field), self.assertRaises(artifacts.SecurityError):
                manual.validate_workflow({**value, field: replacement}, "angular-t1", "fixture")

    def test_angular_restart_requires_new_hits_and_both_cancelled_owners(self):
        value = self.angular_report()
        for sequence in ("18", "19", "-1", "1" * 21, True):
            wrong = {**value, "authenticatedNativeCacheHits": [{"sequence": sequence}]}
            with self.subTest(sequence=sequence), self.assertRaisesRegex(artifacts.SecurityError, "restart-cache"):
                manual.validate_workflow(wrong, "angular-t1", "fixture")
        for field, replacement in (("authenticatedNativeCacheHits", []),
                                   ("preRestartNativeCacheHitHighWatermark", None)):
            with self.subTest(field=field), self.assertRaisesRegex(artifacts.SecurityError, "restart-cache"):
                manual.validate_workflow({**value, field: replacement}, "angular-t1", "fixture")
        for cancellations in ([], value["cancellations"][:1], value["cancellations"][::-1],
                              [{"disconnect": False, "terminal": "running"}, value["cancellations"][1]]):
            with self.subTest(cancellations=cancellations), self.assertRaisesRegex(artifacts.SecurityError, "cancellation"):
                manual.validate_workflow({**value, "cancellations": cancellations}, "angular-t1", "fixture")

    def test_ci_runs_the_exact_current_inventory_and_retains_its_receipt(self):
        workflow = (security.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        command = ('python3 tools/phase3_security.py --profile pr --inventory "$RUNNER_TEMP/lsf-workspace-tests.jsonl" '
                   '--source-commit "$GITHUB_SHA" --output target/phase3-security/pr-receipt.json')
        self.assertEqual(workflow.count(command), 1)
        self.assertLess(workflow.index("Build workspace binaries and test harnesses"), workflow.index(command))
        self.assertIn("name: phase3-security-pr-${{ github.sha }}", workflow)
        self.assertIn("path: target/phase3-security/pr-receipt.json", workflow)

    def test_provider_workflow_is_validated_without_inventing_its_absent_pass_flag(self):
        value = self.report()
        del value["passed"]
        del value["temporaryOutputsRemoved"]
        value.update({"grantsRevoked": True, "selectedRevisionPreservedAcrossRestart": True,
                      "angularT1Qualified": False, "activations": ["fixture"] * 9,
                      "upstream": {"requests": 4, "authorized": 4, "unexpected": 0}})
        manual.validate_workflow(value, "provider-management", "fixture")
        for count in (1, 3):
            with self.subTest(count=count), self.assertRaisesRegex(artifacts.SecurityError, "shutdown-count"):
                manual.validate_workflow({**value, "shutdown": self.report(count)["shutdown"]},
                                         "provider-management", "fixture")
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

    def test_mutated_manual_binary_prevents_a_final_fixture_identity_claim(self):
        arguments = argparse.Namespace(cli=Path("approved-cli"))
        runner = Mock(deadline=time.monotonic() + 5)
        with patch.object(manual, "file_identity", return_value={"sha256": "new"}):
            with self.assertRaisesRegex(artifacts.SecurityError, "manual-input-changed"):
                manual.verify_inputs(arguments, runner, {"cli": {"sha256": "old"}})

    def test_browser_receipt_requires_real_observations_without_a_component_claim(self):
        report = {"browser": "153.0.8010.47", "liveSharedIngress": True, "controlledNodeSsr": True,
                  "componentRenderClaimed": False, "originalDomReused": True, "navigationHydrated": True,
                  "escapedDataRoundTrip": True, "inlineAndRemoteScriptsBlocked": True,
                  "baseOverrideBlocked": True, "wrongScriptMimeBlocked": True,
                  "sameOriginPostReachedMethodPolicy": True, "errors": 0,
                  "publicApplicationQualified": False, "applicationComponentInvoked": False,
                  "managementRpcAbsent": False, "browserFetchCredentialsOmitted": False,
                  "cookiesDoNotAuthenticate": False}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "browser/browser-receipt.json"
            path.parent.mkdir()
            raw = json.dumps(report, separators=(",", ":")).encode()
            path.write_bytes(raw)
            self.assertEqual(manual.browser_output(directory, time.monotonic() + 5), raw)
            for changed in ({"componentRenderClaimed": True}, {"errors": False}, {"originalDomReused": 1},
                            {"navigationHydrated": False}, {"browser": "opaque-text"}, {"extra": True},
                            {"publicApplicationQualified": True}, {"applicationComponentInvoked": True},
                            {"browserFetchCredentialsOmitted": 0}):
                path.write_text(json.dumps({**report, **changed}))
                with self.subTest(changed=changed), self.assertRaises(artifacts.SecurityError):
                    manual.browser_output(directory, time.monotonic() + 5)
            path.write_bytes(raw[:-1] + b',"errors":0}')
            with self.assertRaises(artifacts.ArtifactError):
                manual.browser_output(directory, time.monotonic() + 5)
            path.write_bytes(b"x" * 4097)
            with self.assertRaisesRegex(artifacts.SecurityError, "file-limit"):
                manual.browser_output(directory, time.monotonic() + 5)

    def test_public_browser_application_cannot_reuse_assets_only_observations(self):
        report = {"browser": "153.0.8010.47", "liveSharedIngress": True, "controlledNodeSsr": True,
                  "componentRenderClaimed": False, "originalDomReused": True, "navigationHydrated": True,
                  "escapedDataRoundTrip": True, "inlineAndRemoteScriptsBlocked": True,
                  "baseOverrideBlocked": True, "wrongScriptMimeBlocked": True,
                  "sameOriginPostReachedMethodPolicy": True, "errors": 0,
                  "publicApplicationQualified": True, "applicationComponentInvoked": True,
                  "managementRpcAbsent": True, "browserFetchCredentialsOmitted": True,
                  "cookiesDoNotAuthenticate": True}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "browser/browser-application-receipt.json"
            path.parent.mkdir()
            raw = json.dumps(report, separators=(",", ":")).encode()
            path.write_bytes(raw)
            self.assertEqual(manual.browser_output(directory, time.monotonic() + 5, application=True), raw)
            for field in ("publicApplicationQualified", "applicationComponentInvoked", "managementRpcAbsent",
                          "browserFetchCredentialsOmitted", "cookiesDoNotAuthenticate"):
                path.write_text(json.dumps({**report, field: False}))
                with self.subTest(field=field), self.assertRaises(artifacts.SecurityError):
                    manual.browser_output(directory, time.monotonic() + 5, application=True)


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

    def test_negative_inner_receipt_stops_the_container_and_exits_nonzero(self):
        before = self.fixture()
        after = copy.deepcopy(before)
        after["State"]["Running"] = False
        report = {"schemaVersion": "latent.phase3.security.failure.v1", "profile": "manual", "passed": False,
                  "enclosingContainerStopRequired": True, "enclosingContainerOwner": "owned-fixture",
                  "failedStage": "selected:case", "classification": "test-result-count"}
        args = argparse.Namespace(container="named-fixture", owner="owned-fixture", arguments=["--inventory", "unused"])
        with patch.object(container, "inspect", side_effect=[before, after]), \
                patch.object(container, "command", side_effect=[completed(json.dumps(report).encode()), completed()]):
            result = container.run(args)
        self.assertIs(result["passed"], False)
        self.assertIs(result["enclosingContainer"]["stopped"], True)
        self.assertIs(result["enclosingContainerStopRequired"], False)
        with patch.object(container, "run", return_value=result), redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()) as diagnostic:
            status = container.main(["--container", "named-fixture", "--owner", "owned-fixture", "--", "unused"])
        self.assertEqual(status, 1)
        self.assertIn("selected:case: test-result-count", diagnostic.getvalue())

    def test_false_failure_schema_cannot_be_coerced_into_a_success(self):
        before = self.fixture()
        after = copy.deepcopy(before)
        after["State"]["Running"] = False
        report = {"schemaVersion": "latent.phase3.security.failure.v1", "profile": "manual", "passed": True,
                  "enclosingContainerStopRequired": True, "enclosingContainerOwner": "owned-fixture",
                  "failedStage": "selected:case", "classification": "test-result-count"}
        args = argparse.Namespace(container="named-fixture", owner="owned-fixture", arguments=["--inventory", "unused"])
        with patch.object(container, "inspect", side_effect=[before, after]), \
                patch.object(container, "command", side_effect=[completed(json.dumps(report).encode()), completed()]):
            with self.assertRaisesRegex(artifacts.SecurityError, "container-failure-receipt"):
                container.run(args)

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
