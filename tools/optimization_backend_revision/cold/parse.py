"""Bind the cold collector's complete offer/job/resource graph to retained inputs."""
from tools.optimization_evidence.common import fields, integer, read_json, require, sha256, uint
from tools.phase1_evidence.resources import Samples, idle, shutdown
from tools.phase1_paired.common import INPUT
from . import attempts, model, controls as control_checks
from .observer import Observer


def configuration(value, variant):
    fields(value, "formatVersion dataDirectory nodeId bind workers cells execution catalogs cache retention telemetry shutdownGraceMillis")
    require(value["formatVersion"] == 1 and value["nodeId"] == "cold-comparison"
            and value["dataDirectory"] == "data" and value["bind"] == "127.0.0.1:0", "cold-configuration-identity")
    require(value["workers"] == {"runtime":2,"control":4}
            and value["cells"] == [{"class":"standard","capacity":4,"queueCapacity":64,"maximumMemoryBytes":67_108_864}]
            and value["execution"] == {"maximumCpuFuel":10_000_000_000,"maximumWallTimeMillis":5000,"maximumLogBytes":16384}, "cold-execution-controls")
    cache = {"entries":8,"sourceBytes":134_217_728,"metadataBytes":67_108_864,"compiledImageBytes":536_870_912,"preparations":4}
    if variant == "candidate":
        cache["compilerWorkers"] = 2
    require(value["cache"] == cache and value["catalogs"] == {"releaseEntries":16,"releaseIndexBytes":16_777_216,"deployments":16,"deploymentStateBytes":16_777_216}
            and value["retention"] == {"terminalEntries":2048,"terminalTtlMillis":60_000,"bytes":536_870_912}
            and value["telemetry"] == {"queueEntries":256,"retainedEntries":128,"retainedBytes":1_048_576}
            and value["shutdownGraceMillis"] == 1000, "cold-capacity-controls")


def fixtures(value, artifacts, directory, echo):
    require(isinstance(value, list) and len(value) == 8, "cold-fixture-count")
    base = artifacts.path(echo["component"]).read_bytes()
    original_contracts = artifacts.json(echo["contracts"])
    releases = []
    for index,row in enumerate(value):
        fields(row, "key directory artifact component publication target")
        require(row["key"] == str(index) and row["directory"] == f"fixtures/key-{index}", "cold-fixture-order")
        parent = directory / row["directory"]
        component = row["component"]
        require(component["path"] == "echo-component.wasm", "cold-component-path")
        actual = artifacts.nested(parent,component).read_bytes()
        require(actual == base + (bytes([0,2,0,index]) if index else b""), "cold-fixture-treatment-changed")
        digest = sha256(actual)
        releases.append(digest)
        artifact = fields(row["artifact"], "component_sha256 component_bytes stored_descriptor_reference capsule contracts deployment")
        require(artifact["component_sha256"] == digest and uint(artifact["component_bytes"]) == len(actual)
                and artifact["stored_descriptor_reference"] == "local:release:"+digest, "cold-published-artifact-mismatch")
        documents = {}
        for name in ("capsule","contracts","deployment"):
            ref = artifact[name]
            require(ref["path"] == f"echo-{name}.json" and uint(ref["bytes"]) <= 1024**2, "cold-metadata-path")
            documents[name] = read_json(artifacts.nested(parent,ref),1024**2)
        capsule,contracts,deployment = (documents[name] for name in ("capsule","contracts","deployment"))
        require(contracts == original_contracts and capsule["exports"] == ["examples:echo/api@0.1.0"]
                and capsule["component"]["digest"] == deployment["spec"]["release"] == digest
                and deployment["spec"]["service"] == f"cold-key-{index}", "cold-fixture-semantics")
        for document in (capsule,deployment):
            require(document["metadata"]["tenant"] == "examples" and document["metadata"]["name"] == f"cold-key-{index}", "cold-fixture-scope")
        for budget in (capsule["execution"]["limits"],deployment["spec"]["resources"]):
            require(budget["cpuFuel"] == 10_000_000_000 and budget["memoryBytes"] == 16_777_216
                    and budget["logBytes"] == 16384 and budget.get("wallTimeLimitMillis") in (None,1000), "cold-persisted-grants")
        require(row["publication"] == {"release_digest":digest,"deployment_id":f"cold-key-{index}",
                "object_generation":"1","catalog_generation":str(index+1)}, "cold-publication-stamp")
        require(row["target"] == {"tenant":"examples","service":f"cold-key-{index}","contract":"examples:echo/api@0.1.0","function":"echo"}, "cold-target-changed")
    require(len(set(releases)) == 8, "cold-components-not-distinct")
    return releases


