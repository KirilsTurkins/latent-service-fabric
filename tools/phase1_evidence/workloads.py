"""Mixed-workload conservation and measured benchmark sample boundaries."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from .common import canonical, digest, fields, require, text, uint
from .resources import Samples, idle
from .statistics import Measurements
from .statistics import decimal_string

OUTCOMES = ("success", "domain", "trap", "fuel", "memory", "deadline", "cancel", "malformed",
            "log_denied", "log_accepted", "context", "fresh_store")
TIMING_FIELDS = ("backend_setup_micros guest_call_micros host_call_micros host_call_count "
                 "component_post_return_micros activation_resource_reclamation_micros "
                 "outcome_classification_micros reusable_proof_micros backend_total_micros").split()


class CommonWorkload:
    def __init__(self, plan: dict[str, Any], measurements: Measurements, samples: Samples):
        self.plan, self.measurements, self.samples = plan, measurements, samples
        self.publications: set[str] = set()
        self.checkpoints: list[str] = []

    def common_event(self, kind: str, payload: Any) -> bool:
        if kind == "publication":
            fields(payload, "release_digest deployment_id publish_elapsed_nanos apply_elapsed_nanos")
            release = digest(payload["release_digest"])
            require(release not in self.publications and not self.checkpoints, "invalid-publication-order")
            self.publications.add(release)
            text(payload["deployment_id"], 512)
            for operation in ("publish", "apply"):
                self.measurements.add("management." + operation, "persistent-tonic-management." + operation + ".v1", "ns",
                                      [payload[operation + "_elapsed_nanos"]])
            return True
        if kind == "checkpoint":
            fields(payload, "phase resources")
            phase = text(payload["phase"], 128)
            require(phase not in self.checkpoints or phase == "sample-complete", "duplicate-workload-checkpoint")
            self.samples.check(payload["resources"])
            idle(payload["resources"])
            self.checkpoints.append(phase)
            self.measurements.add("resident_memory." + phase, "collector-node-process.proc-status.v1", "bytes",
                                  [payload["resources"]["resources"]["process"]["residentMemoryBytes"]])
            return True
        return False


class Soak(CommonWorkload):
    def __init__(self, plan: dict[str, Any], measurements: Measurements, samples: Samples):
        super().__init__(plan, measurements, samples)
        self.attempts = Counter()
        self.batches = Counter()
        self.outcomes = Counter()

    def event(self, kind: str, payload: Any) -> None:
        if self.common_event(kind, payload):
            if kind == "checkpoint":
                require(self.checkpoints == ["before-warmup", "after-warmup", "final"][:len(self.checkpoints)], "invalid-soak-checkpoint-order")
                if payload["phase"] == "after-warmup":
                    require(self.attempts["warmup"] == self.plan["warmup_invocations"], "warmup-not-complete")
                if payload["phase"] == "final":
                    require(self.attempts["measured"] == self.plan["measured_invocations"], "measured-work-not-complete")
            return
        require(kind == "soak-batch", "unexpected-soak-event")
        fields(payload, "stage batch_index first_invocation attempts concurrency outcome_counts rpc_latency_micros consumed_cpu_fuel consumed_log_bytes peak_memory_bytes resources")
        stage = payload["stage"]
        require(stage in ("warmup", "measured") and self.checkpoints ==
                (["before-warmup"] if stage == "warmup" else ["before-warmup", "after-warmup"]), "invalid-soak-stage")
        require(uint(payload["batch_index"]) == self.batches[stage]
                and uint(payload["first_invocation"]) == self.attempts[stage], "soak-batch-sequence")
        expected_total = self.plan[stage + "_invocations"]
        expected_count = min(self.plan["batch_size"], expected_total - self.attempts[stage])
        attempts = uint(payload["attempts"])
        require(0 < attempts == expected_count and uint(payload["concurrency"]) == (1 if stage == "warmup" else self.plan["concurrency"]), "soak-batch-size")
        require(isinstance(payload["rpc_latency_micros"], list) and len(payload["rpc_latency_micros"]) == attempts, "soak-latency-count")
        outcomes = payload["outcome_counts"]
        require(isinstance(outcomes, dict) and set(outcomes) <= set(OUTCOMES), "invalid-soak-outcome-set")
        counts = {key: uint(value) for key, value in outcomes.items()}
        require(sum(counts.values()) == attempts, "soak-outcome-conservation")
        if stage == "measured" or self.plan["profile"] == "full":
            require(attempts % 20 == 0 and counts == {name: attempts // 20 * (9 if name == "success" else 1) for name in OUTCOMES}, "soak-mixed-cycle-mismatch")
            if stage == "measured":
                self.outcomes.update(counts)
        else:
            first, end = self.attempts[stage], self.attempts[stage] + attempts
            contexts = int(first <= 1 < end)
            expected = {"success": attempts - contexts}
            if contexts:
                expected["context"] = contexts
            require(counts == expected, "soak-warmup-outcome-mismatch")
        for key in ("consumed_cpu_fuel", "consumed_log_bytes", "peak_memory_bytes"):
            uint(payload[key])
        require(uint(payload["peak_memory_bytes"]) <= 64 * 1024 * 1024, "soak-memory-budget-exceeded")
        self.samples.check(payload["resources"])
        idle(payload["resources"])
        self.measurements.add(stage + ".rpc_latency", "persistent-tonic-invocation.round-trip.v1", "us", payload["rpc_latency_micros"])
        if stage == "measured":
            self.measurements.add("resident_memory.measured_batch", "collector-node-process.proc-status.v1", "bytes",
                                  [payload["resources"]["resources"]["process"]["residentMemoryBytes"]])
        self.attempts[stage] += attempts
        self.batches[stage] += 1

    def finish(self, footer: dict[str, Any]) -> None:
        require(len(self.publications) == 3 and self.checkpoints == ["before-warmup", "after-warmup", "final"], "incomplete-soak-profile")
        result = fields(footer["workload_result"], "warmup_invocations measured_invocations measured_batches cycle_length outcome_counts work")
        for stage in ("warmup", "measured"):
            require(uint(result[stage + "_invocations"]) == self.attempts[stage] == self.plan[stage + "_invocations"], "soak-summary-attempts")
        require(uint(result["measured_batches"]) == self.batches["measured"]
                and uint(result["cycle_length"]) == 20, "soak-summary-batches")
        require({key: uint(value) for key, value in result["outcome_counts"].items()} == self.outcomes, "soak-summary-outcomes")
        require(canonical(result["work"]) == canonical(footer["work"])
                and uint(footer["work"]["invoke_attempts"]) == sum(self.attempts.values()), "soak-final-work-mismatch")
        from .policy import reclamation
        reclamation(self.samples.values, self.plan["profile"])


class Benchmark(CommonWorkload):
    def __init__(self, plan: dict[str, Any], measurements: Measurements, samples: Samples):
        super().__init__(plan, measurements, samples)
        self.calls = Counter()
        self.cases = Counter()
        self.prepares = Counter()
        self.ids: set[str] = set()
        self.queues = 0
        self.input = None
        from .management import BenchmarkManagement
        self.management = BenchmarkManagement(measurements)
        self.batch_timings: dict[str, list[int]] = {"offered_capacity_rpc": [], "cancel_released_queue_rpc": []}
        self.boundaries = {"cold_first_rpc": 1, "warm_rpc": 1, "offered_capacity_rpc": 2,
                           "cancel_released_queue_rpc": 5}
        for cause in ("domain", "trap", "fuel", "memory", "deadline", "cancel"):
            self.boundaries["fault_" + cause] = 1
            self.boundaries["recovery_" + cause] = 1

    def event(self, kind: str, payload: Any) -> None:
        if self.management.event(kind, payload, self.input):
            return
        if kind == "benchmark-input":
            require(self.input is None and not self.calls and isinstance(payload, dict), "invalid-benchmark-input")
            self.input = payload
            return
        if kind == "benchmark-batch":
            fields(payload, "boundary sample attempted_invocations successful_invocations cancelled_invocations elapsed_micros offered_concurrency includes_retained_status_validation scheduler")
            boundary = payload["boundary"]
            require(boundary in self.batch_timings, "invalid-batch-boundary")
            expected = (2, 2, 0, 2) if boundary == "offered_capacity_rpc" else (5, 3, 2, 5)
            require(tuple(uint(payload[key]) for key in ("attempted_invocations", "successful_invocations", "cancelled_invocations", "offered_concurrency")) == expected
                    and payload["includes_retained_status_validation"] is True, "invalid-concurrent-batch")
            require(uint(payload["sample"]) == len(self.batch_timings[boundary]) and uint(payload["elapsed_micros"]) > 0,
                    "invalid-batch-timing")
            self.batch_timings[boundary].append(uint(payload["elapsed_micros"]))
            from .management import scheduler
            scheduler(payload["scheduler"], expected[0], boundary, self.measurements)
            self.measurements.add(boundary + ".batch_elapsed", "concurrent-rpc-with-status-and-control.v1", "us", [payload["elapsed_micros"]])
            return
        if self.common_event(kind, payload):
            return
        if kind == "benchmark-prepare":
            fields(payload, "sample operation elapsed_micros cache_before cache_after")
            operation = payload["operation"]
            require(operation in ("initial", "cold", "cache_hit") and uint(payload["sample"]) == self.prepares[operation], "benchmark-prepare-sequence")
            require(isinstance(payload["cache_before"], dict) and isinstance(payload["cache_after"], dict), "missing-preparation-cache-observations")
            before = fields(payload["cache_before"], "entries hits misses preparing source_bytes compiled_image_bytes")
            after = fields(payload["cache_after"], "entries hits misses preparing source_bytes compiled_image_bytes")
            for snapshot in (before, after):
                for value in snapshot.values():
                    uint(value)
                require(uint(snapshot["preparing"]) == 0, "benchmark-preparation-still-live")
            if operation in ("initial", "cold"):
                require(uint(after["misses"]) == uint(before["misses"]) + 1
                        and uint(after["entries"]) == uint(before["entries"]) + 1, "cold-preparation-not-measured")
                if operation == "initial":
                    require(not self.calls and all(uint(before[key]) == 0 for key in before), "initial-preparation-not-engine-cold")
            else:
                require(uint(after["hits"]) == uint(before["hits"]) + 1
                        and after["misses"] == before["misses"] and after["entries"] == before["entries"], "cache-hit-not-measured")
            self.measurements.add("prepare." + operation, "wasmtime.prepare-for-use.v1", "us", [payload["elapsed_micros"]])
            self.prepares[operation] += 1
        elif kind == "benchmark-call":
            fields(payload, "boundary sample invocation")
            boundary = text(payload["boundary"], 128)
            require(boundary in self.boundaries or boundary == "warmup", "invalid-benchmark-boundary")
            require(uint(payload["sample"]) == self.calls[boundary] // self.boundaries.get(boundary, 1), "benchmark-call-sequence")
            self.invocation(boundary, payload["invocation"])
            self.calls[boundary] += 1
        elif kind == "benchmark-queue":
            fields(payload, "sample active_before_release queued_before_release resources")
            require(uint(payload["sample"]) == self.queues and uint(payload["active_before_release"]) == 2
                    and uint(payload["queued_before_release"]) == 3, "benchmark-queue-sequence")
            self.samples.check(payload["resources"])
            inventory = payload["resources"]["inventory"]
            require(uint(inventory["queueDepth"]) == 3 and sum(cell["active"] for cell in inventory["cellCapacity"]) == 2, "benchmark-queue-observation")
            self.queues += 1
        else:
            require(False, "unexpected-benchmark-event")

    def invocation(self, boundary: str, value: Any) -> None:
        fields(value, "activation_id case outcome rpc_latency_micros consumption timing retained_consumption_matches")
        activation = text(value["activation_id"], 512)
        require(activation not in self.ids and value["retained_consumption_matches"] is True, "invalid-benchmark-activation")
        self.ids.add(activation)
        require(value["case"] in OUTCOMES, "invalid-benchmark-case")
        if boundary.startswith("fault_"):
            require(value["case"] == boundary.removeprefix("fault_"), "benchmark-fault-case-mismatch")
        elif boundary == "cancel_released_queue_rpc":
            require(value["case"] in ("success", "cancel"), "benchmark-queue-case-mismatch")
        else:
            require(value["case"] == "success", "benchmark-success-case-mismatch")
        self.cases[(boundary, value["case"])] += 1
        expected = {"domain": "declared-error", "trap": "guest-trap", "fuel": "resource-exhausted", "memory": "resource-exhausted",
                    "deadline": "deadline-exceeded", "cancel": "cancelled"}.get(value["case"], "success")
        require(value["outcome"] == expected, "benchmark-outcome-mismatch")
        consumption = fields(value["consumption"], "cpu_fuel peak_memory_bytes wall_time_micros log_bytes")
        for item in consumption.values():
            uint(item)
        require(uint(consumption["cpu_fuel"]) > 0 and uint(consumption["peak_memory_bytes"]) > 0,
                "benchmark-guest-did-not-execute")
        if value["case"] == "fuel":
            require(uint(consumption["cpu_fuel"]) <= 50_000, "benchmark-fuel-exceeds-grant")
        if value["case"] == "memory":
            require(uint(consumption["peak_memory_bytes"]) <= 4 * 1024 * 1024, "benchmark-memory-exceeds-grant")
        self.measurements.add(boundary + ".rpc_latency", "persistent-tonic-invocation.round-trip.v1", "us", [value["rpc_latency_micros"]])
        timing = value["timing"]
        if timing is None:
            require(value["case"] in ("deadline", "cancel"), "missing-backend-timing")
            return
        fields(timing, " ".join(TIMING_FIELDS))
        for key, item in timing.items():
            uint(item)
            unit = "count" if key == "host_call_count" else "us"
            self.measurements.add(boundary + "." + key, "generic-wasmtime." + key + ".v1", unit, [item])
        require(uint(timing["host_call_micros"]) <= uint(timing["guest_call_micros"]), "host-call-subset-exceeded")

    def finish(self, footer: dict[str, Any]) -> None:
        result = fields(footer["workload_result"], "samples_per_boundary warmup_invocations planned_invoke_attempts actual_invoke_attempts offered_capacity_concurrency queue_holder_count queue_waiter_count work")
        count = self.plan["benchmark_samples"]
        require(self.input is not None and len(self.publications) == 3 and uint(result["samples_per_boundary"]) == count,
                "incomplete-benchmark-profile")
        require(self.prepares == {"initial": 1, "cold": count, "cache_hit": count} and self.queues == count, "benchmark-boundary-sample-count")
        require(self.management.routes == self.management.mutations == count, "missing-control-boundary-samples")
        require(all(len(values) == count for values in self.batch_timings.values()), "missing-throughput-batches")
        require(self.cases[("cancel_released_queue_rpc", "success")] == count * 3
                and self.cases[("cancel_released_queue_rpc", "cancel")] == count * 2, "benchmark-queue-outcome-count")
        warmup = 1 if self.plan["profile"] == "smoke" else 40
        require(self.calls == dict({key: count * multiplicity for key, multiplicity in self.boundaries.items()}, warmup=warmup),
                "missing-benchmark-boundary")
        require(self.checkpoints == ["before-warmup", "after-warmup"] + ["sample-complete"] * count + ["final"],
                "benchmark-checkpoint-count")
        require(uint(result["warmup_invocations"]) == warmup
                and uint(result["planned_invoke_attempts"]) == warmup + count * 21
                and uint(result["offered_capacity_concurrency"]) == 2
                and uint(result["queue_holder_count"]) == 2 and uint(result["queue_waiter_count"]) == 3,
                "benchmark-planned-work-mismatch")
        require(uint(result["actual_invoke_attempts"]) == uint(result["planned_invoke_attempts"])
                == uint(footer["work"]["invoke_attempts"]), "benchmark-final-work-mismatch")
        require(canonical(result["work"]) == canonical(footer["work"]), "benchmark-summary-work-mismatch")
        require(len(self.ids) == uint(result["actual_invoke_attempts"]), "unobserved-benchmark-invocations")

    def throughput(self) -> dict[str, Any]:
        result = {}
        for boundary, values in self.batch_timings.items():
            if not values:
                continue
            attempted, successful = (2, 2) if boundary == "offered_capacity_rpc" else (5, 3)
            total = sum(values)
            result[boundary] = {"boundary": "concurrent-rpc-with-status-and-control.v1",
                "unit": "invocations_per_second", "batches": str(len(values)), "elapsed_micros": str(total),
                "attempted_invocations": str(attempted * len(values)), "successful_invocations": str(successful * len(values)),
                "attempted_per_second": decimal_string((Decimal(attempted * len(values)) * 1_000_000 / total).quantize(Decimal("0.000001"))),
                "successful_per_second": decimal_string((Decimal(successful * len(values)) * 1_000_000 / total).quantize(Decimal("0.000001")))}
        return result
