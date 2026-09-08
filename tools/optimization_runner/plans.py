"""Committed workload controls; changing these creates a different comparison."""
from __future__ import annotations

TOKEN = "optimization-benchmark-local-fixture-token-v1"
TENANT = "optimization"
SERVICE = "optimization/workloads"
CONTRACT = "optimization:benchmark/workloads@0.1.0"
SERVICES = [SERVICE] + [f"{SERVICE}-{index}" for index in range(1, 5)]


def cases(profile: str) -> list[dict]:
    if profile not in ("smoke", "full"):
        raise ValueError("unknown optimization profile")
    full = profile == "full"
    base = {
        "schema": "latent.optimization.client-plan.v1",
        "tenant": TENANT, "services": [SERVICE], "contract": CONTRACT, "route": None,
        "function": "echo", "payload": ["optimization-reference-v1"],
        "warmup_attempts": 40 if full else 4, "measured_attempts": 400 if full else 12,
        "batch_size": 100 if full else 12,
        "concurrency": 1, "runtime_workers": 2, "schedule": {"mode": "closed-loop"},
        "budget_millis": 1000, "cpu_fuel": 10_000_000_000,
        "memory_bytes": 67_108_864, "log_bytes": 16_384,
        "connect_timeout_millis": 5000, "response_timeout_millis": 5000,
        "maximum_output_bytes": 32 * 1024 * 1024,
    }
    result = []

    def add(identifier: str, **changes: object) -> None:
        result.append({"id": identifier, "client_plan": {**base, **changes}})

    add("warm-echo")
    add("compute", function="compute", payload=[17, 10_000])
    add("transform", function="transform", payload=[{
        "label": "structured-reference", "bytes": list(range(256)) * 4,
        "values": list(range(64)),
    }])
    add("payload-64k", payload=["x" * 65_536])
    # The current per-transfer lifting allowance is128KiB, tighter than the
    # configured1MiB RPC ceiling and256KiB JSON string cap. Keep this comparison
    # within the effective limit; record all three limits in the report.
    add("payload-near-limit", payload=["x" * (120 * 1024)],
        warmup_attempts=4, measured_attempts=40 if full else 2)
    for budget in (1, 2, 5, 10):
        add(f"budget-{budget}ms", budget_millis=budget)
    for concurrency in (4, 16, 64):
        add(f"concurrency-{concurrency}", concurrency=concurrency)
    for rate in (250, 1000, 4000):
        add(f"rate-{rate}", concurrency=64,
            schedule={"mode": "scheduled", "interval_nanos": 1_000_000_000 // rate})
    add("cache-working-set", services=SERVICES, warmup_attempts=5,
        measured_attempts=100 if full else 10, budget_millis=5000)
    return result


def plan(profile: str) -> dict:
    return {
        "schema": "latent.optimization.plan.v1", "profile": profile,
        "repetitions": 7 if profile == "full" else 1,
        "scenarios": ["cold-restart"], "cases": cases(profile),
        "maximum_run_seconds": "7200" if profile == "full" else "300",
        "maximum_artifact_bytes": str(1024 * 1024 * 1024),
    }
