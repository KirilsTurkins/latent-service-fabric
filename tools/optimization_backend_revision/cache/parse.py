"""Replay the exact cache offer, ownership and preparation-event graph."""
from tools.optimization_evidence.common import fields, integer, require, sha256, text, uint
from tools.optimization_evidence import attempts as shared_attempts
from tools.optimization_evidence.workload import MEDIA
from tools.phase1_evidence.resources import Samples, idle, shutdown
from tools.phase1_paired.common import INPUT
from tools.phase1_paired.metrics import timing
from ..cold import attempts, controls
from ..cold.parse import configuration, fixtures
from . import accounting, model
from .observer import CacheObserver


def header(value, selected, identity, artifacts, raw_path, echo, variant):
    fields(value, "schema plan identity configuration effective_options semantic_input clock startup fixtures initial_observer initial_accounting "
           "configured_runtimes population event_export samples status reason elapsed_micros work direct_work before_shutdown "
           "accounting_before_shutdown shutdown data_cleanup runtime_threads_after_join final_observer final_runtime_accounting")
    require(value["schema"] == "latent.optimization.cache-behavior-arm.v1" and value["plan"] == selected
            and value["identity"] == identity and value["status"] == "passed" and value["reason"] is None, "cache-arm-not-passed")
    count, commands = model.population(selected["profile"])
    require(value["population"] == {"attempts": str(count), "commands": str(commands), "direct_readiness_acquisitions": "2",
                                    "direct_materializations": "1", "direct_executions": "1", "explicit_releases": "9"}
            and value["work"] == {"invoke_attempts": str(count), "commands": str(commands), "budget_exhausted": False}
            and value["direct_work"] == model.DIRECT, "cache-population-mismatch")
    require(value["event_export"] == {"maximum_sequential_calls": 16, "sequence_policy": "contiguous-deduplicated", "maximum_stage_ring": 256},
            "cache-export-policy-changed")
    configuration(value["configuration"], "candidate", node_id="cache-comparison", entries=4)
    require(value["effective_options"] == {
        "cpu_fuel": "10000000000", "memory_bytes": "16777216", "wall_time_limit_millis": "1000", "log_bytes": "16384",
        "pool_capacity": "4", "queue_capacity": "64", "runtime_workers": "2", "control_workers": "4",
        "prepared_cache_maximum_entries": "4", "allocator": "on_demand", "copy_on_write": True, "prepared_cache_enabled": True,
        "fuel_async_yield_interval": "10000", "maximum_wasm_stack_bytes": "524288", "async_stack_bytes": "2097152", "hostcall_fuel": "131072"},
        "cache-effective-options-changed")
    startup = fields(value["startup"], "catalog_open_nanos node_start_nanos client_connect_nanos excluded comparable_to_historical_startup")
    for name in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        uint(startup[name])
    require(startup["excluded"] == ["fixture-loading", "runtime-construction"] and startup["comparable_to_historical_startup"] is False,
            "cache-startup-boundary-changed")
    require(value["configured_runtimes"] == {"invocation": 2, "control": 4, "client": 2}
            and value["runtime_threads_after_join"] == {"invocation": 0, "control": 0, "client": 0}, "cache-runtime-threads-not-joined")
    require(value["semantic_input"] == {"utf8": INPUT, "sha256": sha256(INPUT.encode()), "bytes": "25"}, "cache-semantic-input-changed")
    clock = fields(value["clock"], "unix_origin_nanos clock_anchor_uncertainty_nanos")
    uint(clock["clock_anchor_uncertainty_nanos"])
    origin = uint(clock["unix_origin_nanos"])
    ticks = integer(identity["environment"]["clock_ticks_per_second"], 1, 1_000_000)
    base = artifacts.path(echo["component"]).read_bytes()
    components = [base + (bytes([0, 2, 0, index]) if index else b"") for index in range(5)] + [b"\0asm\x0d\0\x01\0"]
    releases = fixtures(value["fixtures"], artifacts, raw_path.parent, echo, components)
    accounting.checkpoint("empty", value["initial_accounting"], variant)
    return count, origin, ticks, releases


