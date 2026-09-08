"""Validate the actual standalone/RPC arm's per-call and terminal ownership."""

from ..phase1_evidence.common import fields, read_json, require, sha256, uint
from ..phase1_evidence.resources import Samples, idle, shutdown
from .common import GRANTS, INPUT, RAW_LIMIT, plan as validate_plan
from .metrics import consumption, summarize, timing


def parse(value, plan, identity, artifacts, raw_path, *, revision=False):
    common_fields = ("schema arm profile warmup_samples measured_samples plan identity semantic_input semantic_output "
                     "effective_options configuration startup artifact publication preparation_cache_before "
                     "samples status reason elapsed_micros work shutdown data_cleanup ")
    fields(value, common_fields + ("warmup_method before_shutdown" if revision else
           "preparation_elapsed_micros preparation_cache_after prepared_release_elapsed_micros after_release"),
           "" if revision else "preparation_scope")
    scope = value.get("preparation_scope")
    require(scope in (None, "repository-acquisition-including-verified-refill"), "changed-preparation-scope")
    require(value["schema"] == ("latent.optimization.backend-revision-arm.v1" if revision else "latent.phase1.paired-arm.v1")
            and value["arm"] == ("lsf" if revision else "candidate")
            and value["profile"] == plan["profile"] and value["status"] == "passed" and value["reason"] is None,
            "candidate-did-not-pass")
    validate_plan(value["plan"])
    require(value["plan"] == plan and value["identity"] == identity, "candidate-plan-or-identity-mismatch")
    semantic = {"utf8": INPUT, "sha256": sha256(INPUT.encode()), "bytes": "25"}
    require(value["semantic_input"] == value["semantic_output"] == semantic, "candidate-semantic-workload-changed")
    for key in ("warmup_samples", "measured_samples"):
        require(uint(value[key]) == plan[key], "changed-candidate-population")
    options(value["effective_options"])
    configuration(value["configuration"])
    startup = fields(value["startup"], "catalog_open_nanos node_start_nanos client_connect_nanos excluded comparable_to_historical_startup")
    require(startup["excluded"] == ["fixture-loading", "runtime-construction"]
            and startup["comparable_to_historical_startup"] is False, "unmatched-startup-claimed")
    for key in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        uint(startup[key])
    fixture = metadata(value["artifact"], identity, artifacts, raw_path.parent)
    publication = fields(value["publication"], "release_digest deployment_id object_generation catalog_generation")
    require(publication["release_digest"] == identity["fixtures"][0]["sha256"]
            and publication["deployment_id"] == fixture["metadata"]["name"]
            and publication["object_generation"] == publication["catalog_generation"] == "1", "candidate-publication-mismatch")
    cache(value["preparation_cache_before"], entries=0, hits=0, misses=0)
    if revision:
        require(value["warmup_method"] == "first-rpc-empty-cache-in-declared-warmup", "changed-revision-warmup-method")
    else:
        cache(value["preparation_cache_after"], entries=1, hits=0, misses=1)
        require(value["preparation_cache_after"]["source_bytes"] == identity["fixtures"][0]["bytes"], "candidate-prepared-wrong-component")
    total = plan["warmup_samples"] + plan["measured_samples"]
    require(isinstance(value["samples"], list) and len(value["samples"]) == total, "candidate-sample-count")
    tracker, samples, pinned_revision = Samples(), [], None
    for index, row in enumerate(value["samples"]):
        fields(row, "iteration activation_id semantic_output_sha256 outcome elapsed_micros timing consumption post_call receipt")
        require(row["iteration"] == str(index) and row["activation_id"] == f"baseline-warm-echo-{index:08}", "reordered-candidate-population")
        require(row["outcome"] == "success" and row["semantic_output_sha256"] == semantic["sha256"], "candidate-output-mismatch")
        consumed = consumption(row["consumption"])
        require(0 < consumed["log_bytes"] and consumed["wall_time_micros"] < 1_000_000, "candidate-common-grant-exhausted")
        receipt = fields(row["receipt"], "release_digest revision_id route_generation terminal_state retained_consumption_matches")
        if pinned_revision is None:
            pinned_revision = receipt["revision_id"]
        require(isinstance(pinned_revision, str) and pinned_revision.startswith("revision-v1:sha256:")
                and receipt["revision_id"] == pinned_revision and receipt["release_digest"] == publication["release_digest"]
                and receipt["route_generation"] == "1" and receipt["terminal_state"] == "completed"
                and receipt["retained_consumption_matches"] is True, "candidate-terminal-pin-mismatch")
        post = row["post_call"]
        tracker.check(post)
        idle(post)
        require(post["backend"]["stores_created"] == str(index + 1), "candidate-store-not-fresh")
        cells = post["inventory"]["cellCapacity"]
        require(len(cells) == 1 and cells[0]["total"] == cells[0]["available"] == 2
                and cells[0]["quarantined"] == 0 and cells[0]["queueCapacity"] == 3, "candidate-cell-control-mismatch")
        resident = post["inventory"]["cacheSummary"]
        require(resident["entries"] == resident["misses"] == "1" and resident["hits"] == str(index if revision else index + 1)
                and resident["evictions"] == resident["invalidations"] == "0"
                and resident["sourceBytes"] == identity["fixtures"][0]["bytes"], "candidate-cache-not-reused")
        work(post["work"], index + 1)
        samples.append({"elapsed": uint(row["elapsed_micros"]), "timing": timing(row["timing"])})
    final = value["before_shutdown" if revision else "after_release"]
    tracker.check(final)
    idle(final)
    require(final["inventory"]["cacheSummary"]["entries"] == ("1" if revision else "0")
            and final["backend"]["stores_created"] == str(total), "candidate-final-residency-not-observed")
    if revision:
        resident = final["inventory"]["cacheSummary"]
        require(resident["hits"] == str(total - 1) and resident["misses"] == "1"
                and resident["evictions"] == resident["invalidations"] == "0", "revision-final-cache-mismatch")
    work(value["work"], total)
    shutdown(value["shutdown"])
    require(value["shutdown"]["quarantinedCells"] == 0 and value["data_cleanup"] == {"removed": True}, "candidate-did-not-clean")
    if not revision:
        uint(value["prepared_release_elapsed_micros"])
    require(tracker.last_finished <= uint(value["elapsed_micros"]) <= int(plan["maximum_run_seconds"]) * 1_000_000, "candidate-exceeded-window")
    metrics = summarize(samples, plan["warmup_samples"], samples[0]["elapsed"] if revision else uint(value["preparation_elapsed_micros"]))
    if scope:
        for metric in metrics:
            if metric["name"] == "initial_preparation_micros":
                metric["boundary"]["candidate"] = "repository-acquisition-including-verified-refill"
    if revision:
        for metric in metrics:
            if metric["name"] == "initial_preparation_micros":
                metric["name"] = "first_rpc_empty_cache_micros"
                metric["boundary"] = {"category": "node-rpc", "control": "first-rpc-empty-cache-through-terminal-receipt",
                                      "candidate": "first-rpc-empty-cache-through-terminal-receipt"}
            elif metric["name"] == "semantic_invoke_elapsed_micros":
                metric["boundary"] = {"category": "node-rpc", "control": "persistent-loopback-rpc-invoke-through-terminal-receipt",
                                      "candidate": "persistent-loopback-rpc-invoke-through-terminal-receipt"}
    return {"metrics": metrics,
            "samples": str(total), "process_identity": tracker.identity,
            "effective_options": value["effective_options"], "historical_full_proof": "not-applicable"}


