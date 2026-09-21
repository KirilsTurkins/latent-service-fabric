"""Finite resource profiles for actual signed Angular on the existing protected T1 node."""
from __future__ import annotations

import hashlib
import time

from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_node import pages, sample, settled_samples
from tools.phase3_resource_profile import digest, integer, quiescent, summary, validate_schedule
from tools.phase3_resource_render import RenderClient, consumption, finish, prepare_observed, spawn
from tools.phase3_resource_os import Probe
from tools.phase3_resource_schedule import run_open_loop
from tools.phase3_resource_storage import failure_storage, storage_snapshot
from tools.phase3_resource_workload import overload_counts
from tools.phase3_web_qualification import cancel_render, native_cache_audit
from tools.phase3_web_scenario import (
    TENANT, client_profile, configure_angular_node, deploy, fixture_metadata,
    http_response, invoke, prepare, publish, trigger,
)
from tools.run_security_profile_workflow import replace_config


def configure(client, directory, fixture, compiler, profile):
    require(profile["controlJobs"] == 2, "resource-angular-observer-control-budget")
    config, settings = configure_angular_node(client, directory, fixture, compiler)
    settings["workers"].update(runtime=profile["cells"], control=profile["controlJobs"])
    settings["cells"][0].update(capacity=profile["cells"], queueCapacity=2)
    settings["catalogs"]["deployments"] = profile["dormantSteps"][-1] + 1
    settings["cache"].update(entries=2, preparations=1)
    settings["audit"].update(records=4096, diskBytes=33554432)
    replace_config(config, settings)
    return config, settings


def warm_cache_observed(before, after):
    require(integer(after["hits"]) > integer(before["hits"])
            and all(after[key] == before[key] for key in
                    ("entries", "misses", "sourceBytes", "compiledImageBytes", "metadataBytes"))
            and integer(after["entries"]) > 0 and integer(after["compiledImageBytes"]) > 0,
            "resource-angular-prepared-cache-hit")
    return {"before": before, "after": after, "scope": "in-memory-prepared-cache-not-native-disk-cache"}


def observed_summary(values):
    known = [value for value in values if value is not None]
    measured = summary(known) if known else {"count": 0, "minimum": None, "maximum": None, "p50": None, "p95": None}
    return {**measured, "sampleCount": len(values), "unavailableCount": len(values) - len(known)}


