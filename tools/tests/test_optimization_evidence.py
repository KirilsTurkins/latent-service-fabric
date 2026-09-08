"""Synthetic evidence tests: no server, guest, Docker or benchmark execution."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.optimization_evidence.attempts import CONSUMPTION, counts
from tools.optimization_evidence.common import EvidenceError, canonical, decode, read_json, sha256
from tools.optimization_evidence.suite import ZERO_SHUTDOWN, validate_suite
from tools.optimization_evidence.workload import MEDIA, expected
from tools.optimization_runner.plans import SERVICES, TENANT, TOKEN, plan as selected_plan


class Fixture:
    def __init__(self, root):
        self.root, self.refs, self.pid = root, {}, 1000
        selected = selected_plan("smoke")
        executables = {name: self.write(f"binaries/{name}", name.encode()) for name in ("native", "lsf", "client")}
        components = [self.write(f"components/{index}.wasm", b"\0asm" + bytes([index])) for index in range(5)]
        sources = [self.write("sources/shared.rs", b"// synthetic test source\n")]
        self.suite = {
            "schema": "latent.optimization.suite.v1", "profile": "smoke", "plan": selected,
            "identity": {
                "source": {"commit": "a" * 40, "tree": "b" * 40, "dirty": True, "cargo_lock_sha256": sha256(b"lock")},
                "build": {"profile": "debug", "rustc": "rustc fixture", "cargo": "cargo fixture", "wasmtime": "47.0.3",
                          "target": "x86_64-unknown-linux-gnu", "overrides": {"fixture": True}},
                "environment": {"os": "Linux", "arch": "x86_64", "kernel": "synthetic", "cpu_model": "synthetic",
                                "logical_cpus": "4", "memory_total_bytes": "1000000", "virtualization": {},
                                "allocator": {}, "cpu_policy": {}, "load_before": [0, 0, 0]},
                "executables": executables, "components": components, "workload_sources": sources,
            }, "runs": [], "artifacts": [],
        }
        for arm_index, arm in enumerate(("native", "lsf")):
            owner = self.owner(arm + "-server", executables[arm]["sha256"])
            batches, clients = [], []
            for case in selected["cases"]:
                client = self.owner("load-client", executables["client"]["sha256"])
                clients.append(client)
                batches.append(self.batch(arm, case, owner, client, components))
            prefix = arm + "/"
            shutdown = ({"event": "stopped", "clean": True, "implementation": "native-reference"} if arm == "native" else
                        {"schemaVersion": "latent.standalone.status.v1", "event": "stopped", "clean": True,
                         "report": {**dict.fromkeys(ZERO_SHUTDOWN, 0), "clean": True, "telemetryFlushed": True,
                                    "epochHelperJoined": True, "quarantinedCells": 0, "telemetryRetainedEntries": 2}})
            self.suite["runs"].append({
                "repetition": 1, "arm": arm, "scenario": "cold-restart", "status": "passed", "reason": None,
                "started_micros": str(arm_index * 10_000_000), "finished_micros": str((arm_index + 1) * 10_000_000),
                "batches": batches, "server_process": self.write(prefix + "server.json", owner),
                "configuration": self.write(prefix + "config.json", self.config(arm)),
                "cleanup": self.write(prefix + "cleanup.json", {"server": owner, "clients": clients, "server_shutdown": shutdown}),
                "lifecycle": {"process_start_to_ready_micros": "100", "process_start_to_first_response_observed_micros": "200",
                              "ready_to_first_response_observed_micros": "100",
                              "first_response_observation": "parent-received-client-event-upper-bound-includes-client-startup-and-connect",
                              "initial_preparation": "included-in-first-call" if arm == "lsf" else "not-applicable"},
            })
        self.write("empty.log", b"")
        self.save()

    def write(self, name, value):
        data = value if isinstance(value, bytes) else canonical(value) + b"\n"
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        ref = {"path": name, "sha256": sha256(data), "bytes": str(len(data))}
        self.refs[name] = ref
        return ref

    def save(self):
        self.suite["artifacts"] = list(self.refs.values())
        (self.root / "suite.json").write_bytes(canonical(self.suite) + b"\n")

    def replace(self, ref, value):
        replacement = self.write(ref["path"], value)
        def update(item):
            if isinstance(item, dict):
                if set(item) == {"path", "sha256", "bytes"} and item["path"] == ref["path"]:
                    item.update(replacement)
                else:
                    for child in item.values():
                        update(child)
            elif isinstance(item, list):
                for child in item:
                    update(child)
        update(self.suite)
        self.save()

    def owner(self, role, executable):
        self.pid += 1
        return {"process_id": self.pid, "start_time_ticks": str(self.pid * 10), "role": role,
                "executable_sha256": executable, "reaped": True, "output_closed": True, "exit_code": 0}

    @staticmethod
    def sampled(owner):
        before = {"process_id": owner["process_id"], "start_time_ticks": owner["start_time_ticks"], "rss_bytes": "4096",
                  "cpu_user_ticks": "10", "cpu_system_ticks": "2", "threads": 2, "fd_count": 5,
                  "read_bytes": "0", "write_bytes": "0"}
        after = dict(before, cpu_user_ticks="20", cpu_system_ticks="3", write_bytes="100")
        return {"before": before, "after": after, "last_live": after, "peak_rss_bytes": "4096",
                "sample_interval_millis": 100, "peak_semantics": "maximum-observed-rss-not-instantaneous-peak"}

    def batch(self, arm, case, server, owner, components):
        prefix = f"{arm}/{case['id']}/"
        plan = {**case["client_plan"], "run_id": f"{arm}-{case['id']}", "arm": arm,
                "server_process_id": server["process_id"], "endpoint": "http://127.0.0.1:5000", "token_file": "/fixture/token"}
        plan_ref = self.write(prefix + "plan.json", plan)
        request, result = canonical(plan["payload"]), expected(plan["function"], plan["payload"])
        public = {key: value for key, value in plan.items() if key not in ("token_file", "endpoint", "payload")}
        public.update(payload_sha256=sha256(request), payload_bytes=str(len(request)))
        ready = {"schema": "latent.optimization.client-readiness.v1", "run_id": plan["run_id"], "arm": arm,
                 "client_process_id": owner["process_id"], "server_process_id": server["process_id"],
                 "runtime_workers": plan["runtime_workers"], "maximum_in_flight": plan["concurrency"],
                 "started_unix_millis": "1800000000000", "connected_unix_millis": "1800000000001",
                 "connect_nanos": "1000", "startup_to_ready_nanos": "2000", "plan_sha256": plan_ref["sha256"],
                 "public_plan": public, "request_sha256": sha256(request), "request_bytes": str(len(request)),
                 "expected_output_sha256": sha256(result), "expected_output_bytes": str(len(result)),
                 "observation_hold_millis": 100}
        rows, phases = [], {}
        for phase in ("warmup", "measured"):
            origin = 1_800_000_000_000_000_123
            current = []
            for index in range(plan[phase + "_attempts"]):
                scheduled = index * (plan["schedule"].get("interval_nanos", 3_000_000) if phase == "measured" else 3_000_000)
                dispatched, completed = scheduled + 100, scheduled + 2_000_100
                deadline = scheduled + plan["budget_millis"] * 1_000_000
                absolute = (origin + deadline + 999_999) // 1_000_000
                timeout = deadline - dispatched
                header = f"{timeout}n" if timeout < 100_000_000 else f"{timeout // 1000}u"
                timeout = timeout if header[-1] == "n" else timeout // 1000 * 1000
                activation = f"{plan['run_id']}-{phase}-{index}"
                service = plan["services"][index % len(plan["services"])]
                consumption = dict.fromkeys(CONSUMPTION.split(), "0")
                consumption["wall_time_micros"] = "1000"
                if arm == "lsf":
                    consumption.update(cpu_fuel="100", peak_memory_bytes="4096")
                current.append({
                    "schema": "latent.optimization.attempt.v1", "phase": phase, "index": str(index),
                    "batch": str(index // plan["batch_size"]), "activation_id": activation, "service": service,
                    "scheduled_nanos": str(scheduled), "dispatch_nanos": str(dispatched), "completed_nanos": str(completed),
                    "dispatch_lag_nanos": "100", "request_deadline_unix_millis": str(absolute), "deadline_nanos": str(deadline),
                    "absolute_deadline_quantization_nanos": str(absolute * 1_000_000 - origin - deadline),
                    "grpc_timeout_header": header, "grpc_timeout_nanos": str(timeout),
                    "overshoot_nanos": str(max(0, completed - deadline)), "latency_nanos": "2000000",
                    "outcome": "success", "code": None, "semantic_match": True, "rpc_received": True,
                    "response": {"activation_id": activation, "revision_id": "native-reference-v1" if arm == "native" else "revision-1",
                                 "release_digest": "native-reference-v1" if arm == "native" else components[SERVICES.index(service)]["sha256"],
                                 "route_generation": "1", "consumption": consumption, "media_type": MEDIA,
                                 "payload_sha256": sha256(result), "payload_bytes": str(len(result))},
                })
            rows.extend(current)
            phases[phase] = self.phase(current, origin, plan["batch_size"])
        cgroup = {**dict.fromkeys(("cpu.max", "cpu.stat", "memory.max", "memory.current", "memory.stat",
                                  "memory.events", "cpu.pressure", "memory.pressure", "io.pressure")),
                  "scope": "runner-cgroup-shared", "process_membership": "0::/fixture"}
        summary = {"schema": "latent.optimization.client-summary.v1", "status": "complete", "readiness": ready,
                   **phases, "client_elapsed_nanos": str(3000 + sum(int(v["phase_elapsed_nanos"]) for v in phases.values())),
                   "active_tasks_at_completion": 0, "observation_hold_millis": 100}
        return {"id": case["id"], "plan": plan_ref, "readiness": self.write(prefix + "readiness.json", ready),
                "attempts": self.write(prefix + "attempts.jsonl", b"".join(canonical(row) + b"\n" for row in rows)),
                "summary": self.write(prefix + "summary.json", summary),
                "client_process": self.write(prefix + "client.json", owner),
                "resources": self.write(prefix + "resources.json", {"server": self.sampled(server), "client": self.sampled(owner),
                                                                   "cgroup": {"before": cgroup, "after": cgroup}})}

    @staticmethod
    def phase(rows, origin, size):
        return {"origin_unix_nanos": str(origin), "clock_anchor_uncertainty_nanos": "10",
                "phase_elapsed_nanos": str(max(int(row["completed_nanos"]) for row in rows) + 100),
                "counts": counts(rows),
                "batches": [{"index": str(i), "counts": counts([row for row in rows if int(row["batch"]) == i])}
                            for i in range((len(rows) + size - 1) // size)]}

    @staticmethod
    def config(arm):
        if arm == "native":
            return {"listen": "127.0.0.1:0", "tenant": TENANT, "services": SERVICES, "concurrency": 4,
                    "runtime_workers": 2, "timeout_millis": 5000, "token_kind": "public-local-benchmark-fixture"}
        return {"formatVersion": 1, "dataDirectory": "/synthetic/data", "nodeId": "optimization-node", "bind": "127.0.0.1:0",
                "workers": {"runtime": 2, "control": 2},
                "cells": [{"class": "standard", "capacity": 4, "queueCapacity": 64, "maximumMemoryBytes": 67_108_864}],
                "execution": {"maximumCpuFuel": 10_000_000_000, "maximumWallTimeMillis": 5000, "maximumLogBytes": 16_384},
                "limits": {"maximumPayloadBytes": 1_048_576, "maximumConnections": 32},
                "cache": {"entries": 4, "preparations": 1}, "catalogs": {"releaseEntries": 16, "deployments": 16},
                "retention": {"terminalEntries": 1024, "terminalTtlMillis": 30_000}, "shutdownGraceMillis": 1000,
                "credentials": [{"token": TOKEN, "subject": "optimization-reference", "tenant": TENANT, "role": "operator"}]}


class OptimizationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fixture = Fixture(self.root)

    def validate(self):
        return validate_suite(self.root / "suite.json")

    def rows(self, batch):
        return [json.loads(line) for line in (self.root / batch["attempts"]["path"]).read_bytes().splitlines()]

    def change_rows(self, batch, rows):
        self.fixture.replace(batch["attempts"], b"".join(canonical(row) + b"\n" for row in rows))

    def recount(self, batch, rows):
        summary = read_json(self.root / batch["summary"]["path"])
        plan = read_json(self.root / batch["plan"]["path"])
        for phase in ("warmup", "measured"):
            summary[phase] = Fixture.phase([row for row in rows if row["phase"] == phase],
                                           int(summary[phase]["origin_unix_nanos"]), plan["batch_size"])
        summary["client_elapsed_nanos"] = str(3000 + sum(int(summary[key]["phase_elapsed_nanos"])
                                                        for key in ("warmup", "measured")))
        self.fixture.replace(batch["summary"], summary)

    def test_complete_smoke_keeps_warmup_but_never_claims_full_reference(self):
        result = self.validate()
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(result["population_complete"])
        warm = result["runs"][0]["batches"][0]
        self.assertEqual(warm["warmup"]["counts"]["attempts"], "4")
        self.assertEqual(warm["measured"]["latency_nanos"]["count"], "12")
        self.assertEqual(warm["measured"]["latency_nanos"]["median"], "2000000")
        self.assertEqual(result["comparisons"][0]["pairs"][0]["lsf_minus_native_median_latency_nanos"], "0")

    def test_missing_attempt_and_duplicate_attempt_are_rejected_after_rehash(self):
        batch = self.fixture.suite["runs"][0]["batches"][0]
        rows = self.rows(batch)
        self.change_rows(batch, rows[:-1])
        with self.assertRaises(EvidenceError):
            self.validate()
        self.change_rows(batch, rows[:-1] + [rows[0]])
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_forged_matching_output_is_checked_against_shared_workload(self):
        batch = self.fixture.suite["runs"][0]["batches"][0]
        rows = self.rows(batch)
        rows[0]["response"]["payload_sha256"] = sha256(b"wrong")
        self.change_rows(batch, rows)
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_crossed_response_and_process_identity_are_rejected(self):
        batch = self.fixture.suite["runs"][1]["batches"][0]
        rows = self.rows(batch)
        rows[0]["response"]["release_digest"] = self.fixture.suite["identity"]["components"][1]["sha256"]
        self.change_rows(batch, rows)
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_failure_cannot_be_hidden_by_successful_phase_counts(self):
        batch = self.fixture.suite["runs"][0]["batches"][5]
        rows = self.rows(batch)
        rows[-1].update(outcome="transport-failure", code="grpc-4", semantic_match=None, rpc_received=False, response=None)
        self.change_rows(batch, rows)
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_rehashed_deadline_overshoot_and_throughput_changes_fail(self):
        batch = self.fixture.suite["runs"][0]["batches"][0]
        original = self.rows(batch)
        for field in ("deadline_nanos", "overshoot_nanos", "grpc_timeout_nanos"):
            changed = copy.deepcopy(original)
            changed[0][field] = str(int(changed[0][field]) + 1000)
            self.change_rows(batch, changed)
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                self.validate()

    def test_resource_and_cleanup_lies_fail_after_rehash(self):
        run = self.fixture.suite["runs"][1]
        value = read_json(self.root / run["cleanup"]["path"])
        value["server_shutdown"]["report"]["liveStores"] = 1
        self.fixture.replace(run["cleanup"], value)
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_altered_resource_owner_fails(self):
        batch = self.fixture.suite["runs"][0]["batches"][0]
        value = read_json(self.root / batch["resources"]["path"])
        value["client"]["after"]["process_id"] += 1
        self.fixture.replace(batch["resources"], value)
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_failed_run_and_missing_runs_never_qualify(self):
        run = self.fixture.suite["runs"][1]
        run.update(status="failed", reason="collector-failed")
        self.fixture.save()
        self.assertEqual(self.validate()["status"], "failed")
        self.fixture.suite["runs"] = []
        self.fixture.save()
        result = self.validate()
        self.assertFalse(result["population_complete"])
        self.assertEqual(result["status"], "incomplete")

    def test_empty_original_log_is_valid_but_tampering_is_not(self):
        self.validate()
        (self.root / "empty.log").write_bytes(b"forged")
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_case_and_run_order_are_not_editable_labels(self):
        self.fixture.suite["runs"].reverse()
        self.fixture.save()
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_duplicate_json_keys_and_path_traversal_are_rejected(self):
        with self.assertRaises(EvidenceError):
            decode(b'{"x":1,"x":2}')
        bad = {"path": "../outside", "sha256": sha256(b""), "bytes": "0"}
        self.fixture.refs["../outside"] = bad
        self.fixture.save()
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_budget_miss_is_not_deleted_from_measured_population(self):
        result = self.validate()
        measured = result["runs"][0]["batches"][5]["measured"]
        self.assertEqual(measured["budget_misses"], "12")
        self.assertEqual(measured["latency_nanos"]["count"], "12")
        self.assertGreater(int(measured["overshoot_nanos"]["minimum"]), 0)

    def test_actual_deadline_failure_is_retained_and_replayed(self):
        batch = self.fixture.suite["runs"][0]["batches"][5]
        rows = self.rows(batch)
        row = rows[-1]
        row.update(outcome="platform-failure", code="deadline-exceeded", semantic_match=None)
        row["response"].update(media_type=None, payload_sha256=None, payload_bytes=None)
        self.change_rows(batch, rows)
        self.recount(batch, rows)
        result = self.validate()
        measured = result["runs"][0]["batches"][5]["measured"]
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(measured["counts"]["successful"], "11")
        self.assertEqual(measured["counts"]["outcomes"]["platform-failure"], "1")
        self.assertEqual(measured["latency_nanos"]["count"], "12")

    def test_warmup_outlier_is_retained_but_not_in_measured_percentiles(self):
        batch = self.fixture.suite["runs"][0]["batches"][0]
        rows = self.rows(batch)
        row = [row for row in rows if row["phase"] == "warmup"][-1]
        row["latency_nanos"] = "500000000"
        row["completed_nanos"] = str(int(row["dispatch_nanos"]) + 500_000_000)
        self.change_rows(batch, rows)
        self.recount(batch, rows)
        replay = self.validate()["runs"][0]["batches"][0]
        self.assertEqual(replay["warmup"]["latency_nanos"]["maximum"], "500000000")
        self.assertEqual(replay["measured"]["latency_nanos"]["maximum"], "2000000")

    def test_phase_elapsed_throughput_cannot_be_recomputed_from_call_reciprocals(self):
        batch = self.fixture.suite["runs"][0]["batches"][0]
        summary = read_json(self.root / batch["summary"]["path"])
        summary["measured"]["counts"]["throughput"]["elapsed_nanos"] = "1"
        self.fixture.replace(batch["summary"], summary)
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_case_deletion_cannot_redefine_the_required_profile(self):
        self.fixture.suite["plan"]["cases"].pop()
        self.fixture.save()
        with self.assertRaises(EvidenceError):
            self.validate()

    def test_machine_schemas_match_contract_and_reject_unknown_fields(self):
        import jsonschema
        from tools.optimization_evidence.schemas import documents
        root = Path(__file__).resolve().parents[2] / "benchmarks/optimization"
        schemas = documents()
        for name, document in schemas.items():
            self.assertEqual(read_json(root / name), document)
            jsonschema.Draft202012Validator.check_schema(document)
        batch = self.fixture.suite["runs"][0]["batches"][0]
        values = {
            "suite": self.fixture.suite, "plan": self.fixture.suite["plan"], "aggregate": self.validate(),
            "client-plan": read_json(self.root / batch["plan"]["path"]),
            "client-readiness": read_json(self.root / batch["readiness"]["path"]),
            "client-summary": read_json(self.root / batch["summary"]["path"]),
            "attempt": self.rows(batch)[0], "process": read_json(self.root / batch["client_process"]["path"]),
        }
        for name, value in values.items():
            validator = jsonschema.Draft202012Validator(schemas[name + ".schema.json"])
            validator.validate(value)
            with self.subTest(name=name), self.assertRaises(jsonschema.ValidationError):
                validator.validate(dict(value, unknown=True))


if __name__ == "__main__":
    unittest.main()