def direct(row, release, handle):
    fields(row, "kind activation_id release_digest prepared_handle started_nanos finished_nanos outcome response cleanup_reusable backend_timing")
    require(row["activation_id"] == "cache-held-direct" and row["release_digest"] == release
            and row["prepared_handle"] == handle and row["outcome"] == "success" and row["cleanup_reusable"] is True
            and uint(row["started_nanos"]) <= uint(row["finished_nanos"]), "cache-held-direct-execution-failed-or-crossed")
    response = fields(row["response"], "payload_sha256 payload_bytes media_type consumption")
    require(response["payload_sha256"] == sha256(attempts.PAYLOAD) and uint(response["payload_bytes"]) == len(attempts.PAYLOAD)
            and response["media_type"] == MEDIA, "cache-held-direct-payload")
    # Reuse the actual budget/accounting type; there is deliberately no manager
    # activation, route generation or retained terminal receipt for this call.
    consumed = fields(response["consumption"], shared_attempts.CONSUMPTION)
    for item in consumed.values():
        uint(item)
    require(0 < uint(consumed["cpu_fuel"]) <= 10_000_000_000
            and 0 < uint(consumed["peak_memory_bytes"]) <= 16_777_216
            and uint(consumed["wall_time_micros"]) <= 1_000_000 and uint(consumed["log_bytes"]) <= 16384
            and all(item == "0" for name, item in consumed.items() if name not in (
                "cpu_fuel", "peak_memory_bytes", "wall_time_micros", "log_bytes")), "cache-direct-budget-exceeded")
    timing(row["backend_timing"])