def web_run(args, result, cancellation, temporary, deadline):
    require(args.compiler is not None and args.compiler.is_absolute(), "resource-angular-compiler-required")
    result["compiler"] = file_identity(args.compiler)
    metadata, records = fixture_metadata(args.fixture_root)
    result["angularBuild"] = metadata
    result["evidenceScope"] = "actual-signed-Angular-protected-T1-standalone-resource-profile"
    result["pendingAcceptance"] = ["JS-allocator-heap-not-exported", "standalone-event-secret-child-provider-matrix",
                                   "OCI-token-resolver-redirect-pool-campaign", "real-browser-parent-owned"]
    directories = {name: temporary / name for name in ("node", "client")}
    for directory in directories.values():
        directory.mkdir(mode=0o700)
    client = RenderClient(args.cli, directories["client"], cancellation, deadline)
    client.observations, client.samples = result["calls"], result["samples"]
    client.sampled_activations, client.heat = set(), "setup"
    profile = result["profile"]
    config, settings = configure(client, directories["node"], args.fixture_root, args.compiler, profile)
    result.update(configuration=settings, configurationDigest=digest(settings))
    node = None
    try:
        node = connect(client, args.node, directories["node"], config, TENANT, 1)
        client_profile(client, 1)
        client.probe = Probe(node, result["build"]["binaries"]["node"])
        result["nodeIdentity"] = client.probe.identity
        result["samples"] += settled_samples(client, client.probe, "fixed", 0, profile["samplesPerPhase"], False)
        result["storage"] = [{"phase": "fixed", **storage_snapshot(directories["node"], deadline)}]
        publications = {name: publish(client, args.fixture_root, name)["publication"]["id"]
                        for name in ("angular", "alternate")}
        result["publications"] = publications
        result["catalog"] = {"components": len({records[name]["componentDigest"] for name in publications}),
                             "packages": len({records[name]["packageDigest"] for name in publications}),
                             "publications": len(set(publications.values())), "dormantPopulations": [],
                             "scope": "fresh-owned-catalog-exact-successful-signed-web-admissions"}
        names, deployment = [], None
        for count in profile["dormantSteps"]:
            for ordinal in range(len(names), count):
                name = "angular" if ordinal == 0 else f"resource-angular-{ordinal:03}"
                current = deploy(client, records["angular"], publications["angular"], "deploy-" + name, name=name)
                if ordinal == 0:
                    deployment = current
                names.append(name)
            observed = pages(client, "deployment", "deployments")
            require(len(observed) == count, "resource-angular-dormant-count")
            result["catalog"]["dormantPopulations"].append({"requested": count, "admitted": len(observed),
                                                         "pageDigest": digest(observed)})
            result["samples"] += settled_samples(client, client.probe, "dormant", count,
                                                  profile["samplesPerPhase"], False)
        require(all(integer(row["inventory"]["cacheSummary"]["entries"]) == 0
                    for row in result["samples"] if row["phase"] == "dormant"), "resource-angular-eager-preparation")
        client.dormant = len(names)
        result["storage"].append({"phase": "dormant", **storage_snapshot(directories["node"], deadline)})
        prepare_observed(client, publications["angular"], result)
        result["nativeCacheMisses"] = native_cache_audit(client, records["angular"], "cache-miss")
        before_warm = sample(client, client.probe, "prepared", len(names), False)
        result["samples"].append(before_warm)
        began = time.monotonic_ns()
        prepare(client, publications["angular"], 1, wait=15000)
        result["warmPreparationNanos"] = str(time.monotonic_ns() - began)
        after_warm = sample(client, client.probe, "warm-preparation", len(names), False)
        result["samples"].append(after_warm)
        result["warmPreparedCache"] = warm_cache_observed(before_warm["inventory"]["cacheSummary"],
                                                         after_warm["inventory"]["cacheSummary"])
        result["storage"].append({"phase": "prepared", **storage_snapshot(directories["node"], deadline)})
        for heat in ("cold", "warm"):
            client.heat = heat
            rendered = invoke(client, records["angular"], publications["angular"], "resource-angular-" + heat)
        result["samples"] += settled_samples(client, client.probe, "warm", len(names), profile["samplesPerPhase"], False)
        installed_trigger = trigger(client, records["angular"], publications["angular"], deployment,
                                    rendered["revision"], "alice.angular.test")
        began = time.monotonic_ns()
        body, headers = http_response(client, node, "alice.angular.test")
        require(b"ngh=" in body and b"Alice&lt;unsafe&gt;" in body, "resource-angular-shared-ingress")
        result["httpIngress"] = {"elapsedNanos": str(time.monotonic_ns() - began), "bodyBytes": len(body),
                                 "bodySha256": "sha256:" + hashlib.sha256(body).hexdigest(), "headers": headers}
        result["cancellations"] = []
        for cycle in range(profile["cycles"]):
            client.heat = "failure"
            failure = invoke(client, records["angular"], publications["angular"],
                             f"resource-angular-exception-{cycle}", "/exception", codes=(4,))
            require(failure["category"] == "platform-failure", "resource-angular-failure-not-observed")
            cancelled = cancel_render(client, records["angular"],
                f"resource-angular-cancel-{cycle}", disconnect=cycle % 2 == 1)
            terminal = client.call("activation", "get", cancelled["activationId"])["data"]
            require(terminal["terminalState"] == "cancelled", "resource-angular-cancellation-changed")
            cancelled["consumption"] = consumption(terminal)
            result["cancellations"].append(cancelled)
            client.heat = "recovery"
            invoke(client, records["angular"], publications["angular"], f"resource-angular-recovery-{cycle}")
            rows = run_open_loop(profile["arrivalsPerCycle"], profile["arrivalIntervalMillis"] * 1_000_000,
                profile["maximumOutstanding"],
                lambda ordinal: spawn(client, records["angular"], f"resource-angular-cycle-{cycle}-{ordinal}"),
                lambda process: finish(client, process, records["angular"], publications["angular"]),
                lambda: (cancellation.check(), node.drain()), int(deadline * 1_000_000_000))
            result["cycles"].append({"ordinal": cycle, "arrivals": rows})
            result["samples"] += settled_samples(client, client.probe, "recovery", len(names),
                                                  profile["samplesPerPhase"], False)
        overload(client, records["angular"], publications["angular"], profile, result)
        client.heat = "post-overload"
        invoke(client, records["angular"], publications["angular"], "resource-angular-after-overload")
        state = client.call("trigger", "get", installed_trigger)["data"]
        client.call("trigger", "delete", installed_trigger, "--operation-id", "resource-delete-trigger",
                    "--expected-generation", state["trigger"]["generation"], "--expected-state-version", state["stateVersion"])
        for name in names:
            state = client.call("deployment", "get", name, "--operation-snapshot")["data"]
            client.call("deployment", "delete", name, "--operation-id", "delete-" + name,
                        "--expected-generation", state["deployment"]["generation"],
                        "--expected-state-version", state["stateVersion"])
        require(not pages(client, "deployment", "deployments"), "resource-angular-unrouted-count")
        result["samples"] += settled_samples(client, client.probe, "unrouted", 0, profile["samplesPerPhase"], False)
        result["storage"].append({"phase": "unrouted", **storage_snapshot(directories["node"], deadline)})
        stop(client, node)
        result["shutdown"] = stopped_record(node)
        node = None
    finally:
        result["controlCommands"] = client.calls
        if hasattr(client, "last_failure"):
            result["lastControlFailure"] = client.last_failure
        if node is not None:
            result["nodeFailureStderr"] = bytes(node.buffers[1])[-8192:].decode("utf-8", "replace")
            result["failureStorage"] = failure_storage(directories["node"])
            node.close()
            result["nodeForcedCleanup"] = {"reaped": node.owner.finished, "exitCode": node.owner.process.returncode}