def work(value, count):
    require(value == {"commands": str(2 * count + 2), "invoke_attempts": str(count), "budget_exhausted": False}, "candidate-work-mismatch")


def cache(value, *, entries, hits, misses):
    fields(value, "entries hits misses evictions invalidations source_bytes metadata_bytes compiled_image_bytes preparing")
    for item in value.values():
        uint(item)
    require(value["entries"] == str(entries) and value["hits"] == str(hits) and value["misses"] == str(misses)
            and value["evictions"] == value["invalidations"] == value["preparing"] == "0", "candidate-preparation-cache-mismatch")
    for key in ("source_bytes", "metadata_bytes", "compiled_image_bytes"):
        require((uint(value[key]) > 0) == bool(entries), "candidate-cache-residency-mismatch")


def options(value):
    expected = dict(GRANTS, pool_capacity="2", queue_capacity="3", runtime_workers="2", control_workers="1",
                    prepared_cache_maximum_entries="4", allocator="on_demand", copy_on_write=True,
                    prepared_cache_enabled=True, fuel_async_yield_interval="10000", maximum_wasm_stack_bytes="524288",
                    async_stack_bytes="2097152", hostcall_fuel="131072")
    require(value == expected, "candidate-effective-options-changed")


def configuration(value):
    fields(value, "formatVersion dataDirectory nodeId bind workers cells execution catalogs cache retention telemetry shutdownGraceMillis")
    require(value["formatVersion"] == 1 and value["dataDirectory"] == "data"
            and value["nodeId"] == "phase1-comparison" and value["bind"] == "127.0.0.1:0", "unsafe-candidate-configuration")
    require(value.get("workers") == {"runtime": 2, "control": 1}
            and value.get("cells") == [{"class": "standard", "capacity": 2, "queueCapacity": 3, "maximumMemoryBytes": 16_777_216}]
            and value.get("execution") == {"maximumCpuFuel": 10_000_000_000, "maximumWallTimeMillis": 1000, "maximumLogBytes": 16384}
            and value["cache"] == {"entries": 4, "sourceBytes": 67_108_864, "metadataBytes": 16_777_216,
                                   "compiledImageBytes": 268_435_456, "preparations": 1}
            and value["catalogs"] == {"releaseEntries": 16, "releaseIndexBytes": 16_777_216,
                                      "deployments": 16, "deploymentStateBytes": 16_777_216}
            and value["retention"] == {"terminalEntries": 64, "terminalTtlMillis": 60_000, "bytes": 20_971_520}
            and value["telemetry"] == {"queueEntries": 256, "retainedEntries": 128, "retainedBytes": 1_048_576}
            and value["shutdownGraceMillis"] == 500, "candidate-configuration-controls-changed")


