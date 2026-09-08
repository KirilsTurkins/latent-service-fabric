"""Tiny synthetic verifier inputs, never a checked-in measured baseline."""

from __future__ import annotations

import copy
import base64
import json
from pathlib import Path
import tempfile
import unittest

from tools.validate_phase1_conformance import (
    ConformanceValidationError, MANIFEST, PARITY_INPUTS, PARITY_PAIRS, ZERO_SHUTDOWN_FIELDS, canonical_json, file_digest,
    load_bounded, sha256, validate_report, verify_adapter_input_files, verify_input_files,
)


def counts(commands: int, invokes: int) -> dict:
    return {"commands": str(commands), "invoke_attempts": str(invokes), "budget_exhausted": False}


def cli(command: str, data: dict | None, category: str = "success", error=None, known=True) -> dict:
    return {"schemaVersion": "latent.cli.result.v1", "command": command, "category": category,
            "data": data, "error": error, "requestDispatched": True, "outcomeKnown": known}


def consumption() -> dict:
    return {"cpuFuel": "100", "peakMemoryBytes": "1000", "wallTimeMicros": "10", "logBytes": "0",
            "childCalls": 0, "outboundRequests": 0, "effectCount": 0,
            **dict.fromkeys(("stateReadBytes", "stateWriteBytes", "blobReadBytes", "blobWriteBytes"), "0")}


def invoke(identifier: str, decoded=None, terminal: str | None = None, code: str | None = None, cell="cell-a") -> dict:
    data = {"activationId": identifier, "consumption": consumption(),
            "resolvedRevision": {"revisionId": "revision-synthetic", "releaseDigest": sha256(b"generic"), "routeGeneration": "1"},
            "metadata": {"cell-id": cell}}
    if terminal is not None:
        data["terminalState"] = terminal
        return cli("invoke", data, "platform-failure", {"code": code or terminal})
    raw = canonical_json(decoded)
    data["payload"] = {"encoding": "base64", "mediaType": "application/vnd.latent.wit-values.v1+json",
                       "data": base64.b64encode(raw).decode(), "byteLength": str(len(raw))}
    return cli("invoke", data)


def status(identifier: str, terminal: str | None = None, used=None, phase="running") -> dict:
    return cli("activation get", {"activationId": identifier, "phase": phase, "terminalState": terminal,
                                  "finalConsumption": used, "terminalAtUnixMillis": "1000" if terminal else None})


def idle_fixture(sample: dict, phase: str) -> dict:
    result = copy.deepcopy(sample)
    result["phase"] = phase
    result["inventory"] = {
        "queueDepth": "0", "cacheSummary": dict.fromkeys(("preparing", "preparingSourceBytes", "preparingMetadataBytes"), "0"),
        "quotas": {"usage": {"activeActivations": 0, "queuedActivations": 0, "reservedCpuFuel": "0", "reservedMemoryBytes": "0"}},
        "cellCapacity": [{"total": 2, "available": 2, "active": 0, "quarantined": 0, "queueDepth": 0}],
        "topology": {"available": True, "entries": [
            {"ownership": "activation-scoped", "activeCount": "0"},
            {"ownership": "service-resident", "activeCount": "0", "configuredCount": "0"}]}}
    return result


def fresh_fixture(sample: dict) -> dict:
    return {"responses": [invoke("warmup", [11]), invoke("fresh-first", [1]),
                          invoke("fresh-second", [1], cell="cell-b"), invoke("fresh-third", [1])],
            "sample": idle_fixture(sample, "warm")}


def fuel_fixture(sample: dict) -> dict:
    response = invoke("fuel-exhausted", terminal="resource_exhausted", code="resource-exhausted")
    return {"response": response, "status": status("fuel-exhausted", "resource_exhausted", response["data"]["consumption"]),
            "fuelGrant": "50000", "idleSample": idle_fixture(sample, "fuel-settled")}


def queue_fixture(sample: dict) -> dict:
    first, second = "queue-holder-first", "queue-holder-second"
    a1, a2, other = "queued-tests-first", "queued-tests-second", "queued-examples"
    full = {"queueDepth": "3", "cellCapacity": [{"total": 2, "active": 2, "available": 0, "queueDepth": 3, "queuedTenants": 2}],
            "quotas": {"usage": {"activeActivations": 5, "queuedActivations": 3}}}
    queued = [invoke(a1, terminal="cancelled"), invoke(a2, terminal="cancelled"), invoke(other, [{"ok": "queued other tenant"}])]
    return {"holdersRunning": [status(first), status(second)], "queued": [status(item, phase="queued") for item in (a1, a2, other)],
            "full": full, "unchangedFull": copy.deepcopy(full),
            "overflow": cli("invoke", None, "transport-failure", {"grpcCode": "resource-exhausted"}, known=False),
            "overflowStatus": cli("activation get", None, "not-found"), "firstHandoff": status(a1),
            "secondHandoff": {"examplesResult": queued[2], "secondHolderRunning": status(second), "secondQueuedRunning": status(a2)},
            "cancelled": [cli("activation cancel", {"activationId": item, "disposition": "accepted", "terminalState": None})
                          for item in (first, a1, a2, second)],
            "holderResults": [invoke(item, terminal="cancelled") for item in (first, second)],
            "queuedResults": queued, "queuedStatuses": [status(item, "completed" if index == 2 else "cancelled", queued[index]["data"]["consumption"])
                                                            for index, item in enumerate((a1, a2, other))],
            "idleSample": idle_fixture(sample, "queue-settled"),
            "fairnessOracle": "other-tenant-completes-before-uncancelled-same-tenant-spin",
            "overflowBoundary": "standalone-active-owner-ceiling-before-extra-journal-registration"}


