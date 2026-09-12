"""Offline profile/receipt/ownership checks; no node, compiler or network."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import phase2_gate_resource as workflow
from tools.phase2_gate_resource import SOURCE_FILES
from tools.phase2_gate_resource_os import fixture_inventory
from tools.phase2_gate_resource_profile import (
    FIXED_LIVE_ROWS, FIXED_RUNTIME_ROWS, FIXED_UNKNOWN_ROWS,
    OBSERVATION_ROWS, PHASES, PROFILE, ZERO_ROWS, configuration, digest, integer,
    quiet, shutdown_report, validate_receipt,
)
from tools.phase2_gate_resource_run import BoundedClient
from tools.phase2_operator_process import WorkflowError


def complete_inventory(phase="baseline"):
    rows = [{"name": name, "kind": "test", "ownership": "activation-scoped",
             "configuredCount": "1", "activeCount": "0", "attributes": {}}
            for name in ZERO_ROWS]
    rows += [{"name": name, "kind": "test", "ownership": "node-fixed",
              "configuredCount": "4", "activeCount": "1", "attributes": {}}
             for name in OBSERVATION_ROWS]
    rows += [{"name": name, "kind": "test", "ownership": "node-fixed",
              "configuredCount": "2" if name in FIXED_RUNTIME_ROWS else "1",
              "activeCount": None if name in FIXED_UNKNOWN_ROWS else "1", "attributes": {}}
             for name in FIXED_LIVE_ROWS + FIXED_RUNTIME_ROWS + FIXED_UNKNOWN_ROWS]
    warm = phase in ("baseline", "dormant")
    return {
        "queueDepth": "0", "routeGeneration": "2" if phase == "baseline" else
            "33" if phase == "unrouted" else "17",
        "cellCapacity": [{"observationAvailable": True, "total": 1, "active": 0,
                          "quarantined": 0, "queueDepth": 0, "queuedTenants": 0,
                          "granted": "2" if warm else "32"}],
        "topology": {"available": True, "complete": True, "entries": rows},
        "cacheSummary": {"available": True, "entries": "2", "maximumEntries": "2",
                         "preparing": "0", "preparingSourceBytes": "0", "preparingMetadataBytes": "0",
                         "sourceBytes": "1024", "maximumSourceBytes": "2048",
                         "metadataBytes": "1024", "maximumMetadataBytes": "2048",
                         "compiledImageBytes": "1024", "maximumCompiledImageBytes": "2048",
                         "misses": "2", "hits": "0" if warm else "30"},
        "quotas": {"usage": {"activeActivations": 0, "queuedActivations": 0,
                            "reservedCpuFuel": "0", "reservedMemoryBytes": "0"}},
    }


def complete_shutdown():
    value = dict.fromkeys((
        "activeConnections", "activeRpcs", "activeControlJobs", "activeActivations",
        "cancellationRegistrations", "observerCorrelations", "quotaReservations",
        "queuedReservations", "reservedCpuFuel", "reservedMemoryBytes", "activeLeases",
        "queuedActivations", "quarantinedCells", "activeBackendInvocations",
        "instanceReservations", "preparingComponents", "preparingSourceBytes",
        "preparingMetadataBytes", "liveStores", "liveHostStates", "liveInstances",
        "liveTemporaryBuffers", "liveCancellationProbes"), 0)
    value.update(clean=True, telemetryFlushed=True, epochHelperJoined=True)
    value["compiler"] = dict.fromkeys((
        "assigned_jobs", "running_jobs", "queued_jobs", "waiting_callers", "ready_preparations",
        "ready_metadata_bytes", "ready_compiled_image_bytes", "reserved_document_bytes", "workers_live"), 0)
    value["compiler"].update(accepting=False, failed=False, maximum_workers=1, workers_joined=1,
                              workers_quiescent=1, jobs_started=2, jobs_completed=2,
                              jobs_failed=0, jobs_abandoned=0)
    value["cleanup"] = dict(driverJoined=True, driverAlive=False, accepting=False,
                            failed=False, reserved=0, queued=0, running=0,
                            timedOut=0, panicked=0, fallbacks=0, handoffs=0, completed=0)
    value["audit"] = dict(workerJoined=True, recoveryPending=False, queuedOperations=0,
                          queryOwners=0, queryBytes=0, pendingAttempts=0, reservedRecords=0, stageBytes=0)
    value["rollouts"] = dict(workerJoined=True, workerLive=False, failed=False, queuedCommands=0,
                             activeCommands=0, retainedRequestBytes=0, responseOwners=0, responseBytes=0,
                             canary=dict(retainedWindows=0, retainedSamples=0, liveSamples=0, snapshotOwners=0))
    return value


def complete_receipt():
    identity = "sha256:" + "1" * 64
    config = configuration("tests")
    config_digest = digest(config)
    config["credentials"] = [{key: value for key, value in row.items() if key != "token"}
                             for row in config["credentials"]]
    packages = [{"name": f"capsule-{i:02}", "componentDigest": f"sha256:{i:064x}",
                 "packageDigest": f"sha256:{i + 32:064x}", "manifestDigest": f"sha256:{i + 32:064x}"}
                for i in range(32)]
    return {
        "schemaVersion": "latent.phase2.resource-receipt.v1", "profile": copy.deepcopy(PROFILE),
        "profileDigest": digest(PROFILE), "passed": True, "syntheticTestEvidence": True,
        "build": dict(schemaVersion="latent.phase2.resource-build.v1", sourceRevision="1" * 40,
                      cargoLockSha256=identity, cliSha256=identity, nodeSha256=identity,
                      rustcVersion="rustc 1.95.0", buildProfile="debug"),
        "collectorSources": [{"path": name, "digest": identity} for name in SOURCE_FILES],
        "configuration": config, "configurationDigest": config_digest,
        "fixtureInventoryDigest": identity, "fixtureMetadataDigest": identity, "policyFileDigest": identity,
        "host": {"system": "Linux", "pageSize": "4096", "clockTicks": "100"},
        "controls": 150, "invokeAttempts": 32, "elapsedMillis": "120000",
        "packages": packages,
        "invocations": [{"releaseDigest": packages[i % 2]["componentDigest"],
                         "routeGeneration": str(i + 1) if i < 2 else "17"}
                        for i in range(32)],
        "samples": [{"phase": phase, "inventory": complete_inventory(phase), "os": {
            "processId": 42, "startTimeTicks": "100", "observedMonotonicNanos": str(1000000000 + i * 60000000),
            "rssBytes": str(1000000 + i * 4096), "kernelHighWaterRssBytes": str(2000000 + i * 4096),
            "cpuUserTicks": "10", "cpuSystemTicks": "10", "readBytes": "1024", "writeBytes": "2048",
            "threads": 8, "tasks": 8, "fdCount": 12, "socketCount": 3,
            "listeningTcpSockets": 1, "descendants": 0, "procBytesRead": 512}}
            for i, phase in enumerate(phase for phase in PHASES for _ in range(3))],
        "catalog": {"peakReleases": 32, "peakDeployments": 16,
                    "remainingDeployments": 0, "retainedReleases": 32,
                    "dormantRouteGeneration": "17", "unroutedGeneration": "33"},
        "process": {"processId": 42, "startTimeTicks": "100", "executableDigest": identity,
                    "ownedProcessGroup": 42, "exitedSuccessfully": True, "reapedByOwner": True},
        "shutdown": complete_shutdown(), "temporaryOutputsRemoved": True,
    }


class Phase2ResourceTests(unittest.TestCase):
    def test_exact_profile_is_frozen_and_retained_config_excludes_token(self):
        receipt = complete_receipt()
        validate_receipt(receipt)
        self.assertNotIn("token", receipt["configuration"]["credentials"][0])
        receipt["profile"]["releases"] = 33
        receipt["profileDigest"] = digest(receipt["profile"])
        with self.assertRaisesRegex(WorkflowError, "receipt-profile"):
            validate_receipt(receipt)

    def test_rss_growth_is_reported_but_active_ownership_fails(self):
        receipt = complete_receipt()
        receipt["samples"][-1]["os"]["rssBytes"] = str(2**54 + 1)
        validate_receipt(receipt)
        self.assertEqual(integer(receipt["samples"][-1]["os"]["rssBytes"]), 2**54 + 1)
        receipt["samples"][-1]["inventory"]["topology"]["entries"][0]["activeCount"] = "1"
        with self.assertRaisesRegex(WorkflowError, "receipt-active-inventory"):
            validate_receipt(receipt)

    def test_unavailable_or_missing_observation_never_becomes_zero(self):
        for change in ("incomplete", "missing", "unknown"):
            value = complete_inventory()
            if change == "incomplete":
                value["topology"]["complete"] = False
            elif change == "missing":
                value["topology"]["entries"].pop(0)
            else:
                value["topology"]["entries"][0]["activeCount"] = None
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                quiet(value)

    def test_own_observer_slot_is_bounded_and_no_capacity_change_allowed(self):
        value = complete_inventory()
        self.assertTrue(quiet(value))
        row = next(row for row in value["topology"]["entries"] if row["name"] == "control-jobs")
        row["activeCount"] = "2"
        self.assertFalse(quiet(value))
        row["activeCount"] = "5"
        with self.assertRaisesRegex(WorkflowError, "inventory-resource-limit"):
            quiet(value)

    def test_os_growth_process_replacement_and_extra_compilation_fail(self):
        for field, altered in (("threads", 9), ("fdCount", 13), ("socketCount", 4),
                               ("listeningTcpSockets", 2), ("descendants", 1),
                               ("processId", 43), ("startTimeTicks", "101")):
            value = complete_receipt()
            value["samples"][6]["os"][field] = altered
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                validate_receipt(value)
        value = complete_receipt()
        value["samples"][3]["inventory"]["cacheSummary"]["misses"] = "3"
        with self.assertRaisesRegex(WorkflowError, "receipt-unexpected-preparation"):
            validate_receipt(value)

    def test_missing_sample_wrong_phase_and_wrong_component_fail(self):
        value = complete_receipt()
        value["samples"].pop()
        with self.assertRaisesRegex(WorkflowError, "receipt-samples"):
            validate_receipt(value)
        value = complete_receipt()
        value["samples"][3]["phase"] = "baseline"
        with self.assertRaisesRegex(WorkflowError, "receipt-samples"):
            validate_receipt(value)
        value = complete_receipt()
        value["invocations"][20]["releaseDigest"] = value["packages"][2]["componentDigest"]
        with self.assertRaisesRegex(WorkflowError, "receipt-invocations"):
            validate_receipt(value)

    def test_signal_or_exit_without_actual_reap_is_not_cleanup(self):
        value = complete_receipt()
        value["process"]["reapedByOwner"] = False
        with self.assertRaisesRegex(WorkflowError, "receipt-reap"):
            validate_receipt(value)
        for section, field, altered in (
            ("compiler", "workers_joined", 0), ("compiler", "ready_preparations", 1),
            ("cleanup", "driverJoined", False), ("audit", "pendingAttempts", 1),
            ("rollouts", "workerLive", True)):
            report = complete_shutdown()
            report[section][field] = altered
            with self.subTest(section=section, field=field), self.assertRaises(WorkflowError):
                shutdown_report(report)

    def test_request_reservation_precedes_shared_process_call(self):
        client = BoundedClient(Path("/cli"), Path("/client"), None, 0)
        with patch("tools.phase2_operator_process.Client.call", return_value={}) as call:
            for _ in range(32):
                client.call("invoke")
            with self.assertRaisesRegex(WorkflowError, "invoke-budget"):
                client.call("invoke")
            self.assertEqual(call.call_count, 32)
            for _ in range(256):
                client.call("node", "get", "id")
            with self.assertRaisesRegex(WorkflowError, "control-budget"):
                client.call("node", "get", "id")
            self.assertEqual(call.call_count, 288)

    def test_fixture_inventory_is_bounded_and_compares_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "manifest.json"
            source.write_bytes(b"{}")
            first = fixture_inventory(root)
            source.write_bytes(b"{ }")
            self.assertNotEqual(first, fixture_inventory(root))
            with (root / "oversize").open("wb") as target:
                target.truncate(PROFILE["maximumFixtureBytes"] + 1)
            with self.assertRaisesRegex(WorkflowError, "fixture-byte-bound"):
                fixture_inventory(root)

    def test_receipt_requires_build_identity_and_bounded_counter_shape(self):
        value = complete_receipt()
        value["build"]["nodeSha256"] = "unknown"
        with self.assertRaisesRegex(WorkflowError, "identity-digest"):
            validate_receipt(value)
        for value in (True, -1, 1.5, "01", str(2**64)):
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                integer(value)

    def test_consistently_missing_fixed_owner_rows_cannot_fake_complete_topology(self):
        value = complete_receipt()
        for sample in value["samples"]:
            sample["inventory"]["topology"]["entries"] = [
                row for row in sample["inventory"]["topology"]["entries"]
                if row["name"] != "wasmtime-compiler"]
        with self.assertRaisesRegex(WorkflowError, "inventory-fixed-rows"):
            validate_receipt(value)
        value = complete_receipt()
        for sample in value["samples"]:
            next(row for row in sample["inventory"]["topology"]["entries"]
                 if row["name"] == "rollout-coordinator")["activeCount"] = None
        with self.assertRaisesRegex(WorkflowError, "inventory-fixed-unavailable"):
            validate_receipt(value)

    def test_duplicate_or_reordered_os_observations_and_counter_regression_fail(self):
        for field, number in (("observedMonotonicNanos", "1000000000"),
                              ("cpuUserTicks", "9"), ("writeBytes", "0")):
            value = complete_receipt()
            value["samples"][5]["os"][field] = number
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                validate_receipt(value)

    def test_phase_counts_require_real_warm_and_cohort_progress(self):
        for target, field, altered in (("cell", "granted", "2"), ("cache", "hits", "0"),
                                       ("route", "routeGeneration", "2")):
            value = complete_receipt()
            sample = value["samples"][6]["inventory"]
            record = sample["cellCapacity"][0] if target == "cell" else \
                sample["cacheSummary"] if target == "cache" else sample
            record[field] = altered
            with self.subTest(target=target), self.assertRaises(WorkflowError):
                validate_receipt(value)
        value = complete_receipt()
        for sample in value["samples"]:
            sample["inventory"]["cacheSummary"]["misses"] = "0"
        with self.assertRaisesRegex(WorkflowError, "receipt-warm-preparations"):
            validate_receipt(value)
        value = complete_receipt()
        value["shutdown"]["compiler"]["jobs_started"] = 3
        with self.assertRaisesRegex(WorkflowError, "receipt-compiler-work"):
            validate_receipt(value)


class ResourceReceiptPublicationTests(unittest.TestCase):
    """Exercise real final validation, signal ownership and new-file publication."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fixture = self.root / "fixture"
        fixture.mkdir()
        self.args = SimpleNamespace(cli=self.root / "latent", node=self.root / "latentd",
                                    fixture_root=fixture, build_identity=self.root / "build.json",
                                    output=self.root / "receipt.json")
        numbers = [signal.SIGINT, signal.SIGTERM]
        if hasattr(signal, "SIGBREAK"):
            numbers.append(signal.SIGBREAK)
        self.original_handlers = dict.fromkeys(numbers, signal.SIG_DFL)
        self.handlers = dict(self.original_handlers)

        def install(number, handler):
            previous = self.handlers[number]
            self.handlers[number] = handler
            return previous

        self.enterContext(patch.object(signal, "getsignal", side_effect=self.handlers.__getitem__))
        self.enterContext(patch.object(signal, "signal", side_effect=install))
        self.enterContext(patch.object(workflow.sys, "platform", "linux"))
        self.enterContext(patch.object(workflow.sys, "version_info", (3, 13)))
        self.enterContext(patch.object(workflow.os, "sysconf", return_value=4096, create=True))
        self.now = 1000.0
        self.enterContext(patch.object(workflow.time, "monotonic", side_effect=lambda: self.now))
        expected = complete_receipt()
        self.enterContext(patch.object(workflow, "build_identity", return_value=expected["build"]))
        self.enterContext(patch.object(workflow, "hash_file", return_value="sha256:" + "1" * 64))
        self.enterContext(patch.object(workflow, "fixture_inventory", return_value=[]))
        self.enterContext(patch.object(workflow, "metadata", return_value={
            "packages": expected["packages"], "verifiedAtUnixSeconds": "1",
            "proofAgeExpiresAtUnixSeconds": "601",
        }))
        self.work_directories = []

        def completed_work(client, _binary, _directory, _fixture, _metadata, result):
            self.work_directories.append(client.directory.parent)
            result.update(copy.deepcopy(expected))
            client.controls = expected["controls"]
            client.invocations = expected["invokeAttempts"]
            self.now += 1

        self.run = self.enterContext(patch.object(workflow, "run", side_effect=completed_work))
        self.stdout = self.enterContext(redirect_stdout(io.StringIO()))

    def check_published(self, passed):
        self.run.assert_called_once()
        self.assertEqual(len(self.work_directories), 1)
        self.assertFalse(self.work_directories[0].exists())
        self.assertEqual(self.handlers, self.original_handlers)
        result = json.loads(self.args.output.read_text())
        self.assertIs(result["passed"], passed)
        self.assertIs(json.loads(self.stdout.getvalue())["passed"], passed)
        self.assertEqual(len(result["samples"]), 12, "completed evidence was discarded")
        self.assertTrue(result["temporaryOutputsRemoved"])
        if not passed:
            with self.assertRaisesRegex(WorkflowError, "receipt-not-passing"):
                validate_receipt(result)
        return result

    def test_cancellation_during_final_validation_retains_only_failed_receipt(self):
        def validate_then_cancel(value):
            validate_receipt(value)
            handler = self.handlers[signal.SIGTERM]
            self.assertTrue(callable(handler))
            handler(signal.SIGTERM, None)

        with patch.object(workflow, "validate_receipt", side_effect=validate_then_cancel):
            with self.assertRaisesRegex(WorkflowError, "receipt-validation:resource-unavailable"):
                workflow.execute(self.args)
        self.check_published(False)

    def test_validation_overrun_uses_existing_final_deadline_and_retains_failure(self):
        def validate_then_expire(value):
            validate_receipt(value)
            self.now = 1000 + PROFILE["deadlineSeconds"] + PROFILE["shutdownSeconds"] + 1

        with patch.object(workflow, "validate_receipt", side_effect=validate_then_expire):
            with self.assertRaisesRegex(WorkflowError, "receipt-validation:resource-deadline"):
                workflow.execute(self.args)
        self.assertEqual(self.check_published(False)["elapsedMillis"], "311000")

    def test_successful_publication_includes_final_validation_elapsed_time(self):
        def validate_then_finish(value):
            validate_receipt(value)
            self.now += 2

        with patch.object(workflow, "validate_receipt", side_effect=validate_then_finish):
            workflow.execute(self.args)
        result = self.check_published(True)
        self.assertEqual(result["elapsedMillis"], "3000")
        validate_receipt(result)