def parse(value, selected, identity, artifacts, raw_path, echo, variant):
    fields(value, "schema plan identity configuration effective_options semantic_input clock startup fixtures initial_observer configured_runtimes "
           "population samples status reason elapsed_micros work before_shutdown shutdown data_cleanup runtime_threads_after_join final_observer")
    require(value["schema"] == "latent.optimization.cold-arm.v1" and value["plan"] == selected
            and value["identity"] == identity and value["status"] == "passed" and value["reason"] is None, "cold-arm-not-passed")
    count,commands = model.population(selected["profile"])
    require(value["population"] == {"attempts":str(count),"commands":str(commands)}
            and value["work"] == {"invoke_attempts":str(count),"commands":str(commands),"budget_exhausted":False}, "cold-population-count")
    configuration(value["configuration"],variant)
    require(value["effective_options"] == {
        "cpu_fuel":"10000000000","memory_bytes":"16777216","wall_time_limit_millis":"1000","log_bytes":"16384",
        "pool_capacity":"4","queue_capacity":"64","runtime_workers":"2","control_workers":"4",
        "prepared_cache_maximum_entries":"8","allocator":"on_demand","copy_on_write":True,"prepared_cache_enabled":True,
        "fuel_async_yield_interval":"10000","maximum_wasm_stack_bytes":"524288","async_stack_bytes":"2097152",
        "hostcall_fuel":"131072"}, "cold-engine-controls")
    startup = fields(value["startup"],"catalog_open_nanos node_start_nanos client_connect_nanos excluded comparable_to_historical_startup")
    for name in ("catalog_open_nanos","node_start_nanos","client_connect_nanos"):
        uint(startup[name])
    require(startup["excluded"] == ["fixture-loading","runtime-construction"]
            and startup["comparable_to_historical_startup"] is False, "cold-startup-boundary")
    require(value["configured_runtimes"] == {"invocation":2,"control":4,"client":2}
            and value["runtime_threads_after_join"] == {"invocation":0,"control":0,"client":0}, "cold-runtimes-not-joined")
    require(value["semantic_input"] == {"utf8":INPUT,"sha256":sha256(INPUT.encode()),"bytes":"25"}, "cold-input-changed")
    clock = fields(value["clock"], "unix_origin_nanos clock_anchor_uncertainty_nanos")
    origin = uint(clock["unix_origin_nanos"])
    uint(clock["clock_anchor_uncertainty_nanos"])
    ticks = integer(identity["environment"]["clock_ticks_per_second"],1,1_000_000)
    releases = fixtures(value["fixtures"],artifacts,raw_path.parent,echo)
    rows = value["samples"]
    require(isinstance(rows,list) and len(rows) == count+17, "cold-event-count")
    starts = {row["phase"]:row for row in rows if row.get("kind") == "phase-anchor"}
    require(set(starts) == {"same-key","distinct","cancel"}, "cold-burst-manifest")
    expected = attempts.expected(selected["profile"],starts)
    tracker = Samples()
    snapshots = [row["node"] for row in rows if "node" in row] + [value["before_shutdown"]]
    for sample in snapshots:
        tracker.check(sample)
        cells = sample["inventory"]["cellCapacity"]
        require(len(cells) == 1 and cells[0]["total"] == 4 and cells[0]["queueCapacity"] == 64
                and sample["inventory"]["cacheSummary"]["maximumEntries"] == "8"
                and sample["inventory"]["cacheSummary"]["maximumConcurrentPreparations"] == "4", "cold-sampled-controls")
        require(sample["resources"]["descendants"] == [], "cold-collector-unowned-descendant")
    require(tracker.identity is not None, "cold-process-unobserved")
    observer = Observer(tracker.identity[0],releases,variant)
    observer.check(value["initial_observer"])
    require(not observer.records and not observer.jobs and value["initial_observer"]["snapshot"]["active_jobs"] == "0",
            "cold-header-already-prepared")
    found, normalized, pins = set(), [], {}
    checkpoints, ended, controls, begun, anchored, probed = [], [], [], [], [], []
    active_phase=None
    phase_finish=0
    start_captures={}
    for row in rows:
        kind = row.get("kind")
        if kind == "invoke":
            if row["phase"] in starts:
                require(active_phase == row["phase"] and anchored[-1:] == [active_phase], "cold-offer-outside-its-burst")
            require(row["activation_id"] not in found,"duplicate-cold-offer")
            found.add(row["activation_id"])
            normalized.append(attempts.validate(row,origin,releases,expected,pins))
        elif kind == "checkpoint":
            fields(row,"kind label node observer")
            checkpoints.append(row["label"])
            idle(row["node"],dormant=row["label"] == "empty")
        elif kind in ("phase-start","phase-end"):
            fields(row,"kind phase observer node " + ("" if kind == "phase-start" else "finished_nanos"))
            if kind == "phase-start":
                require(active_phase is None and uint(row["observer"]["collector_started_nanos"]) >= phase_finish,
                        "cold-overlapping-burst-phases")
                active_phase=row["phase"]
                start_captures[active_phase]=row["observer"]
                begun.append(row["phase"])
            if kind == "phase-end":
                require(active_phase == row["phase"], "cold-end-without-start")
                phase_finish=uint(row["finished_nanos"])
                require(uint(row["observer"]["collector_finished_nanos"]) <= phase_finish
                        and all(uint(item["retained_observed_nanos"]) <= phase_finish
                                for item in normalized if item["phase"] == active_phase), "cold-phase-ended-before-calls-drained")
                active_phase=None
                ended.append(row["phase"])
                idle(row["node"])
                control_checks.drained(row["observer"])
        elif kind == "phase-anchor":
            fields(row,"kind phase recorded_nanos offer_lead_nanos origin_nanos cold_due_nanos")
            require(row["offer_lead_nanos"] == "10000000"
                    and uint(row["origin_nanos"]) == uint(row["recorded_nanos"])+10_000_000
                    and begun[-1:] == [row["phase"]]
                    and uint(row["recorded_nanos"]) >= uint(start_captures[row["phase"]]["collector_finished_nanos"]), "cold-schedule-anchor")
            anchored.append(row["phase"])
        elif kind == "status-probe":
            fields(row,"kind phase activation_id started_nanos finished_nanos response retained_valid")
            require(row["activation_id"] == f"cold-{row['phase']}-cold-0000"
                    and row["retained_valid"] is True and row["phase"] == active_phase
                    and uint(starts[row["phase"]]["cold_due_nanos"])+2_000_000 <= uint(row["started_nanos"]) <= uint(row["finished_nanos"])
                    and row["response"]["grpc_code"] in (0,5), "cold-responsiveness-reply")
            if row["response"]["grpc_code"] == 0:
                require(row["response"]["activation_id"] == row["activation_id"], "cold-status-probe-crossed")
            controls.append(row)
            probed.append(row["phase"])
        elif kind == "cancellation":
            control_checks.cancellation(row,observer,releases[7])
            controls.append(row)
        else:
            require(False,"unknown-cold-event")
        if "observer" in row:
            observer.check(row["observer"])
    require(found == set(expected) and checkpoints == ["empty","after-warmup","after-baseline","after-healthy"]
            and ended == begun == anchored == probed == ["same-key","distinct","cancel"]
            and len(controls) == 4, "cold-missing-population")
    observer.check(value["final_observer"],final=True)
    compiled={observer.jobs[uint(row["job_id"])] for row in observer.records.values()
              if row["stage"] == "component_new" and row["succeeded"]}
    require({row["release_digest"] for row in normalized if row["outcome"] == "success"} <= compiled,
            "cold-success-without-observed-compilation")
    idle(value["before_shutdown"])
    shutdown(value["shutdown"],cells=4)
    require(("compiler" in value["shutdown"]) == (variant == "candidate"), "cold-shutdown-compiler-proof-absent-or-invented")
    if variant == "candidate":
        require(value["shutdown"]["compiler"] == {name:item if type(item) is bool else uint(item)
                for name,item in value["final_observer"]["snapshot"]["compiler"].items()}, "cold-final-compiler-proof-crossed")
    require(value["shutdown"]["quarantinedCells"] == 0 and value["data_cleanup"] == {"removed":True}, "cold-shutdown-failed")
    require(tracker.last_finished <= uint(value["elapsed_micros"]) <= model.maximum_seconds(selected["profile"])*1_000_000, "cold-arm-window")
    from .aggregate import summarize
    return {"samples":str(count),"process_identity":tracker.identity,"clock_ticks_per_second":ticks,
            **summarize(normalized,observer,controls,snapshots)}
