"""Tiny synthetic verifier inputs, never a checked-in measured baseline."""

from __future__ import annotations

import copy
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


def parity_observations(cleanup: dict) -> dict:
    config = {
        "formatVersion": 1, "dataDirectory": "data", "nodeId": "phase1-adapter-parity",
        "bind": "127.0.0.1:0", "workers": {"runtime": 1, "control": 1},
        "cells": [{"class": "standard", "capacity": 2, "queueCapacity": 2, "maximumMemoryBytes": 64 * 1024 * 1024}],
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
    return {"pairs": pairs, "shutdown": copy.deepcopy(cleanup), "node_starts": "1",
            "public_config": config, "config_sha256": sha256(canonical_json(config)),
            "inputs": [{"name": name, "sha256": sha256(b"echo" if index == 0 else name.encode()),
                        "bytes": str(4 if index == 0 else len(name))} for index, name in enumerate(PARITY_INPUTS)],
            "comparison": "synthetic unit test", "variable_fields": ["test identity"], "scope": "synthetic unit test",
            "retained_metric_points": "1", "inventory_cache_entries": "1"}


def refresh_case_artifacts(report: dict, root: Path) -> None:
    for case in report["cases"]:
        if case["id"] == "adapter-rpc-parity":
            name = "adapter.json"
            case["diagnostics"] = [name]
            value = {"driver": "adapter", "cases": [case], "work": case["work"], "artifacts": []}
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
              "work": counts(16, 16) if identifier == "adapter-rpc-parity" else counts(1, 1),
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
        "work": counts(process_commands + 16, process_commands + 16), "drivers": [
            {"driver": "process", "work": counts(process_commands, process_commands)},
            {"driver": "adapter", "work": counts(16, 16)},
        ], "cases": cases,
        "samples": [{"sequence": str(index), "sample_started_micros": str(index * 2),
                     "sample_finished_micros": str(index * 2 + 1), "node_instance": 1, "phase": phase,
                     "process": copy.deepcopy(process), "inventory": {"synthetic_unit_test": True}}
                    for index, phase in enumerate(("empty", "dormant", "warm", "post-mixed"))],
        "shutdowns": [{"node_instance": 1, "process_id": 123, "start_time_ticks": "456",
                       "exit_success": True, "reaped": True, "readers_joined": True, "report": cleanup}],
        "artifacts": [{"path": "raw.jsonl", "sha256": sha256(raw), "bytes": str(len(raw))}],
        "deferred_evidence": [{"id": identifier, "status": "not_run", "reason": "not-authorized-heavy-work"}
                              for identifier in manifest["deferred_evidence"]],
        "deterministic_status": "passed", "phase1_completion": "incomplete",
    }
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

    def test_adapter_requires_all_eight_ordered_pairs_even_with_sixteen_claimed_invokes(self) -> None:
        changes = [lambda value: value["pairs"].pop(),
                   lambda value: value["pairs"].append(value["pairs"][0]),
                   lambda value: value["pairs"][0].update(name="foreign-tenant"),
                   lambda value: value["pairs"][3].update(code="Internal"),
                   lambda value: value["pairs"][0].update(receipt_pin_equal=False),
                   lambda value: value["pairs"][0].update(cpu_fuel="1000001")]
        for change in changes:
            self.rejects_parity(change)

    def rejects_parity(self, mutation) -> None:
        candidate = copy.deepcopy(self.report)
        mutation(candidate["cases"][-1]["observations"])
        # Rehash the raw artifact too, so the semantic checks themselves must reject.
        refresh_case_artifacts(candidate, self.root)
        with self.assertRaises(ConformanceValidationError):
            validate_report(candidate, self.root)
        refresh_case_artifacts(self.report, self.root)

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
        self.rejects_parity(lambda value: value.update(inventory_cache_entries="2"))


if __name__ == "__main__":
    unittest.main()