def wall_fixture(sample: dict) -> dict:
    def observe(identifier, before, ceiling):
        deadline = before + ceiling
        decoded = [{"activation": identifier, "deadline": {"some": str(deadline)},
                    "remaining": {"wall-time-limit-millis": {"some": str(ceiling - 1)}}}]
        response = invoke(identifier, decoded)
        return {"response": response, "status": status(identifier, "completed", response["data"]["consumption"]),
                "decoded": decoded, "beforeUnixMillis": str(before), "afterUnixMillis": str(before + 1),
                "effectiveDeadlineUnixMillis": str(deadline), "remainingMillis": str(ceiling - 1),
                "requestedWallMillis": "5000", "clockResolutionMillis": "1"}
    def deployment(command, generation, ceiling):
        return cli(command, {"deployment": {"generation": str(generation),
            "manifest": {"metadata": {"name": "capabilities", "tenant": "tests"},
                         "spec": {"resources": {"wallTimeLimitMillis": ceiling}}}}})
    applied = deployment("deployment apply", 2, 1000)
    return {"nodeCeiling": {"ceilingMillis": "5000", "nodeAgeMillis": "5001",
                "observation": observe("wall-node-aged", 6000, 5000), "scope": "configured-standalone-transport-and-admission"},
            "deploymentCeiling": {"ceilingMillis": "1000", "agedMillis": "1001", "committedUnixMillis": "8000",
                "original": deployment("deployment get", 1, None), "applied": applied,
                "persistedBefore": deployment("deployment get", 2, 1000), "persistedAfter": deployment("deployment get", 2, 1000),
                "observation": observe("wall-deployment-aged", 9001, 1000)},
            "callerDeadline": {"absoluteUnixMillis": "10500", "observation": observe("wall-caller-earlier", 10000, 500)},
            "restored": deployment("deployment apply", 3, None), "idleSample": idle_fixture(sample, "wall-ceilings-settled")}


def remaining(fuel=99_999_900, memory=67_000_000, logs=16384) -> dict:
    return {"cpu-fuel": str(fuel), "memory-bytes": str(memory), "log-bytes": str(logs),
            "wall-time-limit-millis": {"some": "3999"}, "child-calls": 0, "outbound-requests": 0, "effect-count": 0,
            **dict.fromkeys(("state-read-bytes", "state-write-bytes", "blob-read-bytes", "blob-write-bytes"), "0")}


def telemetry_fixture(tenant: str, identifier: str, log_count: int, ordinal: int) -> dict:
    root, parent = ("parity-root", "parity-parent") if tenant == "examples" else ("capability-root", "capability-parent")
    release = sha256(b"echo" if tenant == "examples" else b"capabilities")
    trace = {"trace_id": f"{ordinal:032x}", "span_id": f"{ordinal:016x}", "trace_flags": 0, "baggage": {}}
    attrs = {"activation_id": identifier, "root_activation_id": root, "parent_activation_id": parent,
             "tenant": tenant, "service": "shared", "release": release, "revision": "revision-synthetic", "route_generation": "1"}
    attrs.update(contract="examples:echo/api@0.1.0" if tenant == "examples" else "tests:capabilities/api@0.1.0",
                 function="echo" if tenant == "examples" else identifier.split("-cap-", 1)[-1])
    result = {"activation_id": identifier, "root_activation_id": root, "parent_activation_id": parent,
            "tenant": tenant, "service": "shared", "release_digest": release, "revision_id": "revision-synthetic", "route_generation": "1",
            "completion_span": {"name": "latent.activation", "status": "ok", "attributes": copy.deepcopy(attrs),
                                "trace": trace, "started_at_unix_nanos": "1000000", "ended_at_unix_nanos": "1000010"},
            "guest_logs": [{"body": "[REDACTED]", "attributes": copy.deepcopy(attrs), "trace": copy.deepcopy(trace),
                            "observed_at_unix_millis": "1000"} for _ in range(log_count)]}
    if tenant == "examples":
        result["completion_span"]["attributes"].update(cpu_fuel="0", memory_bytes="0", log_bytes="0")
    return result


