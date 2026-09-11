"""Durable control-path and scheduler timing deltas, separate from RPC latency."""

from typing import Any

from .common import digest, fields, require, text, uint


class BenchmarkManagement:
    def __init__(self, measurements):
        self.measurements = measurements
        self.routes = 0
        self.mutations = 0
        self.last_generation = 0

    def event(self, kind: str, value: Any, benchmark_input) -> bool:
        if kind == "benchmark-route":
            fields(value, "sample boundary elapsed_nanos tenant service contract function release_digest revision_id route_generation")
            require(benchmark_input is not None and uint(value["sample"]) == self.routes
                    and value["boundary"] == "directory-deployment-resolver.resolve", "invalid-benchmark-route")
            for field in ("tenant", "service", "contract", "function"):
                require(value[field] == benchmark_input[field], "benchmark-route-scope-mismatch")
            require(value["release_digest"] == benchmark_input["component_digest"], "benchmark-route-release-mismatch")
            text(value["revision_id"], 512)
            require(uint(value["route_generation"]) > 0, "invalid-benchmark-route-generation")
            self.measurements.add("route_lookup.echo", value["boundary"], "ns", [value["elapsed_nanos"]])
            self.routes += 1
            return True
        if kind != "benchmark-management":
            return False
        fields(value, "sample publish_mode apply_mode publish_elapsed_nanos apply_elapsed_nanos release_digest deployment_id previous_object_generation object_generation catalog_generation persisted_generation_matches persisted_record_sha256")
        require(benchmark_input is not None and uint(value["sample"]) == self.mutations
                and value["publish_mode"] == "idempotent-existing-release"
                and value["apply_mode"] == "same-manifest-new-generation", "invalid-benchmark-management")
        require(value["release_digest"] == benchmark_input["component_digest"]
                and value["deployment_id"] == benchmark_input["service"], "benchmark-management-object-mismatch")
        previous, current, catalog = (uint(value[key]) for key in
                                      ("previous_object_generation", "object_generation", "catalog_generation"))
        require(current == catalog > previous >= self.last_generation
                and (self.mutations == 0 or previous == self.last_generation)
                and value["persisted_generation_matches"] is True, "benchmark-management-generation-mismatch")
        digest(value["persisted_record_sha256"])
        for operation in ("publish", "apply"):
            mode = value[operation + "_mode"]
            self.measurements.add("management.repeated_" + operation,
                                  "persistent-tonic-management." + mode + ".v1", "ns",
                                  [value[operation + "_elapsed_nanos"]])
        self.last_generation = current
        self.mutations += 1
        return True


def scheduler(value: Any, expected_grants: int, boundary: str, measurements) -> None:
    fields(value, "granted_before granted_after total_wait_micros_before total_wait_micros_after grants wait_sum_micros")
    counts = {key: uint(item) for key, item in value.items()}
    require(counts["granted_after"] - counts["granted_before"] == counts["grants"] == expected_grants
            and counts["total_wait_micros_after"] - counts["total_wait_micros_before"] == counts["wait_sum_micros"],
            "benchmark-scheduler-delta-mismatch")
    measurements.add(boundary + ".scheduler_wait_sum", "local-scheduler.enqueue-to-grant.batch-sum.v1", "us",
                     [value["wait_sum_micros"]])
