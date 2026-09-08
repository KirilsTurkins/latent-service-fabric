"""Tiny synthetic evidence; these are validator fixtures, never measured baselines."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.phase1_evidence.common import canonical, reference, sha256


def plan(kind="scale", repetition=1):
    return {"schema": "latent.phase1.measurement-plan.v1", "profile": "smoke", "kind": kind,
            "repetition": repetition, "scale_counts": [2, 4], "route_samples": 16,
            "warmup_invocations": 4, "measured_invocations": 20, "batch_size": 20,
            "concurrency": 2, "benchmark_samples": 4, "maximum_run_seconds": "90",
            "maximum_output_bytes": "8388608"}


def identity():
    return {"schema": "latent.phase1.measurement-identity.v1",
            "source": {"commit": "a" * 40, "tree": "b" * 40, "dirty": False, "cargo_lock_sha256": sha256(b"lock")},
            "build": {"profile": "debug", "rustc": "rustc test", "cargo": "cargo test", "wasmtime": "47.0.3",
                      "target": "x86_64-unknown-linux-gnu", "overrides": {"recipe": "synthetic-test"}},
            "environment": {"os": "Linux", "arch": "x86_64", "kernel": "synthetic", "cpu_model": "synthetic cpu",
                "logical_cpus": "2", "memory_total_bytes": "1073741824", "virtualization": {"container": False},
                "allocator": {"LD_PRELOAD": "unset"}, "cpu_policy": {}, "load_before": [0.0, 0.0, 0.0]},
            "binary": {"sha256": sha256(b"binary"), "bytes": "6"},
            "fixtures": [{"name": name, "sha256": sha256(name.encode()), "bytes": str(len(name))}
                         for name in ("echo", "generic", "capabilities")]}


def work(invokes=0, commands=8):
    return {"commands": str(commands), "invoke_attempts": str(invokes), "budget_exhausted": False}


def ownership():
    return {"cancellation": {"active_registrations": "0"},
        "journal": {"active": "0", "terminal": "0", "reserved_bytes": "0", "retained_bytes": "0", "evicted": "0",
                    "begun": "0", "completed": "0", "maximum_active": "64", "maximum_terminal": "64",
                    "maximum_record_bytes": "65536", "maximum_retained_bytes": "4194304"},
        "observer": {"active_correlations": "0", "maximum_active_correlations": "64", "received": "0", "completed": "0",
                     "guest_logs": "0", "observations_dropped": "0", "capacity_drops": "0", "invalid_records": "0",
                     "unknown_correlations": "0", "submission_errors": "0", "panics": "0"},
        "sink": {"entries": "0", "retained_bytes": "0", "maximum_entries": "128", "maximum_bytes": "1048576",
                 "evicted_entries": "0", "dropped_oversized": "0"},
        "pipeline": {"queue_depth": "0", "queue_capacity": "256", "accepted": "0", "exported": "0",
                     "dropped_queue_full": "0", "dropped_queue_closed": "0", "dropped_invalid_record": "0",
                     "sink_failures": "0", "sink_timeouts": "0", "flush_timeouts": "0", "shutdown_timeouts": "0", "worker_panics": "0"}}


def sample(label, tick=1, *, active=0, queued=0, rss=1024):
    cell = {"class": "standard", "total": 2, "available": 2-active, "active": active, "quarantined": 0,
            "queueDepth": queued, "queuedTenants": min(2, queued), "queueCapacity": 3, "accepting": True,
            "granted": "0", "rejected": "0", "cancellations": "0", "expired": "0", "totalWaitMicros": "0", "maxWaitMicros": "0"}
    return {"label": label, "started_micros": str(tick*10), "finished_micros": str(tick*10+1),
        "resources": {"identity": {"processId": 123, "startTimeTicks": "77"},
            "process": {"processId": 123, "residentMemoryBytes": str(rss), "threadCount": "4", "openFileDescriptors": "8", "socketCount": "2"},
            "taskCount": "4", "uniqueSocketCount": "2", "listeningTcpSocketCount": "1", "descendants": [], "sampleAttempts": 1},
        "inventory": {"nodeId": "synthetic-node", "observedAtUnixMillis": "100", "queueDepth": str(queued), "routeGeneration": "0",
            "cellCapacity": [cell], "ready": True, "healthy": True,
            "cacheSummary": {"available": True, "entries": "0", "maximumEntries": "4", "sourceBytes": "0", "maximumSourceBytes": "67108864",
                "metadataBytes": "0", "maximumMetadataBytes": "16777216", "compiledImageBytes": "0", "maximumCompiledImageBytes": "268435456",
                "preparing": "0", "maximumConcurrentPreparations": "1", "preparingSourceBytes": "0", "preparingMetadataBytes": "0",
                "hits": "0", "misses": "0", "evictions": "0", "invalidations": "0"},
            "quotas": {"retainedTenants": "0", "usage": {"activeActivations": active, "queuedActivations": queued,
                       "reservedCpuFuel": "0", "reservedMemoryBytes": "0"}},
            "topology": {"available": True, "complete": True, "entries": [{"name": "runtime", "kind": "worker",
                         "ownership": "node-fixed", "configuredCount": "4", "activeCount": "4", "attributes": {}}]}},
        "backend": {"active_invocations": str(active), "live_stores": str(active), "live_host_states": str(active),
                    "live_component_instances": str(active), "live_temporary_buffers": "0", "live_cancellation_probes": "0", "stores_created": "0"},
        "ownership": ownership(), "work": work()}


def shutdown():
    from tools.phase1_evidence.resources import ZERO_SHUTDOWN_FIELDS
    return dict({key: 0 for key in ZERO_SHUTDOWN_FIELDS}, clean=True, quarantinedCells=0,
                telemetryRetainedEntries=0, telemetryFlushed=True, epochHelperJoined=True)


def rows(kind="scale", repetition=1):
    result = []
    def emit(name, payload):
        result.append({"schema": "latent.phase1.measurement.raw.v1", "sequence": str(len(result)), "kind": name, "payload": payload})
    emit("header", {"profile": "smoke", "workload": kind, "repetition": str(repetition), "plan": plan(kind, repetition),
                    "config": {"formatVersion": 1, "dataDirectory": "data"}, "identity": identity()})
    emit("fixture-inputs", fixture_documents()[0])
    from tools.phase1_evidence.provenance import BOUNDARIES
    emit("startup", {"unit": "ns", "catalog_open_nanos": "10", "node_start_nanos": "20", "client_connect_nanos": "10",
                     "boundaries": BOUNDARIES, "excluded": ["fixture-loading", "runtime-construction"]})
    if kind == "scale":
        emit("scale-baseline", sample("baseline", 1))
        for index, count in enumerate((2, 4), 2):
            emit("scale-checkpoint", {"registered_releases": str(count), "registered_deployments": str(count),
                "publish_elapsed_nanos": "100", "apply_elapsed_nanos": "50", "route_lookup": {
                    "boundary": "directory-deployment-resolver.resolve", "unit": "ns", "samples": [str(x) for x in range(16)], "sample_count": "16"},
                "sample": sample("scale", index)})
        summary = {"registered_releases": "4", "registered_deployments": "4", "checkpoint_count": "2", "route_samples": "32", "dormant_topology_constant": True}
        emit("scale-summary", summary)
        final_work = work()
    elif kind == "soak":
        for name in ("echo", "generic", "capabilities"):
            emit("publication", {"release_digest": sha256(name.encode()), "deployment_id": name,
                                 "publish_elapsed_nanos": "100", "apply_elapsed_nanos": "50"})
        emit("checkpoint", {"phase": "before-warmup", "resources": sample("before-warmup", 1)})
        emit("soak-batch", batch("warmup", {"success": "3", "context": "1"}, 4, 2))
        emit("checkpoint", {"phase": "after-warmup", "resources": sample("after-warmup", 3)})
        counts = {name: "1" for name in ("domain", "trap", "fuel", "memory", "deadline", "cancel", "malformed", "log_denied", "log_accepted", "context", "fresh_store")}
        counts["success"] = "9"
        emit("soak-batch", batch("measured", counts, 20, 4))
        emit("checkpoint", {"phase": "final", "resources": sample("final", 5)})
        final_work = work(24, 60)
        summary = {"warmup_invocations": "4", "measured_invocations": "20", "measured_batches": "1",
                   "cycle_length": "20", "outcome_counts": counts, "work": final_work}
    elif kind == "benchmark":
        from tools.tests.phase1_benchmark_fixtures import populate
        summary, final_work = populate(emit)
    else:
        raise ValueError("unsupported synthetic kind")
    emit("data-cleanup", {"removed": True})
    emit("summary", {"status": "passed", "reason": None, "event_count": str(len(result)-1), "elapsed_nanos": "1000000",
                     "shutdown": shutdown(), "work": final_work, "workload_result": summary})
    return result


def batch(stage, outcomes, attempts, tick):
    return {"stage": stage, "batch_index": "0", "first_invocation": "0", "attempts": str(attempts),
            "concurrency": "1" if stage == "warmup" else "2", "outcome_counts": outcomes,
            "rpc_latency_micros": ["5"] * attempts, "consumed_cpu_fuel": "100", "consumed_log_bytes": "10",
            "peak_memory_bytes": "1024", "resources": sample(stage, tick)}


def save_rows(path, values):
    for name, value in fixture_documents()[1].items():
        destination = path.parent / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(canonical(value))
    path.write_bytes(b"".join(canonical(row) + b"\n" for row in values))


def fixture_documents():
    documents, fixtures = {}, []
    for name in ("echo", "generic", "capabilities"):
        tenant, service = ("examples" if name == "echo" else "tests"), "measurement-" + name
        contract = f"{tenant}:{name}/api@0.1.0"
        component = sha256(name.encode())
        values = {
            "capsule": {"metadata": {"tenant": tenant, "name": service}, "component": {"digest": component}, "exports": [contract]},
            "deployment": {"metadata": {"tenant": tenant, "name": service}, "spec": {"release": component, "service": service}},
            "contracts": {"format_version": 1, "contracts": [{"interfaces": [{"id": contract}]}]},
        }
        row = {"name": name, "tenant": tenant, "service": service, "component_sha256": component, "component_bytes": str(len(name))}
        for role, value in values.items():
            path = f"fixture-inputs/{name}-{role}.json"
            documents[path] = value
            encoded = canonical(value)
            row[role] = {"path": path, "sha256": sha256(encoded), "bytes": str(len(encoded))}
        fixtures.append(row)
    return {"fixtures": fixtures}, documents


def suite(root: Path, kinds=("scale",), repetitions=1):
    document = {"schema": "latent.phase1.measurement-suite.v1", "profile": "smoke", "identity": identity(),
                "plans": {kind: plan(kind) for kind in kinds}, "runs": [], "artifacts": []}
    for kind in kinds:
        for repetition in range(1, repetitions + 1):
            directory = root / f"{kind}-{repetition:02}"
            directory.mkdir(parents=True)
            raw = directory / "measurements.jsonl"
            save_rows(raw, rows(kind, repetition))
            extra = {"identity.json": identity(), "host-after.json": identity()["environment"],
                     "process.json": {"process_id": 123, "start_time_ticks": "77", "reaped": True, "output_closed": True, "exit_code": 0},
                     "parent-cleanup.json": {"removed": True}}
            for name, value in extra.items():
                (directory / name).write_bytes(canonical(value))
            report = reference(raw, root)
            document["runs"].append({"kind": kind, "repetition": repetition, "status": "passed", "reason": None, "report": report})
            document["artifacts"].extend(reference(path, root) for path in sorted(directory.rglob("*")) if path.is_file())
    path = root / "suite.json"
    path.write_bytes(canonical(document))
    return path


def refresh(root: Path, document):
    for item in document["artifacts"]:
        item.update(reference(root / item["path"], root))
    for run in document["runs"]:
        if run["report"]:
            run["report"].update(reference(root / run["report"]["path"], root))
    (root / "suite.json").write_bytes(canonical(document))