def capability_fixture(name: str, direct: bool, ordinal: int) -> dict:
    identifier = ("direct" if direct else "remote") + "-cap-" + name
    call = telemetry_fixture("tests", identifier, {"snapshot": 0, "work-observe": 1, "clocks": 2}[name], ordinal)
    used = {"cpu_fuel": "10000", "peak_memory_bytes": "1000000", "wall_time_micros": "50", "log_bytes": "0" if name == "snapshot" else "100",
            **dict.fromkeys(("child_calls", "outbound_requests", "state_read_bytes", "state_write_bytes", "blob_read_bytes", "blob_write_bytes", "effect_count"), "0")}
    call.update(cell_id="phase1-adapter-parity:phase0:standard:00000000", consumption=used,
                grant={"cpu_fuel": "100000000", "memory_bytes": "67108864", "log_bytes": "16384", "wall_time_limit_millis": "4000"},
                retained_status={"activation_id": identifier, "phase": "running", "terminal_state": "completed", "final_consumption": copy.deepcopy(used),
                                 "terminal_at_unix_millis": "1001", "last_updated_unix_millis": "1001",
                                 "metadata": {"release": call["release_digest"], "revision": call["revision_id"], "route-generation": call["route_generation"]},
                                 "terminal_kind": "success"})
    call["completion_span"]["attributes"].update(cpu_fuel=used["cpu_fuel"], memory_bytes=used["peak_memory_bytes"],
                                                wall_time_micros=used["wall_time_micros"], log_bytes=used["log_bytes"])
    if name == "snapshot":
        trace = call["completion_span"]["trace"]
        decoded = {"activation": identifier, "root": "capability-root", "parent": {"some": "capability-parent"},
                   "principal": {"subject": "parity-tests", "kind": "administrator", "tenant": {"some": "tests"}, "service": {"none": None}, "claims": []},
                   "trace": {"trace-id": trace["trace_id"], "span-id": trace["span_id"], "trace-flags": 0, "baggage": []},
                   "deadline": {"some": "5000"}, "metadata": [["guest.visible", "paired"]], "remaining": remaining()}
    elif name == "work-observe":
        decoded = {"before": remaining(), "after": remaining(99_999_000, 66_500_000, 16284), "logged": {"ok": True}, "checksum": 1024}
    else:
        decoded = [{"wall": "1000", "monotonic": str(index + 1)} for index in range(3)]
    call["decoded"] = [decoded]
    return call


def parity_observations(cleanup: dict) -> dict:
    config = {
        "formatVersion": 1, "dataDirectory": "data", "nodeId": "phase1-adapter-parity",
        "bind": "127.0.0.1:0", "workers": {"runtime": 1, "control": 1},
        "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2, "maximumMemoryBytes": 64 * 1024 * 1024}],
        "execution": {"maximumCpuFuel": 100_000_000, "maximumWallTimeMillis": 5000, "maximumLogBytes": 16384},
        "shutdownGraceMillis": 500,
    }
    pairs = []
    for index, name in enumerate(PARITY_PAIRS):
        if index in (3, 7):
            pairs.append({"name": name, "classification": "rpc-rejection",
                          "code": "DeadlineExceeded" if index == 3 else "PermissionDenied"})
        else:
            pairs.append({"name": name,
                          "classification": "success" if index == 0 else "declared-error" if index == 1 else "platform-failure",
                          "cpu_fuel": "0", "peak_memory_bytes": "0", "log_bytes": "0", "receipt_pin_equal": True})
    capabilities = [{"name": name, "direct": capability_fixture(name, True, 1 + index * 2),
                     "rpc": capability_fixture(name, False, 2 + index * 2),
                     "observed_before_unix_millis": "1000", "observed_after_unix_millis": "1001"}
                    for index, name in enumerate(("snapshot", "work-observe", "clocks"))]
    return {"pairs": pairs, "capability_pairs": capabilities, "published_inputs": [],
            "tenant_telemetry": [telemetry_fixture("examples", "remote-0", 1, 7), copy.deepcopy(capabilities[1]["rpc"])],
            "shutdown": copy.deepcopy(cleanup), "node_starts": "1",
            "public_config": config, "config_sha256": sha256(canonical_json(config)),
            "inputs": [{"name": name, "sha256": sha256(b"echo" if index == 0 else name.encode()),
                        "bytes": str(4 if index == 0 else len(name))} for index, name in enumerate(PARITY_INPUTS)],
            "comparison": "synthetic unit test", "variable_fields": ["test identity"], "scope": "synthetic unit test",
            "retained_metric_points": "1", "inventory_cache_entries": "2"}


def published_fixtures(report: dict, root: Path) -> None:
    (root / "adapter-inputs").mkdir(exist_ok=True)
    rows = []
    for name, tenant in (("echo", "examples"), ("capabilities", "tests")):
        release = sha256(name.encode())
        package = "examples:echo" if name == "echo" else "tests:capabilities"
        contract = package + "/api@0.1.0"
        row = {"tenant": tenant, "service": "shared", "component_sha256": release}
        documents = {"manifest": {"metadata": {"name": "shared", "tenant": tenant}, "component": {"digest": release}, "exports": [contract]},
                     "contracts": {"format_version": 1, "contracts": [{"id": contract, "package_name": package, "synthetic_unit_test": True}]},
                     "deployment": {"metadata": {"tenant": tenant}, "spec": {"service": "shared", "release": release}}}
        for kind, document in documents.items():
            raw = canonical_json(document)
            path = f"adapter-inputs/{name}-{kind}.json"
            (root / path).write_bytes(raw)
            reference = {"path": path, "sha256": sha256(raw), "bytes": str(len(raw))}
            row[kind] = reference
            report["artifacts"].append(reference)
        rows.append(row)
    report["cases"][-1]["observations"]["published_inputs"] = rows


