"""Finite resource profiles for actual signed Angular on the existing protected T1 node."""
from __future__ import annotations

import hashlib
import time

from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_node import pages, sample, settled_samples
from tools.phase3_resource_profile import digest, integer, quiescent, summary, validate_schedule
from tools.phase3_resource_render import RenderClient, finish, prepare_observed, spawn
from tools.phase3_resource_os import Probe
from tools.phase3_resource_schedule import run_open_loop
from tools.phase3_resource_storage import storage_snapshot
from tools.phase3_resource_workload import overload_counts
from tools.phase3_web_qualification import cancel_render, native_cache_audit
from tools.phase3_web_scenario import (
    TENANT, client_profile, configure_angular_node, deploy, fixture_metadata,
    http_response, invoke, prepare, publish, trigger,
)
from tools.run_security_profile_workflow import replace_config


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
    config, settings = configure_angular_node(client, directories["node"], args.fixture_root, args.compiler)
    settings["workers"]["runtime"] = profile["cells"]
    settings["cells"][0].update(capacity=profile["cells"], queueCapacity=2)
    settings["catalogs"]["deployments"] = profile["dormantSteps"][-1] + 1
    settings["cache"].update(entries=2, preparations=1)
    settings["audit"].update(records=4096, diskBytes=33554432)
    replace_config(config, settings)
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
        began = time.monotonic_ns()
        prepare(client, publications["angular"], 1, wait=15000)
        result["warmPreparationNanos"] = str(time.monotonic_ns() - began)
        result["nativeCacheHits"] = native_cache_audit(client, records["angular"], "cache-hit")
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
            result["cancellations"].append(cancel_render(client, records["angular"],
                f"resource-angular-cancel-{cycle}", disconnect=cycle % 2 == 1))
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


def validate_web(value):
    profile, samples = value["profile"], value["samples"]
    require(profile["kind"] == "web" and value["angularBuild"]["actualAngularBuild"] is True,
            "resource-angular-profile")
    require(value["catalog"]["components"] == 1 and value["catalog"]["packages"] == 2
            and value["catalog"]["publications"] == 2, "resource-angular-distinct-catalog-counts")
    require(value["catalog"]["dormantPopulations"] and [row["admitted"] for row in value["catalog"]["dormantPopulations"]]
            == profile["dormantSteps"], "resource-angular-density-populations")
    for phase in ("fixed", "dormant", "warm", "active", "recovery", "unrouted"):
        selected = [row for row in samples if row["phase"] == phase]
        require(bool(selected), "resource-angular-missing-phase")
        for row in selected:
            require(row["os"]["identity"] == value["nodeIdentity"] and row["os"]["metrics"]["rssBytes"] > 0,
                    "resource-angular-sample-owner")
            if phase != "active":
                require(quiescent(row), "resource-angular-retained-owner")
    for count in profile["dormantSteps"]:
        require(sum(row["phase"] == "dormant" and row["dormantDeployments"] == count for row in samples)
                == profile["samplesPerPhase"], "resource-angular-density-samples")
    require(len(value["cycles"]) == profile["cycles"] and len(value["cancellations"]) == profile["cycles"],
            "resource-angular-cycle-population")
    for cycle in value["cycles"]:
        validate_schedule(cycle["arrivals"], profile["arrivalsPerCycle"], profile["arrivalIntervalMillis"] * 1_000_000)
        require(any(row["disposition"] == "completed" and row["result"]["category"] == "success"
                    for row in cycle["arrivals"]), "resource-angular-churn-no-success")
    require(value["preparation"]["reaped"] and value["nativeCacheMisses"] and value["nativeCacheHits"],
            "resource-angular-preparation-evidence")
    require(value["shutdown"]["reaped"] is True and value["shutdown"]["record"]["clean"] is True
            and value["temporaryOutputsRemoved"] is True and value["fixtureUnchanged"] is True,
            "resource-angular-cleanup")
    require(value["overloadClassification"] == overload_counts(value["overload"]), "resource-angular-overload")
    dormant = [row for row in samples if row["phase"] == "dormant"]
    checks = {"requestedDormantPopulationsAdmitted": True,
              "dormantProcessesPlateau": len({row["os"]["metrics"]["processes"] for row in dormant}) == 1,
              "dormantThreadsPlateau": len({row["os"]["metrics"]["threads"] for row in dormant}) == 1,
              "dormantListenersPlateau": len({row["os"]["metrics"]["listeners"] for row in dormant}) == 1,
              "liveRendererCellsObserved": any(integer(cell["active"]) > 0 for row in samples if row["phase"] == "active"
                                                for cell in row["inventory"]["cellCapacity"]),
              "activeOwnershipReturns": all(quiescent(row) for row in samples if row["phase"] == "recovery")}
    if value["checks"]:
        require(value["checks"] == checks, "resource-angular-checks-changed")
    value["checks"] = checks
    value["analysis"] = {"osRanges": {phase: {key: summary([row["os"]["metrics"][key]
        for row in samples if row["phase"] == phase]) for key in
        ("processes", "threads", "listeners", "sockets", "handles", "rssBytes")}
        for phase in ("fixed", "dormant", "warm", "active", "recovery", "unrouted")},
        "latencyNanos": {heat: summary([integer(row["elapsedNanos"]) for row in value["calls"]
            if row["heat"] == heat]) for heat in ("cold", "warm", "failure", "recovery")},
        "rendererHeapBytes": None, "rendererHeapReason": "JS-allocator-not-exported-RSS-is-not-heap",
        "universalPerformanceClaim": False}
    require(all(checks.values()), "resource-angular-plateau-check-failed")
    return True
