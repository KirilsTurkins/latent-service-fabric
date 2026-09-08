"""Measurement-specific invariants are derived from retained observations."""

from __future__ import annotations

from typing import Any

from .common import canonical, fields, require, uint
from .resources import Samples, fixed_topology, idle
from .statistics import Measurements


class Profile:
    def __init__(self, plan: dict[str, Any], measurements: Measurements, samples: Samples):
        self.kind = plan["kind"]
        if self.kind == "scale":
            self.validator = Scale(plan, measurements, samples)
        else:
            from .workloads import Benchmark, Soak
            self.validator = (Soak if self.kind == "soak" else Benchmark)(plan, measurements, samples)

    def event(self, kind: str, payload: Any) -> None:
        self.validator.event(kind, payload)

    def finish(self, footer: dict[str, Any]) -> None:
        self.validator.finish(footer)


class Scale:
    def __init__(self, plan: dict[str, Any], measurements: Measurements, samples: Samples):
        self.plan, self.measurements, self.samples = plan, measurements, samples
        self.baseline = None
        self.checkpoints: list[int] = []
        self.summary = None

    def event(self, kind: str, payload: Any) -> None:
        require(self.summary is None, "scale-event-after-result")
        if kind == "scale-baseline":
            require(self.baseline is None and not self.checkpoints, "duplicate-scale-baseline")
            self.samples.check(payload)
            idle(payload, dormant=True)
            self.baseline = payload
        elif kind == "scale-checkpoint":
            fields(payload, "registered_releases registered_deployments publish_elapsed_nanos apply_elapsed_nanos route_lookup sample")
            require(self.baseline is not None and len(self.checkpoints) < len(self.plan["scale_counts"]), "unexpected-scale-checkpoint")
            count = self.plan["scale_counts"][len(self.checkpoints)]
            require(uint(payload["registered_releases"]) == count and uint(payload["registered_deployments"]) == count,
                    "scale-target-mismatch")
            lookup = fields(payload["route_lookup"], "boundary unit samples sample_count")
            require(lookup["boundary"] == "directory-deployment-resolver.resolve" and lookup["unit"] == "ns", "route-measurement-boundary")
            require(isinstance(lookup["samples"], list) and len(lookup["samples"]) == self.plan["route_samples"]
                    and uint(lookup["sample_count"]) == len(lookup["samples"]), "route-sample-count")
            self.measurements.add(f"route_lookup.scale_{count}", lookup["boundary"], "ns", lookup["samples"])
            for name in ("publish", "apply"):
                uint(payload[name + "_elapsed_nanos"])
            sample = payload["sample"]
            self.samples.check(sample)
            idle(sample, dormant=True)
            require(canonical(fixed_topology(sample)) == canonical(fixed_topology(self.baseline)), "dormant-topology-growth")
            base_fd = uint(self.baseline["resources"]["process"]["openFileDescriptors"])
            require(uint(sample["resources"]["process"]["openFileDescriptors"]) == base_fd, "dormant-descriptor-growth")
            self.measurements.add(f"resident_memory.scale_{count}", "collector-node-process.proc-status.v1", "bytes",
                                  [sample["resources"]["process"]["residentMemoryBytes"]])
            self.checkpoints.append(count)
        elif kind == "scale-summary":
            self.summary = fields(payload, "registered_releases registered_deployments checkpoint_count route_samples dormant_topology_constant")
        else:
            require(False, "unexpected-scale-event")

    def finish(self, footer: dict[str, Any]) -> None:
        require(self.baseline is not None and self.checkpoints == self.plan["scale_counts"] and self.summary is not None,
                "incomplete-scale-profile")
        require(canonical(self.summary) == canonical(footer["workload_result"]), "scale-summary-mismatch")
        require(uint(self.summary["registered_releases"]) == self.checkpoints[-1]
                and uint(self.summary["registered_deployments"]) == self.checkpoints[-1]
                and uint(self.summary["checkpoint_count"]) == len(self.checkpoints)
                and uint(self.summary["route_samples"]) == len(self.checkpoints) * self.plan["route_samples"]
                and self.summary["dormant_topology_constant"] is True, "invalid-scale-summary")
        require(uint(footer["work"]["invoke_attempts"]) == 0
                and uint(footer["work"]["commands"]) >= self.checkpoints[-1], "invalid-dormant-work")