def refresh_case_artifacts(report: dict, root: Path) -> None:
    for case in report["cases"]:
        if case["id"] == "adapter-rpc-parity":
            name = "adapter.json"
            case["diagnostics"] = [name]
            value = {"driver": "adapter", "cases": [case], "work": case["work"],
                     "artifacts": [item for item in report["artifacts"] if item["path"].startswith("adapter-inputs/")]}
        else:
            name = f"case-{case['id']}.json"
            case["diagnostics"] = [name]
            value = case["observations"]
        data = canonical_json(value)
        (root / name).write_bytes(data)
        reference = {"path": name, "sha256": sha256(data), "bytes": str(len(data))}
        report["artifacts"] = [item for item in report["artifacts"] if item["path"] != name]
        report["artifacts"].append(reference)


def fixture_report(root: Path) -> dict:
    manifest = json.loads(MANIFEST.read_text())
    raw = b'{"syntheticUnitTestFixture":true}\n'
    (root / "raw.jsonl").write_bytes(raw)
    identity = {
        "source_commit": "a" * 40, "source_tree": "b" * 40, "source_dirty": True,
        "cargo_lock_sha256": "sha256:" + "c" * 64,
        "config_sha256": sha256(b'{"configured_cells":2,"runtime_workers":1}'),
        "binaries": [{"name": name, "sha256": sha256(name.encode()), "bytes": str(len(name))}
                     for name in ("latent", "latentd")],
        "fixtures": [{"name": name, "sha256": sha256(name.encode()), "bytes": str(len(name))}
                     for name in ("echo", "generic", "capabilities")],
    }
    cases = [{"id": identifier, "status": "passed", "reason": None,
              "work": counts(22, 22) if identifier == "adapter-rpc-parity" else counts(1, 1),
              "observations": {"synthetic_unit_test": True}, "diagnostics": ["raw.jsonl"]}
             for identifier in manifest["required_cases"]]
    process = {
        "identity": {"processId": 123, "startTimeTicks": "456"},
        "process": {"processId": 123, "residentMemoryBytes": "1024", "threadCount": "4",
                    "openFileDescriptors": "8", "socketCount": "2"},
        "taskCount": "4", "uniqueSocketCount": "2", "listeningTcpSocketCount": "1",
        "descendants": [], "sampleAttempts": 1,
    }
    cleanup = dict.fromkeys(ZERO_SHUTDOWN_FIELDS, 0)
    cleanup.update(clean=True, quarantinedCells=1, telemetryRetainedEntries=3,
                   telemetryFlushed=True, epochHelperJoined=True)
    process_commands = len(cases) - 1
    cases[-1]["observations"] = parity_observations(cleanup)
    report = {
        "schema": "latent.phase1.conformance.v1", "profile": "bounded-deterministic",
        "case_manifest_sha256": sha256(MANIFEST.read_bytes()), "identity": identity,
        "environment": {"os": "linux", "kernel": "unit-test", "architecture": "test",
                        "rust_version": "test", "wasmtime_version": "test"},
        "public_config": {"configured_cells": 2, "runtime_workers": 1},
        "work": counts(process_commands + 22, process_commands + 22), "drivers": [
            {"driver": "process", "work": counts(process_commands, process_commands)},
            {"driver": "adapter", "work": counts(22, 22)},
        ], "cases": cases,
        "samples": [{"sequence": str(index), "sample_started_micros": str(index * 2),
                     "sample_finished_micros": str(index * 2 + 1), "node_instance": 1, "phase": phase,
                     "process": copy.deepcopy(process), "inventory": {"synthetic_unit_test": True}}
                    for index, phase in enumerate(("empty", "dormant", "warm", "post-mixed"))],
        "shutdowns": [{"node_instance": 1, "process_id": 123, "start_time_ticks": "456",
                       "exit_success": True, "reaped": True, "readers_joined": True, "report": cleanup}],
        "artifacts": [{"path": "raw.jsonl", "sha256": sha256(raw), "bytes": str(len(raw))}],
        "deferred_evidence": [{"id": identifier, "status": "not_run", "reason": "outside-bounded-profile"}
                              for identifier in manifest["deferred_evidence"]],
        "deterministic_status": "passed", "phase1_completion": "incomplete",
    }
    for case in report["cases"]:
        builder = {"fresh-store": fresh_fixture, "fuel-budget": fuel_fixture, "queue-admission": queue_fixture,
                   "persistent-wall-ceiling": wall_fixture}.get(case["id"])
        if builder:
            case["observations"] = builder(report["samples"][0])
    published_fixtures(report, root)
    refresh_case_artifacts(report, root)
    return report


class ConformanceValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.report = fixture_report(self.root)

    def rejects(self, mutation) -> None:
        candidate = copy.deepcopy(self.report)
        mutation(candidate)
        with self.assertRaises(ConformanceValidationError):
            validate_report(candidate, self.root)

    def test_complete_selected_cases_are_only_an_incomplete_phase1_gate(self) -> None:
        validate_report(self.report, self.root)
        self.assertEqual(self.report["phase1_completion"], "incomplete")

    def test_missing_duplicate_unknown_or_skipped_case_fails(self) -> None:
        changes = [lambda value: value["cases"].pop(),
                   lambda value: value["cases"].append(value["cases"][0]),
                   lambda value: value["cases"][0].update(id="invented"),
                   lambda value: value["cases"][0].update(status="not_run", reason="missing-fixture"),
                   lambda value: value["cases"][0].update(status="not_applicable", reason="missing-fixture"),
                   lambda value: value["cases"][0].update(status="failed", reason="fixture-failed")]
        for change in changes:
            with self.subTest(change=change):
                self.rejects(change)

    def test_heavy_work_cannot_be_promoted_to_pass_or_silently_omitted(self) -> None:
        for change in (lambda value: value.update(phase1_completion="complete"),
                       lambda value: value["deferred_evidence"].pop(),
                       lambda value: value["deferred_evidence"][0].update(status="passed"),
                       lambda value: value["deferred_evidence"][0].update(reason="not-needed")):
            self.rejects(change)

    def test_invocation_and_command_caps_include_rejected_attempts(self) -> None:
        for work in (counts(65, 65), counts(257, 1), {**counts(30, 30), "budget_exhausted": True}):
            self.rejects(lambda value: value.update(work=work))
        self.rejects(lambda value: value["drivers"][0].update(work=counts(225, 14)))
        self.rejects(lambda value: value["cases"][0].update(work=counts(0, 0)))

    def test_u64_values_are_lossless_canonical_decimal_strings(self) -> None:
        for malformed in (30, True, "030", "+30", "18446744073709551616", "-1"):
            self.rejects(lambda value: value["work"].update(commands=malformed))

    def test_missing_or_unknown_measurements_are_never_zero_substitutes(self) -> None:
        for unavailable in (None, "0"):
            self.rejects(lambda value: value["samples"][0]["process"]["process"].update(residentMemoryBytes=unavailable))
        self.rejects(lambda value: value["samples"][0]["process"].update(listeningTcpSocketCount="0"))
        self.rejects(lambda value: value["samples"][0]["process"].update(descendants=[{"processId": 999, "startTimeTicks": "100"}]))

    def test_changed_child_pid_starttime_or_unreaped_owner_fails(self) -> None:
        self.rejects(lambda value: value["samples"][1]["process"]["identity"].update(processId=999))
        self.rejects(lambda value: value["samples"][1]["process"]["identity"].update(startTimeTicks="789"))
        self.rejects(lambda value: value["shutdowns"][0].update(reaped=False))
        self.rejects(lambda value: value["shutdowns"][0].update(readers_joined=False))
        self.rejects(lambda value: value["samples"][1].update(sequence="0"))

    def test_missing_cleanup_or_live_owner_fails(self) -> None:
        self.rejects(lambda value: value["shutdowns"].clear())
        for key in ZERO_SHUTDOWN_FIELDS:
            with self.subTest(counter=key):
                self.rejects(lambda value: value["shutdowns"][0]["report"].update({key: 1}))
        self.rejects(lambda value: value["shutdowns"][0]["report"].pop("liveStores"))
        self.rejects(lambda value: value["shutdowns"][0]["report"].update(epochHelperJoined=False))

    def test_corrupt_raw_bytes_size_hash_or_missing_diagnostic_fails(self) -> None:
        self.rejects(lambda value: value["artifacts"][0].update(bytes="1"))
        self.rejects(lambda value: value["artifacts"][0].update(sha256="sha256:" + "0" * 64))
        self.rejects(lambda value: value["cases"][0].update(diagnostics=[]))
        (self.root / "raw.jsonl").write_bytes(b"changed")
        with self.assertRaises(ConformanceValidationError):
            validate_report(self.report, self.root)

    def test_path_traversal_and_symlink_escape_fails(self) -> None:
        for path in ("../raw.jsonl", "/raw.jsonl", "a/../raw.jsonl", "C:\\raw.jsonl", "./raw.jsonl"):
            self.rejects(lambda value: value["artifacts"][0].update(path=path))
        link = self.root / "alias.jsonl"
        try:
            link.symlink_to(self.root / "raw.jsonl")
        except OSError:
            return  # Windows hosts may disallow symlink creation; traversal still tested.
        self.rejects(lambda value: value["artifacts"][0].update(path=link.name))

    def test_duplicate_json_depth_and_byte_limits_fail_before_validation(self) -> None:
        path = self.root / "bad.json"
        for raw in (b'{"work":1,"work":2}', b"[" * 49 + b"0" + b"]" * 49,
                    b'{"x":NaN}', b'{"x":1e999}', b'{"x":' + b"9" * 100 + b"}"):
            path.write_bytes(raw)
            with self.assertRaises(ConformanceValidationError):
                load_bounded(path)
        path.write_bytes(b" " * 65)
        with self.assertRaises(ConformanceValidationError):
            load_bounded(path, 64)

    def test_source_config_manifest_identity_and_secret_config_are_checked(self) -> None:
        with self.assertRaises(ConformanceValidationError):
            validate_report(self.report, self.root, expected_source_commit="0" * 40)
        with self.assertRaises(ConformanceValidationError):
            validate_report(self.report, self.root, expected_config_sha256="sha256:" + "0" * 64)
        self.rejects(lambda value: value.update(case_manifest_sha256="sha256:" + "0" * 64))
        self.rejects(lambda value: value["public_config"].update(nested={"token": "PRIVATE"}))
        self.rejects(lambda value: value["public_config"].update(configured_cells=3))

    def test_sampling_windows_phases_and_dormant_thread_topology_are_coherent(self) -> None:
        self.rejects(lambda value: value["samples"][1].update(sample_started_micros="0"))
        self.rejects(lambda value: value["samples"][1].update(phase="empty"))
        self.rejects(lambda value: value["samples"][1]["process"].update(taskCount="5"))
        def growth(value):
            value["samples"][1]["process"].update(taskCount="5")
            value["samples"][1]["process"]["process"].update(threadCount="5")
        self.rejects(growth)

    def test_actual_binary_and_fixture_bytes_bind_report_identities(self) -> None:
        for name in ("latent", "echo"):
            (self.root / name).write_bytes(name.encode())
        verify_input_files(self.report["identity"], [f"latent={self.root / 'latent'}"],
                           [f"echo={self.root / 'echo'}"], None)
        (self.root / "echo").write_bytes(b"changed")
        with self.assertRaises(ConformanceValidationError):
            verify_input_files(self.report["identity"], [], [f"echo={self.root / 'echo'}"], None)
        with self.assertRaises(ConformanceValidationError):
            file_digest(self.root / "echo", 2)

    def test_report_observations_cannot_diverge_from_hashed_case_or_adapter_diagnostics(self) -> None:
        self.rejects(lambda value: value["cases"][0]["observations"].update(synthetic_unit_test=False))
        self.rejects(lambda value: value["cases"][-1]["observations"].update(node_starts="2"))
        self.rejects(lambda value: value["cases"][-1].update(diagnostics=["raw.jsonl"]))

    def test_adapter_requires_all_eight_ordered_outcome_pairs_even_with_claimed_invokes(self) -> None:
        changes = [lambda value: value["pairs"].pop(),
                   lambda value: value["pairs"].append(value["pairs"][0]),
                   lambda value: value["pairs"][0].update(name="foreign-tenant"),
                   lambda value: value["pairs"][3].update(code="Internal"),
                   lambda value: value["pairs"][0].update(receipt_pin_equal=False),
                   lambda value: value["pairs"][0].update(cpu_fuel="1000001")]
        for change in changes:
            self.rejects_parity(change)

    def rejects_parity(self, mutation) -> None:
        self.rejects_case("adapter-rpc-parity", mutation)

    def rejects_case(self, identifier, mutation) -> None:
        candidate = copy.deepcopy(self.report)
        case = next(case for case in candidate["cases"] if case["id"] == identifier)
        mutation(case["observations"])
        # Rehash the raw artifact too, so the semantic checks themselves must reject.
        refresh_case_artifacts(candidate, self.root)
        with self.assertRaises(ConformanceValidationError):
            validate_report(candidate, self.root)
        refresh_case_artifacts(self.report, self.root)

    def test_positive_fuel_exhaustion_needs_charge_retained_accounting_and_reclamation(self) -> None:
        changes = [lambda value: value.update(fuelGrant="0"),
                   lambda value: value["response"]["data"]["consumption"].update(cpuFuel="0"),
                   lambda value: value["response"]["data"]["consumption"].update(cpuFuel="50001"),
                   lambda value: value["response"]["error"].update(code="deadline-exceeded"),
                   lambda value: value["status"]["data"].update(activationId="other-owner"),
                   lambda value: value["status"]["data"].update(finalConsumption=consumption() | {"cpuFuel": "99"}),
                   lambda value: value["idleSample"]["inventory"]["quotas"]["usage"].update(activeActivations=1)]
        for change in changes:
            self.rejects_case("fuel-budget", change)

    def test_fresh_state_must_repeat_on_the_same_actual_cell(self) -> None:
        for change in (lambda value: value["responses"].pop(),
                       lambda value: value["responses"][3]["data"]["metadata"].update({"cell-id": "cell-c"}),
                       lambda value: value["responses"][3].update(data=invoke("fresh-third", [2])["data"])):
            self.rejects_case("fresh-store", change)

    def test_fairness_cannot_pass_with_expired_or_early_cancelled_competitors(self) -> None:
        changes = [lambda value: value["queued"].pop(),
                   lambda value: value["full"]["cellCapacity"][0].update(queuedTenants=1),
                   lambda value: value["firstHandoff"]["data"].update(phase="queued"),
                   lambda value: value["secondHandoff"]["secondHolderRunning"]["data"].update(terminalState="deadline_exceeded"),
                   lambda value: value["secondHandoff"]["secondQueuedRunning"]["data"].update(terminalAtUnixMillis="1000"),
                   lambda value: value["cancelled"][2]["data"].update(disposition="already-terminal", terminalState="deadline_exceeded"),
                   lambda value: value["overflow"].update(category="platform-failure", outcomeKnown=True),
                   lambda value: value["overflowStatus"].update(category="success", data={}),
                   lambda value: value["queuedStatuses"][2]["data"].update(finalConsumption=consumption() | {"cpuFuel": "99"}),
                   lambda value: value["idleSample"]["inventory"]["cellCapacity"][0].update(quarantined=1)]
        for change in changes:
            self.rejects_case("queue-admission", change)

    def test_relative_wall_policies_must_age_persist_and_preserve_the_earlier_caller(self) -> None:
        changes = [lambda value: value["nodeCeiling"].update(nodeAgeMillis="5000"),
                   lambda value: value["deploymentCeiling"].update(agedMillis="1000"),
                   lambda value: value["deploymentCeiling"].update(committedUnixMillis="8001"),
                   lambda value: value["nodeCeiling"]["observation"].update(effectiveDeadlineUnixMillis="5000"),
                   lambda value: value["deploymentCeiling"]["observation"].update(remainingMillis="1001"),
                   lambda value: value["deploymentCeiling"]["persistedAfter"]["data"]["deployment"].update(generation="3"),
                   lambda value: value["callerDeadline"].update(absoluteUnixMillis="11000"),
                   lambda value: value["restored"]["data"]["deployment"]["manifest"]["spec"]["resources"].update(wallTimeLimitMillis=1000),
                   lambda value: value["nodeCeiling"]["observation"].update(decoded=[])]
        for change in changes:
            self.rejects_case("persistent-wall-ceiling", change)

    def test_capability_pairs_require_exact_context_trace_and_retained_ownership(self) -> None:
        changes = [lambda value: value["capability_pairs"].pop(),
                   lambda value: value["capability_pairs"][0].update(name="clocks"),
                   lambda value: value["capability_pairs"][0]["rpc"].update(cell_id="other-cell"),
                   lambda value: value["capability_pairs"][0]["rpc"]["decoded"][0].update(activation="direct-cap-snapshot"),
                   lambda value: value["capability_pairs"][0]["rpc"]["decoded"][0]["principal"].update(tenant={"some": "examples"}),
                   lambda value: value["capability_pairs"][0]["rpc"]["decoded"][0]["principal"].update(kind="user"),
                   lambda value: value["capability_pairs"][0]["rpc"]["decoded"][0]["trace"].update({"trace-id": "f" * 32}),
                   lambda value: value["capability_pairs"][0]["rpc"]["retained_status"]["final_consumption"].update(cpu_fuel="99"),
                   lambda value: value["capability_pairs"][0]["rpc"]["retained_status"]["metadata"].update(release=sha256(b"echo")),
                   lambda value: value["capability_pairs"][0]["rpc"]["completion_span"]["attributes"].update(function="other-function")]
        for change in changes:
            self.rejects_parity(change)

    def test_live_budget_and_clock_evidence_cannot_be_replaced_with_flags(self) -> None:
        changes = [lambda value: value["capability_pairs"][1]["direct"]["decoded"][0].update(checksum=0),
                   lambda value: value["capability_pairs"][1]["direct"]["decoded"][0].update(logged={"err": "denied"}),
                   lambda value: value["capability_pairs"][1]["direct"]["decoded"][0]["after"].update({"log-bytes": "16384"}),
                   lambda value: value["capability_pairs"][1]["direct"]["completion_span"]["attributes"].update(log_bytes="99"),
                   lambda value: value["capability_pairs"][1]["direct"]["guest_logs"].clear(),
                   lambda value: value["capability_pairs"][2]["direct"]["decoded"][0][1].update(monotonic="0"),
                   lambda value: value["capability_pairs"][2]["direct"]["decoded"][0][1].update(wall="0")]
        for change in changes:
            self.rejects_parity(change)

    def test_live_submillisecond_budget_can_project_to_zero_milliseconds(self) -> None:
        candidate = copy.deepcopy(self.report)
        value = candidate["cases"][-1]["observations"]["capability_pairs"][0]["direct"]["decoded"][0]
        value["remaining"]["wall-time-limit-millis"] = {"some": "0"}
        refresh_case_artifacts(candidate, self.root)
        try:
            validate_report(candidate, self.root)
        finally:
            refresh_case_artifacts(self.report, self.root)

    def test_shared_service_telemetry_and_transmitted_metadata_stay_tenant_bound(self) -> None:
        changes = [lambda value: value["tenant_telemetry"].pop(),
                   lambda value: value["tenant_telemetry"][0].update(tenant="tests"),
                   lambda value: value["tenant_telemetry"][0]["guest_logs"][0]["attributes"].update(activation_id="remote-cap-work-observe"),
                   lambda value: value["tenant_telemetry"][0]["guest_logs"][0]["trace"].update(trace_id="f" * 32),
                   lambda value: value["tenant_telemetry"][0]["guest_logs"][0].update(body="unredacted guest data"),
                   lambda value: value["tenant_telemetry"][0]["completion_span"]["attributes"].update(cpu_fuel="10000"),
                   lambda value: value["tenant_telemetry"][0]["completion_span"]["attributes"].update(memory_bytes="1000000"),
                   lambda value: value["tenant_telemetry"][0]["completion_span"]["attributes"].update(log_bytes="100"),
                   lambda value: value["tenant_telemetry"][0]["guest_logs"][0]["attributes"].update(contract="tests:capabilities/api@0.1.0"),
                   lambda value: value["published_inputs"].pop(),
                   lambda value: value["published_inputs"][0].update(component_sha256=sha256(b"capabilities")),
                   lambda value: value["published_inputs"][0]["manifest"].update(path="capsule.json")]
        for change in changes:
            self.rejects_parity(change)

    def test_rehashed_transmitted_manifest_cannot_change_published_tenant_scope(self) -> None:
        candidate = copy.deepcopy(self.report)
        reference = candidate["cases"][-1]["observations"]["published_inputs"][0]["manifest"]
        path = self.root / reference["path"]
        original = path.read_bytes()
        changed = json.loads(original)
        changed["metadata"]["tenant"] = "tests"
        raw = canonical_json(changed)
        path.write_bytes(raw)
        reference.update(sha256=sha256(raw), bytes=str(len(raw)))
        refresh_case_artifacts(candidate, self.root)
        try:
            with self.assertRaisesRegex(ConformanceValidationError, "published-manifest-scope-mismatch"):
                validate_report(candidate, self.root)
        finally:
            path.write_bytes(original)
            refresh_case_artifacts(self.report, self.root)

    def test_rehashed_foreign_contract_document_cannot_satisfy_capsule_exports(self) -> None:
        candidate = copy.deepcopy(self.report)
        inputs = candidate["cases"][-1]["observations"]["published_inputs"]
        reference = inputs[1]["contracts"]
        path = self.root / reference["path"]
        original = path.read_bytes()
        raw = (self.root / inputs[0]["contracts"]["path"]).read_bytes()
        path.write_bytes(raw)
        reference.update(sha256=sha256(raw), bytes=str(len(raw)))
        refresh_case_artifacts(candidate, self.root)
        try:
            with self.assertRaisesRegex(ConformanceValidationError, "published-contract-export-mismatch"):
                validate_report(candidate, self.root)
        finally:
            path.write_bytes(original)
            refresh_case_artifacts(self.report, self.root)

    def test_rehashed_configuration_must_cover_observed_capability_grants(self) -> None:
        for field in ("maximumCpuFuel", "maximumLogBytes", "maximumWallTimeMillis", "maximumMemoryBytes"):
            def changed(value):
                config = value["public_config"]
                target = config["cells"][0] if field == "maximumMemoryBytes" else config["execution"]
                target[field] = 1
                value["config_sha256"] = sha256(canonical_json(config))
            self.rejects_parity(changed)

    def test_adapter_cleanup_config_and_input_identities_are_required(self) -> None:
        self.rejects_parity(lambda value: value.update(node_starts="2"))
        self.rejects_parity(lambda value: value["shutdown"].update(liveStores=1))
        self.rejects_parity(lambda value: value["shutdown"].update(epochHelperJoined=False))
        self.rejects_parity(lambda value: value["shutdown"].pop("instanceReservations"))
        self.rejects_parity(lambda value: value["public_config"]["workers"].update(runtime=2))
        def expanded_node(value):
            value["public_config"]["cells"][0]["capacity"] = 3
            value["config_sha256"] = sha256(canonical_json(value["public_config"]))
        self.rejects_parity(expanded_node)
        self.rejects_parity(lambda value: value["inputs"].pop())
        self.rejects_parity(lambda value: value["inputs"][0].update(sha256="sha256:" + "f" * 64))

    def test_adapter_package_metadata_matches_actual_generated_fixture_files(self) -> None:
        for index, name in enumerate(PARITY_INPUTS):
            (self.root / name).write_bytes(b"echo" if index == 0 else name.encode())
        arguments = [f"echo={self.root / PARITY_INPUTS[0]}"]
        verify_adapter_input_files(self.report, arguments)
        (self.root / "contracts.json").write_bytes(b"changed")
        with self.assertRaises(ConformanceValidationError):
            verify_adapter_input_files(self.report, arguments)

    def test_adapter_probe_observations_are_required_canonical_and_bounded(self) -> None:
        for field in ("retained_metric_points", "inventory_cache_entries"):
            self.rejects_parity(lambda value: value.pop(field))
            for invalid in (1, "01", "18446744073709551616"):
                self.rejects_parity(lambda value: value.update({field: invalid}))
        self.rejects_parity(lambda value: value.update(retained_metric_points="1025"))
        self.rejects_parity(lambda value: value.update(inventory_cache_entries="0"))
        self.rejects_parity(lambda value: value.update(inventory_cache_entries="1"))


if __name__ == "__main__":
    unittest.main()