def metadata(value, identity, artifacts, directory):
    fields(value, "component_sha256 component_bytes stored_descriptor_reference capsule contracts deployment")
    component = identity["fixtures"][0]
    require(value["component_sha256"] == component["sha256"] and value["component_bytes"] == component["bytes"]
            and value["stored_descriptor_reference"] == "local:release:" + component["sha256"], "candidate-artifact-mismatch")
    documents = {}
    for role in ("capsule", "contracts", "deployment"):
        ref = value[role]
        require(ref["path"] == "echo-" + role + ".json" and uint(ref["bytes"]) <= 1024**2, "candidate-metadata-boundary")
        documents[role] = read_json(artifacts.nested(directory, ref), 1024**2)
    capsule, contracts, deployment = (documents[key] for key in ("capsule", "contracts", "deployment"))
    for doc in (capsule, deployment):
        require(doc["metadata"]["tenant"] == "examples" and doc["metadata"]["name"] == "measurement-echo", "candidate-fixture-scope-mismatch")
    require(capsule["component"]["digest"] == deployment["spec"]["release"] == component["sha256"]
            and deployment["spec"]["service"] == "measurement-echo", "candidate-fixture-release-mismatch")
    require(capsule["exports"] == ["examples:echo/api@0.1.0"] and contracts["format_version"] == 1, "candidate-fixture-contract-mismatch")
    for budget in (capsule["execution"]["limits"], deployment["spec"]["resources"]):
        require(budget["cpuFuel"] == 10_000_000_000 and budget["memoryBytes"] == 16_777_216
                and budget["logBytes"] == 16384 and budget.get("wallTimeLimitMillis") in (None, 1000), "candidate-persisted-grant-mismatch")
    require(any(interface.get("id") == "examples:echo/api@0.1.0" for descriptor in contracts["contracts"]
                for interface in descriptor["interfaces"]), "candidate-echo-interface-missing")
    return deployment
