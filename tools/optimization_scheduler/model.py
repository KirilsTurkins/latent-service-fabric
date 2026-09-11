"""Finite scheduler selections, populations and immutable resource limits."""
from tools.optimization_evidence.common import require

PREFIX = "latent.optimization.scheduler-"
COLLECTOR = "local::measurement::phase1_scheduler_collector"
SYMBOL = "latent_scheduler::local::measurement::measured_cancel_and_settle"
CASES = ("closed-one", "saturated-one", "saturated-many", "reference-many", "cancel-one", "cancel-many")
VARIANTS = ("control", "candidate")
MAX_RAW_BYTES = 32 * 1024**2
MAX_AGGREGATE_BYTES = 8 * 1024**2
MAX_TOTAL_BYTES = 1024**3
MAX_FOLDED_BYTES = 64 * 1024**2


def plan(profile, variant="control", case="closed-one", mode="normal"):
    require(profile in ("smoke", "full") and variant in VARIANTS and case in CASES,
            "scheduler-plan-selector")
    require(mode == "normal" or mode == "allocation" and case == "cancel-many", "scheduler-plan-mode")
    return {"schema": PREFIX + "plan.v1", "profile": profile, "variant": variant,
            "case": case, "mode": mode, "observation_hold_millis": 100}


def validate_plan(value):
    require(isinstance(value, dict) and set(value) == {"schema", "profile", "variant", "case", "mode", "observation_hold_millis"},
            "scheduler-plan-fields")
    require(type(value["observation_hold_millis"]) is int and value == plan(value["profile"], value["variant"], value["case"], value["mode"]),
            "scheduler-plan-changed")
    return value


def population(profile):
    for index, case in enumerate(CASES):
        for variant in VARIANTS if index % 2 == 0 else tuple(reversed(VARIANTS)):
            yield plan(profile, variant, case)
    for variant in VARIANTS:
        yield plan(profile, variant, "cancel-many", "allocation")


def counts(selected):
    validate_plan(selected)
    storm = selected["case"].startswith("cancel-")
    if storm:
        return {"logical_offers": 68, "warmup_offers": 0, "measured_offers": 68,
                "holders": 4, "queued_offers": 64, "planned_cancel_calls": 32,
                "planned_release_calls": 36, "shutdown_calls": 1}
    full = selected["profile"] == "full"
    measured = {"closed-one": 128 if full else 16, "saturated-one": 2000 if full else 200,
                "saturated-many": 2000 if full else 200, "reference-many": 200 if full else 20}[selected["case"]]
    return {"logical_offers": measured + 8, "warmup_offers": 8, "measured_offers": measured,
            "holders": 0, "queued_offers": 0, "planned_cancel_calls": 0,
            "planned_release_calls": None, "shutdown_calls": 1}


def tenants(selected):
    return 32 if selected["case"] in ("saturated-many", "reference-many") else 8 if selected["case"] == "cancel-many" else 1


def settings(selected):
    expected = counts(selected)
    storm = selected["case"].startswith("cancel-")
    return {"tenants": tenants(selected), "measured_offers": expected["measured_offers"],
            "warmup_offers": expected["warmup_offers"],
            "rate_per_second": 1000 if selected["case"].startswith("saturated-") else 100 if selected["case"] == "reference-many" else 0,
            "pending_capacity": 1 if selected["case"] == "closed-one" else 64,
            "queue_capacity": 64 if storm else 32, "cells": 4, "hold_millis": 10,
            "original_budget_millis": 1000, "counters_enabled": storm and selected["mode"] == "normal"}


def cancelled(queued_ordinal, tenant_count):
    require(type(queued_ordinal) is int and 0 <= queued_ordinal < 64 and tenant_count in (1, 8), "scheduler-cancel-selection")
    return (queued_ordinal // tenant_count) % 8 in (0, 3, 4, 7)


def run_id(ordinal, selected):
    return f"owner-{ordinal:02}-{selected['case']}-{selected['variant']}-{selected['mode']}"


def suite_plan(profile):
    plan(profile)
    return {"schema": PREFIX + "suite-plan.v1", "profile": profile, "children": 14,
            "logical_offers": "9128" if profile == "full" else "1344",
            "load_offers": "8720" if profile == "full" else "936", "storm_offers": "272", "profile_offers": "136",
            "normal_children": 12, "allocation_children": 2,
            "order": "case-order-alternating-first-arm-then-control-candidate-profile",
            "normal_timeout_seconds": 60, "allocation_timeout_seconds": 180,
            "profile_report_timeout_seconds": 120, "suite_timeout_seconds": 1800,
            "maximum_raw_bytes": str(MAX_RAW_BYTES), "maximum_aggregate_bytes": str(MAX_AGGREGATE_BYTES),
            "maximum_total_bytes": str(MAX_TOTAL_BYTES), "maximum_folded_bytes": str(MAX_FOLDED_BYTES),
            "maximum_files": 4096, "maximum_profile_records": 4_000_000,
            "measured_symbol": SYMBOL, "counter_scope": "normal-storm-32-cancellations-and-original-settlements-only",
            "allocation_boundary": "32-cancel-and-32-original-queued-future-settlements-poll-frame"}
