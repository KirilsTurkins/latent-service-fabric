"""The fixed control/Invoke schedule; every child uses the maintained owner."""
from __future__ import annotations

import json
import os
import signal
import time

from tools.phase2_gate_resource_os import Probe
from tools.phase2_gate_resource_profile import (
    PROFILE, compact_inventory, configuration, digest, quiet, shutdown_report,
)
from tools.phase2_operator_canary import invoke
from tools.phase2_operator_process import Client, read_json, require, write_json
from tools.phase2_operator_scenario import NODE_ID, connect, receipt, route, route_identity


class BoundedClient(Client):
    def __init__(self, *args):
        super().__init__(*args)
        self.controls = 0
        self.invocations = 0

    def call(self, *arguments, **keywords):
        invocation = "invoke" in arguments
        if invocation:
            require(self.invocations < PROFILE["invocations"], "invoke-budget")
            self.invocations += 1
        else:
            require(self.controls < PROFILE["maximumControls"], "control-budget")
            self.controls += 1
        return super().call(*arguments, **keywords)


def pause(client, seconds):
    until = min(client.deadline, time.monotonic() + seconds)
    while time.monotonic() < until:
        client.cancellation.check()
        if client.node:
            client.node.drain()
        time.sleep(min(0.025, max(0, until - time.monotonic())))
    require(time.monotonic() < client.deadline, "resource-deadline")


def samples(client, probe, phase, result):
    for _ in range(PROFILE["samplesPerPhase"]):
        for _ in range(PROFILE["settleAttempts"]):
            observed = client.call("node", "get", NODE_ID)["data"]["inventory"]
            if quiet(observed):
                break
            pause(client, PROFILE["settleIntervalMillis"] / 1000)
        else:
            require(False, "inventory-settle-bound")
        pause(client, PROFILE["sampleIntervalMillis"] / 1000)
        require(len(result["samples"]) < PROFILE["osSamples"], "sample-budget")
        result["samples"].append({
            "phase": phase, "inventory": compact_inventory(observed), "os": probe.sample(),
        })


def publish(client, fixture, package):
    name = package["name"]
    value = client.call(
        "release", "publish-package", fixture / name / "package",
        "--evidence", fixture / name / "evidence/index.json",
        "--operation-id", "resource-publish-" + name, "--expected-generation", "0",
    )
    require(value["outcomeKnown"] and value["data"]["release"]["digest"] == package["componentDigest"],
            "resource-publication")
    record = value["data"]["operation"]["record"]
    require(record["packageDigest"] == package["packageDigest"]
            and record["componentDigest"] == package["componentDigest"], "resource-publication-package")


def manifest(client, fixture, ordinal, package):
    value = read_json(fixture / package["name"] / "deployment.json")
    value["metadata"]["name"] = f"resource-{ordinal:02}"
    # Positive equal weights are independently valid; they need not sum to 10000
    # across ordinary deployments. The fixture's capsule remains unchanged.
    value["spec"]["route"]["weight"] = 10000
    path = client.directory / f"deployment-{ordinal:02}-{package['name']}.json"
    write_json(path, value)
    return path


def apply(client, path, name, operation):
    state = client.call("deployment", "get", name, "--operation-snapshot", codes=(0, 6))["data"]
    old = state.get("deployment")
    value = receipt(client.call(
        "deployment", "apply", path, "--operation-id", operation,
        "--expected-state-version", state["stateVersion"],
        "--expected-generation", old["generation"] if old else "0",
    ), operation)
    require(value["deploymentId"] == name, "resource-deployment-identity")
    return value


def delete(client, name):
    state = client.call("deployment", "get", name, "--operation-snapshot")["data"]
    result = client.call(
        "deployment", "delete", name, "--operation-id", "resource-delete-" + name,
        "--expected-state-version", state["stateVersion"],
        "--expected-generation", state["deployment"]["generation"],
    )
    operation = result["data"]["operation"]
    require(result["outcomeKnown"] and operation["operationId"] == "resource-delete-" + name,
            "resource-delete-identity")
    stored = client.call("deployment", "operation", "resource-delete-" + name)["data"]["receipt"]
    require(stored["deploymentId"] == name and stored["receiptDigest"] == operation["receiptDigest"],
            "resource-delete-receipt")


def catalogs(client, metadata, deployment_count):
    releases = client.call("release", "list", "--page-size", "64")["data"]
    require(releases["nextPageToken"] is None and len(releases["releases"]) == 32,
            "resource-release-count")
    require({row["digest"] for row in releases["releases"]} ==
            {row["componentDigest"] for row in metadata["packages"]}, "resource-release-identities")
    deployments = client.call("deployment", "list", "--page-size", "32")["data"]
    require(deployments["nextPageToken"] is None and len(deployments["deployments"]) == deployment_count,
            "resource-deployment-count")
    expected = {f"resource-{index:02}" for index in range(deployment_count)}
    require({row["manifest"]["metadata"]["name"] for row in deployments["deployments"]} == expected,
            "resource-deployment-cohort")
    allowed = {row["componentDigest"] for row in metadata["packages"][:2]}
    require(all(row["manifest"]["spec"]["release"] in allowed for row in deployments["deployments"]),
            "resource-deployment-release")


