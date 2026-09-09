"""Replay the complete fixed owner graph, including all native correctness work."""
from tools.optimization_evidence.common import canonical, fields, hash_file, require, uint
from tools.phase1_evidence.resources import Samples, idle, shutdown
from tools.phase1_cleanup_shutdown import validate_cleanup_shutdown
from ..budget.observer import waits
from ..cache.accounting import runtime
from ..cold.observer import Observer
from . import calls, diagnostic, fixtures as fixture_checks, measurements, model, policy, proofs, resources, schedule

HEADER = ("schema plan identity plan_sha256 identity_sha256 fixture_manifest_sha256 configuration engine_profile effective_options startup clock "
          "before_node_memory fixtures configured_runtimes population bounds samples status reason work before_shutdown shutdown data_cleanup "
          "runtime_threads_after_join final_preparation final_compiler final_runtime_accounting final_diagnostic final_waits "
          "after_shutdown_memory revision_pins functional_guest_logs elapsed_nanos")
COMMAND = "kind ordinal operation target tenant started_nanos finished_nanos response"
CHECKPOINT = "kind label node native accounting compiler preparation cleanup memory cpu"


def parse(value, selected, identity, manifest, manifest_ref, artifacts, directory):
    fields(value, HEADER)
    require(value["schema"] == "latent.optimization.engine-arm.v1" and value["plan"] == selected and value["identity"] == identity
            and value["status"] == "passed" and value["reason"] is None, "engine-raw-not-qualified")
    require(value["plan_sha256"] == hash_file(directory / "plan.json", 64 * 1024)[0]
            and value["identity_sha256"] == hash_file(directory / "identity.json", 1024**2)[0]
            and value["fixture_manifest_sha256"] == manifest_ref["sha256"], "engine-raw-input-byte-binding")
    counts = model.counts(selected["profile"])
    require(value["population"] == {"invokes": str(counts["invokes"]), "commands": str(counts["commands"]),
             "functional_invokes": "24", "functional_commands": "53", "functional_guest_logs": "10"}
            and value["work"] == {"invoke_attempts": str(counts["invokes"]), "commands": str(counts["commands"]), "budget_exhausted": False},
            "engine-raw-population-count")
    require(value["bounds"] == {"arm_seconds": "300", "functional_seconds": "30", "memory_checkpoints": "64",
                               "diagnostic_identities": "24", "diagnostic_records": "1024"}, "engine-raw-bounds-crossed")
    elapsed = uint(value["elapsed_nanos"])
    require(elapsed <= model.MAX_SECONDS * 10**9, "engine-raw-time-bound")
    require(value["configured_runtimes"] == {"invocation": 2, "control": 4, "client": 2}
            and value["runtime_threads_after_join"] == {"invocation": 0, "control": 0, "client": 0}, "engine-runtime-joins")
    policy.configuration(value["configuration"], selected)
    digest = policy.profile(value["engine_profile"], selected, identity)
    expected_options = {"cpu_fuel": "10000000000", "memory_bytes": "16777216", "wall_time_limit_millis": "1000", "log_bytes": "16384",
        "pool_capacity": "4", "queue_capacity": "64", "runtime_workers": "2", "control_workers": "4", "prepared_cache_maximum_entries": "8",
        "allocator": "pooling" if selected["engine_profile_id"].startswith("P") else "on_demand", "copy_on_write": True,
        "prepared_cache_enabled": True, "fuel_async_yield_interval": "10000", "maximum_wasm_stack_bytes": "524288",
        "async_stack_bytes": "2097152", "hostcall_fuel": "131072"}
    require(value["effective_options"] == expected_options, "engine-effective-options-crossed")
    startup = fields(value["startup"], "catalog_open_nanos node_start_nanos client_connect_nanos excluded comparable_to_historical_startup")
    require(startup["excluded"] == ["fixture-loading", "runtime-construction"] and startup["comparable_to_historical_startup"] is False,
            "engine-startup-boundary-crossed")
    for key in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        require(uint(startup[key]) <= elapsed, "engine-startup-outside-process")
    clock = fields(value["clock"], "unix_origin_nanos clock_anchor_uncertainty_nanos")
    origin = uint(clock["unix_origin_nanos"])
    uint(clock["clock_anchor_uncertainty_nanos"])
    releases = fixture_checks.publication(value["fixtures"], manifest, artifacts, directory, value["engine_profile"])
    rows = value["samples"]
    require(isinstance(rows, list) and len(rows) <= model.MAX_SAMPLES
            and all(isinstance(row, dict) and row.get("kind") in ("invoke", "command", "checkpoint", "proof")
                    and len(canonical(row)) <= model.MAX_ROW_BYTES for row in rows), "engine-raw-row-bound")
    tracker = Samples()
    nodes = [row["node"] for row in rows if "node" in row] + [value["before_shutdown"]["node"]]
    for node in nodes:
        tracker.check(node)
        require(uint(node["finished_micros"]) * 1000 <= elapsed, "engine-node-capture-outside-run")
        cells = node["inventory"]["cellCapacity"]
        require(len(cells) == 1 and cells[0]["class"] == "standard" and cells[0]["total"] == 4 and cells[0]["queueCapacity"] == 64
                and cells[0]["quarantined"] == 0 and node["inventory"]["nodeId"] == "engine-comparison"
                and node["inventory"]["routeGeneration"] == "8" and node["resources"]["descendants"] == [], "engine-node-controls-or-quarantine")
        require(node["ownership"]["journal"]["maximum_retained_bytes"] == "536870912"
                and node["ownership"]["journal"]["maximum_terminal"] == "1024", "engine-sampled-retention-controls")
    require(tracker.identity is not None, "engine-process-owner-unobserved")
    observer = Observer(tracker.identity[0], releases, "candidate")
    final_diagnostic = diagnostic.Diagnostic(value["final_diagnostic"])
    require(value["final_diagnostic"]["origin_nanos"] == "0"
            and uint(value["final_diagnostic"]["collector_finished_nanos"]) <= elapsed, "engine-final-diagnostic-outside-run")
    expected = schedule.expected(selected["profile"])
    invoke_rows = [row for row in rows if row.get("kind") == "invoke"]
    require(len(invoke_rows) == counts["invokes"] and {uint(row["ordinal"]) for row in invoke_rows} == set(range(1, counts["invokes"] + 1)),
            "engine-invoke-bijection")
    ordinary = counts["invokes"] - 24
    emitted = list(range(1, ordinary + 19)) + [ordinary + n for n in (19, 23, 20, 21, 22, 24)]
    require([uint(row["ordinal"]) for row in invoke_rows] == emitted, "engine-actual-completion-retention-order")
    pins, normalized = {}, []
    for row in sorted(invoke_rows, key=lambda row: uint(row["ordinal"])):
        ordinal = uint(row["ordinal"])
        normalized.append(calls.validate(row, expected[ordinal - 1], ordinal, value["fixtures"], origin, elapsed, pins))
    by_id = {call["row"]["activation_id"]: call for call in normalized}
    invoke_commands = [uint(call["row"]["command_ordinal"]) for call in normalized]
    require(invoke_commands == sorted(invoke_commands), "engine-invoke-submission-command-order")
    require(value["revision_pins"] == [pins[index] for index in range(8)], "engine-final-revision-pins-crossed")
    commands = [row for row in rows if row.get("kind") == "command"]
    command_ids = [uint(row["ordinal"]) for row in commands] + [uint(row["command_ordinal"]) for row in invoke_rows]
    require(len(command_ids) == counts["commands"] and set(command_ids) == set(range(1, counts["commands"] + 1)), "engine-wire-command-bijection")
    require([uint(row["ordinal"]) for row in commands] == sorted(uint(row["ordinal"]) for row in commands), "engine-control-issuance-order")
    statuses, cancels, prior_command = {}, [], 0
    for index, row in enumerate(commands):
        fields(row, COMMAND)
        begin, end = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(prior_command <= begin <= end <= elapsed and row["kind"] == "command", "engine-command-chronology")
        prior_command = end
        if index < 16:
            publication_command(row, value["fixtures"][index // 2], index)
        elif row["operation"] == "get-activation":
            require(row["target"] in by_id and row["target"] not in statuses, "engine-status-bijection")
            calls.status(row, by_id[row["target"]], elapsed)
            require(uint(row["ordinal"]) > uint(by_id[row["target"]]["row"]["command_ordinal"]), "engine-status-command-before-invoke")
            statuses[row["target"]] = row
        else:
            require(row["operation"] == "cancel" and row["target"] in by_id
                    and row["tenant"] == by_id[row["target"]]["row"]["target"]["tenant"], "engine-unplanned-control-command")
            cancels.append(row)
    require(set(statuses) == set(by_id), "engine-missing-status-control")
    issued = sorted([(uint(row["command_ordinal"]), uint(row["scheduled_nanos"])) for row in invoke_rows]
                    + [(uint(row["ordinal"]), uint(row["started_nanos"])) for row in commands])
    require([at for _, at in issued] == sorted(at for _, at in issued), "engine-issued-command-clock-order")
    lineage = {}
    for call in normalized:
        if call["expected"]["phase"] == "functional":
            lineage[call["row"]["activation_id"]] = final_diagnostic.bind_call(call, statuses[call["row"]["activation_id"]])
        else:
            diagnostic.oracle(call, [])
    checkpoints, memory_rows = checkpoints_check(rows, value, observer, tracker.identity, elapsed, identity)
    windows = batch_windows(rows, normalized, statuses, checkpoints, elapsed, selected["profile"])
    functional = proofs.functional(rows, by_id, statuses, cancels, final_diagnostic, elapsed)
    functional["deadline_lineage"] = lineage
    require(value["functional_guest_logs"] == "10" and sum(len(call["row"]["guest_logs"]) for call in normalized
            if call["expected"]["phase"] == "functional") == 10, "engine-functional-log-population")
    final = value["shutdown"]
    shutdown(final, cells=4)
    require(final["quarantinedCells"] == 0 and "compiler" in final and "cleanup" in final, "engine-final-native-joins-unavailable")
    validate_cleanup_shutdown(final["cleanup"], require)
    policy.cleanup(final["cleanup"])
    require(value["data_cleanup"] == {"removed": True}, "engine-owned-data-remains")
    runtime(value["final_runtime_accounting"], "candidate", zero=True)
    require(uint(checkpoints["before-shutdown"]["memory"]["collector_finished_nanos"])
            <= uint(value["final_preparation"]["collector_started_nanos"])
            <= uint(value["final_preparation"]["collector_finished_nanos"]) <= elapsed, "engine-final-preparation-clock-crossed")
    observer.check(value["final_preparation"], final=True)
    require(value["final_compiler"] == observer.last["compiler"]
            and {key: item if type(item) is bool else uint(item) for key, item in value["final_compiler"].items()} == final["compiler"],
            "engine-compiler-shutdown-projections-crossed")
    require(len(observer.jobs) == 8 and set(observer.jobs.values()) == set(releases)
            and all(row["succeeded"] for row in observer.records.values()), "engine-hidden-or-failed-compilation")
    low, high = max(item[0] for item in observer.anchors), min(item[1] for item in observer.anchors)
    for release in releases:
        first = next(call["row"] for call in normalized if call["row"]["release_digest"] == release)
        compiled = [row for row in observer.records.values() if row["stage"] == "component_new"
                    and observer.jobs[uint(row["job_id"])] == release]
        require(len(compiled) == 1 and uint(first["dispatch_nanos"]) <= uint(compiled[0]["started_nanos"]) + low
                <= uint(compiled[0]["finished_nanos"]) + high <= uint(first["completed_nanos"]),
                "engine-compilation-outside-first-release-rpc")
    waits(value["final_waits"], final=True)
    phases, metrics, memory, preparation = measurements.summarize(normalized, checkpoints, windows, observer, tracker.values,
            memory_rows, {**identity, "measurement_profile": selected["profile"]})
    for key in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        metrics["startup." + key] = startup[key]
    return {"validated_attempts": str(counts["invokes"]), "validated_commands": str(counts["commands"]),
            "attempt_count_complete": True, "process_identity": list(tracker.identity), "elapsed_nanos": str(elapsed),
            "engine_profile": value["engine_profile"], "effective_policy": value["engine_profile"]["effective_policy"],
            "configuration_digest": digest, "phases": phases, "metrics": metrics, "memory": memory,
            "preparation": preparation, "functional": functional, "shutdown": final}


def publication_command(row, fixture, index):
    receipt = fixture["publication"]
    operation = "publish-release" if index % 2 == 0 else "apply-deployment"
    require(row["ordinal"] == str(index + 1) and row["operation"] == operation
            and row["tenant"] == fixture["target"]["tenant"]
            and row["target"] == receipt["release_digest" if index % 2 == 0 else "deployment_id"]
            and row["response"] == ({"grpc_code": 0, "release_digest": receipt["release_digest"]} if index % 2 == 0
                                     else {"grpc_code": 0, "receipt": receipt}), "engine-publication-command-crossed")


def checkpoints_check(rows, value, observer, owner, elapsed, identity):
    selected = [row for row in rows if row.get("kind") == "checkpoint"] + [value["before_shutdown"]]
    labels = ["empty"] + [phase["name"] + "-after-" + population for phase in model.phases(value["plan"]["profile"])
                           for population in ("warmup", "measured")] + ["functional-after-drain", "before-shutdown"]
    require([row["label"] for row in selected] == labels, "engine-checkpoint-population")
    memory_rows, result = [], {}
    os_name = identity["environment"]["os"]
    first_start = uint(selected[0]["node"]["started_micros"]) * 1000
    memory_rows.append(resources.memory(value["before_node_memory"], "before-node", owner, 0, first_start + 999, operating_system=os_name))
    prior_memory = 0
    for row in selected:
        fields(row, CHECKPOINT)
        require(row["kind"] == "checkpoint", "engine-checkpoint-kind")
        node = row["node"]
        idle(node, dormant=row["label"] == "empty")
        policy.native(row["native"], 0)
        require(row["native"] == node["backend"], "engine-checkpoint-native-projection")
        policy.accounting(row["accounting"], node, empty=row["label"] == "empty")
        policy.cleanup(row["cleanup"])
        require(all(row["cleanup"][key] == 0 for key in ("reserved", "queued", "running")), "engine-checkpoint-cleanup-not-drained")
        prep = row["preparation"]
        require(uint(node["finished_micros"]) * 1000 <= uint(prep["collector_started_nanos"])
                and prior_memory <= uint(node["started_micros"]) * 1000 + 999, "engine-checkpoint-clock-order")
        observer.check(prep)
        require(row["compiler"] == prep["snapshot"]["compiler"], "engine-checkpoint-compiler-crossed")
        memory_values = resources.memory(row["memory"], row["label"], owner, uint(prep["collector_finished_nanos"]), elapsed, operating_system=os_name)
        prior_memory = uint(row["memory"]["collector_finished_nanos"])
        measurements.cpu(row["cpu"], owner, prior_memory, elapsed)
        memory_rows.append(memory_values)
        result[row["label"]] = {**row, "memory_values": memory_values}
    require(not value["samples"][16]["preparation"]["snapshot"]["recent_stages"], "engine-compilation-before-first-offer")
    memory_rows.append(resources.memory(value["after_shutdown_memory"], "after-shutdown", owner, prior_memory, elapsed, operating_system=os_name))
    return result, memory_rows


def batch_windows(rows, calls_, statuses, checkpoints, elapsed, profile):
    found = [row for row in rows if row.get("kind") == "proof" and row.get("label") == "batch-window"]
    require(len(found) == 8, "engine-batch-window-population")
    result, previous = {}, uint(checkpoints["empty"]["memory"]["collector_finished_nanos"])
    for row, (phase, population) in zip(found, [(phase, pop) for phase in model.phases(profile) for pop in ("warmup", "measured")], strict=True):
        fields(row, "kind label phase phase_kind first_index count width started_nanos finished_nanos scope")
        name, warmup = phase["name"], phase["warmup"]
        require(row["phase"] == name and row["phase_kind"] == population and row["scope"] == "invoke-status-validation-and-retention"
                and row["first_index"] == str(0 if population == "warmup" else warmup)
                and row["count"] == str(phase[population]) and row["width"] == str(phase["batch_size"]), "engine-batch-plan-crossed")
        begin, finish = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(previous <= begin < finish <= elapsed, "engine-batch-window-order")
        selected = [call for call in calls_ if call["row"]["phase"] == name and call["row"]["phase_kind"] == population]
        for index, call in enumerate(selected):
            offer = call["row"]
            status_end = uint(statuses[offer["activation_id"]]["finished_nanos"])
            require(begin <= uint(offer["scheduled_nanos"]) <= uint(offer["completed_nanos"]) <= status_end <= finish,
                    "engine-offer-outside-batch-window")
            if index >= phase["batch_size"]:
                previous_batch = selected[(index // phase["batch_size"] - 1) * phase["batch_size"]:index // phase["batch_size"] * phase["batch_size"]]
                require(max(uint(statuses[old["row"]["activation_id"]]["finished_nanos"]) for old in previous_batch)
                        <= uint(offer["scheduled_nanos"]), "engine-batch-overlap-or-hidden-concurrency")
        checkpoint = checkpoints[name + "-after-" + population]
        require(finish <= uint(checkpoint["node"]["started_micros"]) * 1000 + 999, "engine-checkpoint-before-batch-drain")
        previous = uint(checkpoint["memory"]["collector_finished_nanos"])
        result[(name, population)] = row
    functional = [call for call in calls_ if call["row"]["phase"] == "functional"]
    require(previous <= min(uint(call["row"]["scheduled_nanos"]) for call in functional)
            and max(uint(statuses[call["row"]["activation_id"]]["finished_nanos"]) for call in functional)
            <= uint(checkpoints["functional-after-drain"]["node"]["started_micros"]) * 1000 + 999, "engine-functional-phase-window")
    return result