def parse(value, selected, identity, artifacts, raw_path, echo, variant):
    count, origin, ticks, releases = header(value, selected, identity, artifacts, raw_path, echo, variant)
    rows = value["samples"]
    require(isinstance(rows, list) and count < len(rows) <= 2048, "cache-event-bound")
    anchors = [row for row in rows if row.get("kind") == "phase-anchor"]
    require(len(anchors) == 1 and anchors[0]["phase"] == "concurrent", "cache-burst-anchor-count")
    anchor = anchors[0]
    expected = model.expected(selected["profile"], anchor)
    tracker = Samples()
    snapshots = [row["node"] for row in rows if "node" in row] + [value["before_shutdown"]]
    for sample in snapshots:
        tracker.check(sample)
        cells, cache = sample["inventory"]["cellCapacity"], sample["inventory"]["cacheSummary"]
        require(len(cells) == 1 and cells[0]["total"] == 4 and cells[0]["queueCapacity"] == 64
                and cache["maximumEntries"] == "4" and cache["maximumConcurrentPreparations"] == "4"
                and sample["resources"]["descendants"] == [], "cache-sampled-controls-or-ownership")
    require(tracker.identity is not None, "cache-process-identity-missing")
    observer = CacheObserver(tracker.identity[0], releases)
    observer.check(value["initial_observer"])
    require(not observer.records and not observer.jobs and value["initial_observer"]["snapshot"]["active_jobs"] == "0", "cache-initial-already-prepared")
    tokens, cursor = model.tokens(selected["profile"]), 0
    found, normalized, pins, checkpoints, checkpoint_rows = set(), [], {}, {}, {}
    handles, direct_result, held, active, anchored, probed = {}, None, None, False, False, False
    phase_start = None
    last_clock = 0
    for row in rows:
        kind = row.get("kind")
        if active and kind in ("invoke", "phase-anchor", "status-probe", "phase-end"):
            if kind == "invoke":
                require(anchored and row["phase"] == "concurrent", "cache-burst-offer-outside-anchor")
            elif kind == "phase-anchor":
                fields(row, "kind phase recorded_nanos offer_lead_nanos origin_nanos cold_due_nanos")
                require(not anchored and row == anchor and row["offer_lead_nanos"] == "10000000"
                        and uint(row["origin_nanos"]) == uint(row["recorded_nanos"]) + 10_000_000
                        and uint(row["recorded_nanos"]) >= uint(phase_start["observer"]["collector_finished_nanos"]), "cache-burst-origin")
                anchored = True
                continue
            elif kind == "status-probe":
                fields(row, "kind phase activation_id started_nanos finished_nanos response retained_valid")
                require(anchored and not probed and row["phase"] == "concurrent"
                        and row["activation_id"] == "cold-concurrent-cold-0000" and row["retained_valid"] is True
                        and uint(anchor["cold_due_nanos"]) + 2_000_000 <= uint(row["started_nanos"]) <= uint(row["finished_nanos"])
                        and row["response"]["grpc_code"] in (0, 5), "cache-status-probe")
                if row["response"]["grpc_code"] == 0:
                    require(row["response"]["activation_id"] == row["activation_id"], "cache-status-probe-crossed")
                probed = row
                continue
            else:
                fields(row, "kind phase observer node finished_nanos")
                finish = uint(row["finished_nanos"])
                require(anchored and probed and row["phase"] == "concurrent"
                        and uint(probed["finished_nanos"]) <= finish
                        and uint(row["observer"]["collector_finished_nanos"]) <= finish
                        and all(uint(item["retained_observed_nanos"]) <= finish for item in normalized if item["phase"] == "concurrent"),
                        "cache-burst-ended-before-work")
                require({key for key, item in expected.items() if item[0] == "concurrent"} <= found, "cache-burst-missing-offer")
                idle(row["node"])
                controls.drained(row["observer"])
                observer.check(row["observer"])
                last_clock, active = finish, False
                continue
        else:
            if kind == "invoke":
                token = kind, row["phase"], uint(row["index"])
            elif kind == "explicit-release":
                token = kind, row["label"], uint(row["key"])
            elif kind in ("checkpoint", "preparation-events"):
                token = kind, row["label"]
            elif kind == "phase-start":
                token = ("burst",)
            else:
                token = (kind,)
            require(not active and cursor < len(tokens) and token == tokens[cursor], "cache-event-order-or-population")
            cursor += 1
        if kind == "invoke":
            require(row["activation_id"] not in found, "cache-duplicate-invoke")
            if not active:
                require(uint(row["scheduled_nanos"]) >= last_clock, "cache-sequential-call-overlapped-prior-work")
            found.add(row["activation_id"])
            parsed = attempts.validate(row, origin, releases, expected, pins, route_generation="6")
            normalized.append(parsed)
            if row["phase"] != "concurrent":
                if row["phase"] == "ownership-invalid":
                    require(row["outcome"] == "platform-failure" and row["response"]["code"] == "incompatible-contract", "cache-refill-failure-oracle")
                else:
                    require(row["outcome"] == "success", "cache-sequential-semantic-failure")
                last_clock = uint(row["retained_observed_nanos"])
        elif kind == "checkpoint":
            fields(row, "kind label node accounting observer")
            label = row["label"]
            require(label not in checkpoints, "cache-duplicate-checkpoint")
            accounting.checkpoint(label, row["accounting"], variant)
            accounting.sampled(label, row["accounting"], row["node"])
            require(uint(row["observer"]["collector_started_nanos"]) >= last_clock, "cache-checkpoint-before-previous-work")
            checkpoints[label], checkpoint_rows[label] = row["accounting"], row
            observer.check(row["observer"])
            if label not in ("held-two-ready", "held-ready-and-active", "evicted-held-ready-and-active", "evicted-held-ready", "resident-new-and-evicted-old"):
                idle(row["node"], dormant=label == "empty")
            require(all(item == "0" for name, item in row["node"]["backend"].items() if name != "stores_created"), "cache-stored-live-guest-instance")
            ready = row["observer"]["snapshot"]["compiler"]["ready_preparations"]
            expected_ready = "2" if label == "held-two-ready" else ("1" if label in (
                "held-ready-and-active", "evicted-held-ready-and-active", "evicted-held-ready", "resident-new-and-evicted-old") else "0")
            require(ready == expected_ready, "cache-ready-owner-count")
            last_clock = uint(row["observer"]["collector_finished_nanos"])
        elif kind == "preparation-events":
            require(uint(row["collector_started_nanos"]) >= last_clock, "cache-export-before-previous-work")
            observer.export(row)
            last_clock = uint(row["collector_finished_nanos"])
        elif kind == "explicit-release":
            fields(row, "kind label key release_digest prepared_handle started_nanos finished_nanos succeeded accounting_before accounting_after")
            key = uint(row["key"])
            handle = text(row["prepared_handle"], 256)
            require(key < 5 and row["release_digest"] == releases[key] and row["succeeded"] is True
                    and last_clock <= uint(row["started_nanos"]) <= uint(row["finished_nanos"])
                    and (key not in handles or handles[key] == handle), "cache-crossed-explicit-release")
            handles[key] = handle
            for name in ("accounting_before", "accounting_after"):
                accounting.check(row[name], variant)
            before, after = row["accounting_before"]["resident"], row["accounting_after"]["resident"]
            removed = uint(before["entries"]) - uint(after["entries"])
            require(removed in (0, 1) and uint(after["invalidations"]) - uint(before["invalidations"]) == removed
                    and all(before[name] == after[name] for name in ("hits", "misses", "evictions")), "cache-invalidation-accounting")
            last_clock = uint(row["finished_nanos"])
        elif kind == "direct-readiness":
            fields(row, "kind release_digest prepared_handle owners direct_work")
            require(row["release_digest"] == releases[0] and row["prepared_handle"] == handles[0] and row["owners"] == "2"
                    and row["direct_work"] == {"readiness_acquisitions": "2", "materializations": "0", "executions": "0", "releases": "5"},
                    "cache-direct-readiness-association")
            held = row["prepared_handle"]
        elif kind == "direct-execution":
            require(held is not None and last_clock <= uint(row["started_nanos"]), "cache-direct-execution-before-pin")
            direct(row, releases[0], held)
            direct_result = row
            last_clock = uint(row["finished_nanos"])
        elif kind == "failed-refill-accounting":
            fields(row, "kind before after")
            for name in ("before", "after"):
                accounting.check(row[name], variant)
            accounting.same_resident(row["before"], row["after"])
            if variant == "candidate":
                require(row["before"]["runtimes"] == row["after"]["runtimes"], "cache-failed-refill-leaked-runtime")
        elif kind == "phase-start":
            fields(row, "kind phase observer node")
            require(row["phase"] == "concurrent" and uint(row["observer"]["collector_started_nanos"]) >= last_clock, "cache-overlapping-burst")
            observer.check(row["observer"])
            controls.drained(row["observer"])
            phase_start, active = row, True
        else:
            require(False, "cache-unknown-event")
    require(cursor == len(tokens) and not active and found == set(expected) and len(found) == count and direct_result is not None,
            "cache-incomplete-population")
    require(uint(value["final_observer"]["collector_started_nanos"]) >= last_clock, "cache-final-observer-before-work")
    observer.check(value["final_observer"], final=True)
    controls.compilation_associations(observer, normalized)
    require(observer.next_export == len(observer.records), "cache-final-unexported-stage")
    accounting.ownership(checkpoints, variant)
    accounting.check(value["accounting_before_shutdown"], variant)
    accounting.sampled("before-shutdown", value["accounting_before_shutdown"], value["before_shutdown"])
    accounting.runtime(value["final_runtime_accounting"], variant, zero=True)
    idle(value["before_shutdown"])
    shutdown(value["shutdown"], cells=4)
    require("compiler" in value["shutdown"] and value["shutdown"]["compiler"] == {
                name: item if type(item) is bool else uint(item) for name, item in value["final_observer"]["snapshot"]["compiler"].items()}
            and value["shutdown"]["quarantinedCells"] == 0 and value["data_cleanup"] == {"removed": True}, "cache-shutdown-or-compiler-join")
    require(tracker.last_finished <= uint(value["elapsed_micros"]) <= 300_000_000, "cache-arm-window")
    from .aggregate import summarize
    return {"samples": str(count), "process_identity": tracker.identity, "clock_ticks_per_second": ticks,
            "direct_execution": direct_result, "direct_work": value["direct_work"], "runtime_accounting_available": variant == "candidate",
            "checkpoints": checkpoints, **summarize(normalized, observer, snapshots, rows)}