def overload(client, record, publication, profile, result):
    processes = []
    result["overload"] = []
    try:
        for ordinal in range(profile["maximumOutstanding"]):
            processes.append(spawn(client, record, f"resource-angular-overload-{ordinal}", "/spin"))
        result["samples"].append(sample(client, client.probe, "active", client.dormant, False))
        for process in processes:
            result["overload"].append(finish(client, process, record, publication))
        result["overloadClassification"] = overload_counts(result["overload"])
    finally:
        for process in processes:
            process.close()


def renderer_memory(value):
    """Invocation high-water marks, not sampled RSS or live JS allocator bytes."""
    ceiling = value["configuration"]["cells"][0]["maximumMemoryBytes"]
    groups = {heat: [row["result"] for row in value["calls"] if row["heat"] == heat]
              for heat in ("cold", "warm", "failure", "recovery", "post-overload")}
    groups["cancelled"] = value["cancellations"]
    groups["churn"] = [row["result"] for cycle in value["cycles"] for row in cycle["arrivals"]
                       if row["disposition"] == "completed"]
    groups["overload"] = value["overload"]
    observed = {}
    for name, rows in groups.items():
        peaks = []
        for row in rows:
            measured = consumption(row)
            peak = None if measured is None else integer(measured["peakMemoryBytes"])
            require(peak is None or peak <= ceiling, "resource-render-memory-ceiling")
            if name not in ("churn", "overload", "cancelled") or row.get("category") == "success":
                require(peak is not None and peak > 0, "resource-render-memory-not-observed")
            peaks.append(peak)
        require(bool(rows), "resource-render-memory-population")
        observed[name] = observed_summary(peaks)
    return {"scope": "per-invocation-aggregate-Wasm-linear-memory-high-water-mark",
            "source": "runtime-BudgetConsumption-peakMemoryBytes",
            "configuredPerInvocationCeilingBytes": ceiling, "peakBytes": observed,
            "includesJavaScriptEngineHeap": True, "javaScriptAllocatorLiveBytes": None,
            "cancellationConsumption": "terminal-status-does-not-retain-consumption",
            "processRssIsSeparate": True, "sumOfPeaksIsNotConcurrentUsage": True}