def stop(client, node, result):
    client.node = None
    try:
        require(not node.owner.exited(), "resource-node-premature-exit")
        os.kill(node.owner.process.pid, signal.SIGTERM)
        completed = node.complete(time.monotonic() + PROFILE["shutdownSeconds"])
        require(completed.returncode == 0, "resource-node-shutdown")
        lines = completed.stdout.splitlines()
        require(len(lines) == 1 and len(lines[0]) <= 16384, "resource-shutdown-frame")
        value = json.loads(lines[0])
        require(value["schemaVersion"] == "latent.standalone.status.v1"
                and value["event"] == "stopped" and value["clean"], "resource-shutdown-status")
        result["shutdown"] = shutdown_report(value["report"])
        result["process"]["exitedSuccessfully"] = True
        result["process"]["reapedByOwner"] = bool(node.owner.finished and
                                                  node.owner.process.returncode == 0)
    finally:
        node.close()


def run(client, binary, directory, fixture, metadata, result):
    client.cancellation.check()
    require(time.monotonic() < client.deadline, "resource-deadline")
    config_value = configuration(metadata["tenant"])
    write_json(directory / "policy.json", read_json(fixture / "policy.json"))
    config = directory / "node.json"
    write_json(config, config_value)
    public_config = dict(config_value)
    public_config["credentials"] = [
        {key: value for key, value in item.items() if key != "token"}
        for item in config_value["credentials"]
    ]
    result["configuration"] = public_config
    result["configurationDigest"] = digest(config_value)
    node = connect(client, binary, directory, config, metadata["tenant"], 1)
    try:
        probe = Probe(node, binary, result["build"]["nodeSha256"], client.deadline)
        result["process"] = probe.identity
        packages = metadata["packages"]
        input_path = client.directory / "invoke.json"
        write_json(input_path, metadata["input"])
        for ordinal in range(2):
            publish(client, fixture, packages[ordinal])
            applied = apply(client, manifest(client, fixture, 0, packages[ordinal]),
                            "resource-00", f"resource-warm-{ordinal}")
            observed = invoke(client, metadata, input_path, f"resource-warm-{ordinal}")
            require(observed["releaseDigest"] == packages[ordinal]["componentDigest"]
                    and observed["routeGeneration"] == applied["routeGeneration"], "resource-warm-revision")
            result["invocations"].append(observed)
        samples(client, probe, "baseline", result)

        for package in packages[2:]:
            publish(client, fixture, package)
        for ordinal in range(1, 16):
            apply(client, manifest(client, fixture, ordinal, packages[ordinal % 2]),
                  f"resource-{ordinal:02}", f"resource-apply-{ordinal:02}")
        catalogs(client, metadata, 16)
        dormant_route = route(client)
        result["catalog"] = {"peakReleases": 32, "peakDeployments": 16,
                             "dormantRouteGeneration": dormant_route["generation"],
                             "dormantRouteDigest": digest(route_identity(dormant_route))}
        samples(client, probe, "dormant", result)
        # The fixed thirty calls exercise only the two prepared images. There
        # is no probabilistic coverage loop or newly generated component here.
        for ordinal in range(30):
            observed = invoke(client, metadata, input_path, f"resource-cohort-{ordinal:02}")
            require(observed["releaseDigest"] in {p["componentDigest"] for p in packages[:2]}
                    and observed["routeGeneration"] == dormant_route["generation"],
                    "resource-cohort-revision")
            result["invocations"].append(observed)
        samples(client, probe, "reclaimed", result)

        for ordinal in range(16):
            delete(client, f"resource-{ordinal:02}")
        catalogs(client, metadata, 0)
        removed_route = route(client)
        require(not removed_route["bindings"] and not removed_route["services"]
                and int(removed_route["generation"]) > int(dormant_route["generation"]),
                "resource-routes-not-removed")
        result["catalog"].update({
            "remainingDeployments": 0, "retainedReleases": 32,
            "unroutedGeneration": removed_route["generation"],
            "unroutedDigest": digest(route_identity(removed_route)),
        })
        samples(client, probe, "unrouted", result)
        stop(client, node, result)
    finally:
        client.node = None
        node.close()
        if "process" in result:
            result["process"]["cleanupReapedByOwner"] = bool(node.owner.finished)
        result["controls"] = client.controls
        result["invokeAttempts"] = client.invocations
