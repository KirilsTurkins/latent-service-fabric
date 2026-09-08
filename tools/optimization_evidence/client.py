"""Strictly bind a client's plan, readiness, all attempt rows and summaries."""

from . import attempts
from .common import canonical, fields, integer, load_rows, require, sha256, text, uint
from .workload import expected

DYNAMIC = {"run_id", "arm", "server_process_id", "endpoint", "token_file"}
PLAN_FIELDS = ("schema run_id arm server_process_id endpoint token_file tenant services contract route function payload "
               "warmup_attempts measured_attempts batch_size concurrency runtime_workers schedule budget_millis cpu_fuel "
               "memory_bytes log_bytes connect_timeout_millis response_timeout_millis maximum_output_bytes")
READY_FIELDS = ("schema run_id arm client_process_id server_process_id runtime_workers maximum_in_flight "
                "started_unix_millis connected_unix_millis connect_nanos startup_to_ready_nanos plan_sha256 public_plan "
                "request_sha256 request_bytes expected_output_sha256 expected_output_bytes observation_hold_millis")


def replay(artifacts, batch, template, arm, server_owner, client_owner, components, activation_ids):
    plan = artifacts.json(batch["plan"], 2 * 1024 * 1024)
    fields(plan, PLAN_FIELDS)
    require({key: value for key, value in plan.items() if key not in DYNAMIC} == template,
            "changed-client-plan")
    require(plan["arm"] == arm and plan["server_process_id"] == server_owner[0], "crossed-client-server")
    run_id = text(plan["run_id"], 48)
    require(all(char.isascii() and (char.isalnum() or char == "-") for char in run_id), "invalid-run-id")
    text(plan["endpoint"], 2048)
    text(plan["token_file"], 4096)
    # serde_json::Value objects use BTree order for input; output is the typed
    # WIT declaration order, independently implemented by the reference helper.
    request = canonical(plan["payload"])
    result = expected(plan["function"], plan["payload"])
    output = {"sha256": sha256(result), "bytes": len(result)}
    public = {key: value for key, value in plan.items() if key not in ("token_file", "endpoint", "payload")}
    public.update(payload_sha256=sha256(request), payload_bytes=str(len(request)))
    readiness = artifacts.json(batch["readiness"])
    fields(readiness, READY_FIELDS)
    require(readiness["schema"] == "latent.optimization.client-readiness.v1"
            and readiness["run_id"] == run_id and readiness["arm"] == arm
            and readiness["client_process_id"] == client_owner[0]
            and readiness["server_process_id"] == server_owner[0]
            and readiness["runtime_workers"] == plan["runtime_workers"]
            and readiness["maximum_in_flight"] == plan["concurrency"]
            and readiness["plan_sha256"] == batch["plan"]["sha256"]
            and readiness["public_plan"] == public
            and readiness["request_sha256"] == sha256(request)
            and uint(readiness["request_bytes"]) == len(request)
            and readiness["expected_output_sha256"] == output["sha256"]
            and uint(readiness["expected_output_bytes"]) == len(result), "crossed-client-input-identity")
    integer(readiness["observation_hold_millis"], 100, 100)
    for key in ("started_unix_millis", "connected_unix_millis", "connect_nanos", "startup_to_ready_nanos"):
        uint(readiness[key])
    require(uint(readiness["startup_to_ready_nanos"]) >= uint(readiness["connect_nanos"]),
            "connect-outside-readiness-boundary")
    summary = artifacts.json(batch["summary"])
    fields(summary, "schema status readiness warmup measured client_elapsed_nanos active_tasks_at_completion observation_hold_millis")
    require(summary["schema"] == "latent.optimization.client-summary.v1" and summary["status"] == "complete"
            and summary["readiness"] == readiness and summary["active_tasks_at_completion"] == 0,
            "invalid-client-completion")
    integer(summary["active_tasks_at_completion"], 0, 0)
    integer(summary["observation_hold_millis"], 100, 100)
    rows = load_rows(artifacts.path(batch["attempts"]))
    expected_count = plan["warmup_attempts"] + plan["measured_attempts"]
    require(len(rows) == expected_count, "missing-or-extra-attempts")
    phases = {"warmup": [], "measured": []}
    measured_started = False
    for row in rows:
        require(row.get("phase") in phases, "unknown-attempt-phase")
        measured_started = measured_started or row["phase"] == "measured"
        require(not measured_started or row["phase"] == "measured", "interleaved-warmup-population")
        phases[row["phase"]].append(row)
    replayed = {}
    elapsed = uint(readiness["startup_to_ready_nanos"])
    for name, selected in phases.items():
        phase = fields(summary[name], "origin_unix_nanos clock_anchor_uncertainty_nanos phase_elapsed_nanos counts batches")
        origin = uint(phase["origin_unix_nanos"])
        uint(phase["clock_anchor_uncertainty_nanos"])
        expected_indices = set(range(plan[name + "_attempts"]))
        indices = {uint(row.get("index")) for row in selected}
        require(indices == expected_indices and len(selected) == len(indices), "duplicate-or-missing-attempt-index")
        for row in selected:
            attempts.attempt(row, plan, name, origin, output, components)
            require(row["activation_id"] not in activation_ids, "reused-activation-identity")
            activation_ids.add(row["activation_id"])
        require(phase["counts"] == attempts.counts(selected), "changed-phase-counts")
        expected_batches = [
            {"index": str(index), "counts": attempts.counts([row for row in selected
                                                            if uint(row["batch"]) == index])}
            for index in range((len(selected) + plan["batch_size"] - 1) // plan["batch_size"])
        ]
        require(phase["batches"] == expected_batches, "changed-batch-counts-or-elapsed")
        phase_elapsed = uint(phase["phase_elapsed_nanos"])
        require(phase_elapsed >= uint(phase["counts"]["last_completed_nanos"]), "truncated-phase-interval")
        elapsed += phase_elapsed
        replayed[name] = attempts.metrics(selected)
        replayed[name]["batches"] = [
            {"index": item["index"], **attempts.metrics([row for row in selected if row["batch"] == item["index"]])}
            for item in expected_batches
        ]
        # Actual dispatch/completion intervals cannot exceed the declared task
        # bound. Equal timestamps free a completed slot before a new dispatch.
        events = sorted((uint(row[key]), delta) for row in selected if row["dispatch_nanos"] is not None
                        for key, delta in (("dispatch_nanos", 1), ("completed_nanos", -1)))
        active = maximum = 0
        for _, delta in events:
            active += delta
            maximum = max(active, maximum)
        require(active == 0 and maximum <= plan["concurrency"], "client-concurrency-exceeds-plan")
    require(uint(summary["client_elapsed_nanos"]) >= elapsed, "client-elapsed-excludes-recorded-work")
    replayed["input"] = {"request_sha256": sha256(request), "request_bytes": str(len(request)),
                         "expected_output_sha256": output["sha256"], "expected_output_bytes": str(len(result))}
    replayed["run_id"] = run_id
    replayed["correctness_failures"] = str(sum(row["outcome"] in ("invalid-response", "declared-error")
                                              for row in rows))
    replayed["readiness"] = {"connect_nanos": readiness["connect_nanos"],
                             "startup_to_ready_nanos": readiness["startup_to_ready_nanos"]}
    return replayed