def validate_web(value):
    profile, samples = value["profile"], value["samples"]
    require(profile["kind"] == "web" and value["angularBuild"]["actualAngularBuild"] is True,
            "resource-angular-profile")
    require(value["catalog"]["components"] == 1 and value["catalog"]["packages"] == 2
            and value["catalog"]["publications"] == 2, "resource-angular-distinct-catalog-counts")
    require(value["catalog"]["dormantPopulations"] and all(
        [row[key] for row in value["catalog"]["dormantPopulations"]] == profile["dormantSteps"]
        for key in ("requested", "admitted")), "resource-angular-density-populations")
    require(value["configuration"]["workers"]["control"] == profile["controlJobs"] == 2,
            "resource-angular-observer-control-budget")
    for phase in ("fixed", "dormant", "warm", "active", "recovery", "unrouted"):
        selected = [row for row in samples if row["phase"] == phase]
        require(bool(selected), "resource-angular-missing-phase")
        for row in selected:
            require(row["os"]["identity"] == value["nodeIdentity"] and row["os"]["metrics"]["rssBytes"] > 0,
                    "resource-angular-sample-owner")
            if phase != "active":
                require(quiescent(row), "resource-angular-retained-owner")
                scoped = [entry for entry in row["inventory"]["topology"]["entries"]
                          if entry["ownership"] == "activation-scoped"]
                require(scoped and all(integer(entry["activeCount"]) == 0 for entry in scoped),
                        "resource-angular-retained-runtime-owner")
    for count in profile["dormantSteps"]:
        require(sum(row["phase"] == "dormant" and row["dormantDeployments"] == count for row in samples)
                == profile["samplesPerPhase"], "resource-angular-density-samples")
    require(len(value["cycles"]) == profile["cycles"] and len(value["cancellations"]) == profile["cycles"],
            "resource-angular-cycle-population")
    for cycle in value["cycles"]:
        validate_schedule(cycle["arrivals"], profile["arrivalsPerCycle"], profile["arrivalIntervalMillis"] * 1_000_000)
        require(any(row["disposition"] == "completed" and row["result"]["category"] == "success"
                    for row in cycle["arrivals"]), "resource-angular-churn-no-success")
    require(value["preparation"]["reaped"] and value["preparation"]["exitCode"] == 0
            and value["preparation"]["result"]["category"] == "success" and value["nativeCacheMisses"],
            "resource-angular-preparation-evidence")
    warm_cache = value["warmPreparedCache"]
    require(warm_cache == warm_cache_observed(warm_cache["before"], warm_cache["after"]),
            "resource-angular-cache-evidence")
    require(sum(row["phase"] == "recovery" for row in samples) == profile["cycles"] * profile["samplesPerPhase"],
            "resource-angular-recovery-population")
    require(all(row["terminal"] == "cancelled" for row in value["cancellations"])
            and {row["disconnect"] for row in value["cancellations"]} == {False, True},
            "resource-angular-cancellation-populations")
    for heat, count, category in (("cold", 1, "success"), ("warm", 1, "success"),
                                  ("failure", profile["cycles"], "platform-failure"),
                                  ("recovery", profile["cycles"], "success"), ("post-overload", 1, "success")):
        selected = [row for row in value["calls"] if row["heat"] == heat]
        require(len(selected) == count and all(row["processReaped"] and row["result"]["category"] == category
                and row["result"]["outcomeKnown"] for row in selected), "resource-angular-call-population")
    require(value["shutdown"]["reaped"] is True and value["shutdown"]["record"]["clean"] is True
            and value["temporaryOutputsRemoved"] is True and value["fixtureUnchanged"] is True,
            "resource-angular-cleanup")
    require(value["overloadClassification"] == overload_counts(value["overload"]), "resource-angular-overload")
    dormant = [row for row in samples if row["phase"] == "dormant"]
    resident_cache = [row["inventory"]["cacheSummary"] for row in samples
                      if row["phase"] in ("warm", "recovery", "unrouted")]
    checks = {"requestedDormantPopulationsAdmitted": True,
              "dormantProcessesPlateau": len({row["os"]["metrics"]["processes"] for row in dormant}) == 1,
              "dormantThreadsPlateau": len({row["os"]["metrics"]["threads"] for row in dormant}) == 1,
              "dormantListenersPlateau": len({row["os"]["metrics"]["listeners"] for row in dormant}) == 1,
              "liveRendererCellsObserved": any(integer(cell["active"]) > 0 for row in samples if row["phase"] == "active"
                                                for cell in row["inventory"]["cellCapacity"]),
              "activeOwnershipReturns": all(quiescent(row) for row in samples if row["phase"] == "recovery")}
    checks["preparedCachePlateau"] = len({tuple(integer(cache[key]) for key in
        ("entries", "sourceBytes", "compiledImageBytes", "metadataBytes")) for cache in resident_cache}) == 1
    if value["checks"]:
        require(value["checks"] == checks, "resource-angular-checks-changed")
    value["checks"] = checks
    value["analysis"] = {"osRanges": {phase: {key: observed_summary([row["os"]["metrics"][key]
        for row in samples if row["phase"] == phase]) for key in
        ("processes", "threads", "listeners", "sockets", "handles", "rssBytes")}
        for phase in ("fixed", "dormant", "preparation", "prepared", "warm", "active", "recovery", "unrouted")},
        "cacheRanges": {phase: {key: summary([integer(row["inventory"]["cacheSummary"][key])
            for row in samples if row["phase"] == phase]) for key in
            ("entries", "sourceBytes", "compiledImageBytes", "metadataBytes", "preparing", "evictions")}
            for phase in ("fixed", "dormant", "prepared", "warm", "recovery", "unrouted")},
        "latencyNanos": {heat: summary([integer(row["elapsedNanos"]) for row in value["calls"]
            if row["heat"] == heat]) for heat in ("cold", "warm", "failure", "recovery")},
        "rendererMemory": renderer_memory(value),
        "rendererHeapBytes": None, "rendererHeapReason": "JS-allocator-not-exported-Wasm-high-water-mark-is-separate",
        "universalPerformanceClaim": False}
    require(all(checks.values()), "resource-angular-plateau-check-failed")
    return True
