"""Use the same protected node, retained publications and authenticated APIs."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import os
from pathlib import Path
import re
import signal
import sys
import time

from tools.phase2_operator_process import Process, read_json, stopped_record, write_json
from tools.phase2_operator_scenario import NODE_ID, TOKEN, receipt, stop
from tools.rust_capsule_project import read_file

from . import configuration as cfg
from .evidence import native
from .inputs import decode, digest, require

KEY = b"aggregate/count"
PATHS = {"command": "/transaction/command", "query": "/transaction/query",
         "scan": "/transaction/scan", "result": "/transaction/result"}


class Node:
    def __init__(self, client, executable: Path, directory: Path):
        self.client, self.executable, self.directory = client, executable, directory
        self.process, self.ordinal = None, 0
        self.shutdown = []

    def start(self, configuration: Path):
        require(self.process is None and self.ordinal < 6, "bounded-exclusive-node-session")
        self.ordinal += 1
        process = Process([str(self.executable), "serve", "--config", str(configuration)], self.directory,
            dict(self.client.environment, HOME=str(self.directory)), self.client.cancellation, maximum=262144)
        try:
            started = process.line(min(self.client.deadline, time.monotonic() + 120))
            process.startup_record = started
            endpoint = started.get("endpoint", "")
            require(re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", endpoint), "actual-node-endpoint")
            path = self.client.directory / f"client-{self.ordinal}.json"
            write_json(path, {"formatVersion": 1, "defaultProfile": "operator", "profiles": [{
                "name": "operator", "endpoint": "http://" + endpoint, "tenant": cfg.TENANT, "token": TOKEN,
                "connectTimeoutMillis": 2000, "rpcTimeoutMillis": 15000}]})
            self.client.config, self.client.node = path, process
            until = min(self.client.deadline, time.monotonic() + 10)
            while True:
                actual = self.client.call("node", "get", NODE_ID)["data"]
                if actual["inventory"]["health"]["ready"]:
                    break
                require(time.monotonic() < until, "actual-node-readiness")
                time.sleep(0.025)
            self.process = process
            self.client.evidence.record(f"node-{self.ordinal}-started", started)
            return process
        except BaseException:
            self.client.node = None
            process.close()
            self.client.evidence.write(f"node-{self.ordinal}-startup.stdout", bytes(process.buffers[0]))
            self.client.evidence.write(f"node-{self.ordinal}-startup.stderr", bytes(process.buffers[1]))
            self.client.evidence.record(f"node-{self.ordinal}-startup-failure", {
                "exitStatus": process.owner.process.returncode, "reaped": process.closed and process.owner.finished,
                "started": getattr(process, "startup_record", None)})
            raise

    def stop(self):
        require(self.process is not None, "original-node-owner-required")
        process = self.process
        try:
            with self.client.cancellation.defer():
                try:
                    stop(self.client, process)
                finally:
                    self.client.evidence.write(f"node-{self.ordinal}.stdout", bytes(process.buffers[0]))
                    self.client.evidence.write(f"node-{self.ordinal}.stderr", bytes(process.buffers[1]))
                observed = stopped_record(process)
                self.client.evidence.record(f"node-{self.ordinal}-stopped", observed)
                require_retirement(observed["record"]["report"])
                self.shutdown.append(observed)
        finally:
            self.process = None

    def close(self):
        if self.process is not None:
            process = self.process
            try:
                self.stop()
            finally:
                process.close()

    def crash(self):
        """A controlled kill of this still-reserved leader, never a peer PID."""
        require(self.process is not None, "original-node-owner-required")
        process = self.process
        self.client.node = None
        try:
            require(not process.owner.exited(), "crash-requires-live-original-leader")
            os.kill(process.owner.process.pid, signal.SIGKILL)
            actual = process.complete(min(self.client.deadline, time.monotonic() + 10))
            require(actual.returncode == -signal.SIGKILL, "actual-controlled-node-crash")
        finally:
            process.close()
            self.process = None
            self.client.evidence.write(f"node-{self.ordinal}-crash.stdout", bytes(process.buffers[0]))
            self.client.evidence.write(f"node-{self.ordinal}-crash.stderr", bytes(process.buffers[1]))
            self.client.evidence.record(f"node-{self.ordinal}-crash", {
                "exitStatus": process.owner.process.returncode, "processId": process.owner.process.pid,
                "reaped": process.closed and process.owner.finished,
                "cleanShutdownObserved": False, "nativeRetirementReportObserved": False})


class Peer:
    def __init__(self, client, directory: Path, tls: Path, credential: Path, incarnation: str):
        self.client, self.directory, self.incarnation = client, directory, incarnation
        environment = dict(client.environment, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
        self.process = Process([sys.executable, "-m", "tools.java_transaction_qualification.provider",
            "--root", str(directory), "--tls", str(tls), "--token-file", str(credential),
            "--incarnation", incarnation, "--deadline", str(client.deadline)], client.directory,
            environment, client.cancellation, maximum=262144)
        self.shutdown = None
        try:
            started = self.process.line(min(client.deadline, time.monotonic() + 10))
            require(set(started) == {"port", "providerIncarnation"}
                    and type(started["port"]) is int and 1 <= started["port"] <= 65535
                    and started["providerIncarnation"] == incarnation, "actual-owned-recipient-listener")
            self.port = started["port"]
            client.evidence.record("recipient-started", started)
        except BaseException:
            self.process.close()
            raise

    def stop(self):
        require(self.shutdown is None, "original-recipient-stop-once")
        with self.client.cancellation.defer():
            self.process.stop()
            lines = bytes(self.process.buffers[0]).splitlines()
            require(len(lines) == 1, "original-recipient-stopped-record")
            observed = decode(lines[0], 8192)
            require(observed["schemaVersion"] == "latent.synthetic.put-once-recipient.v1"
                    and observed["providerIncarnation"] == self.incarnation
                    and observed["recipientDeliveryQualified"] is False
                    and self.process.closed and self.process.owner.finished
                    and self.process.owner.process.returncode == 0, "actual-recipient-retirement")
            self.shutdown = {"reaped": True, "processId": self.process.owner.process.pid, "record": observed}
            self.client.evidence.write("recipient.stdout", bytes(self.process.buffers[0]))
            self.client.evidence.write("recipient.stderr", bytes(self.process.buffers[1]))
            self.client.evidence.record("recipient-stopped", self.shutdown)

    def close(self):
        if self.shutdown is None:
            try:
                self.stop()
            finally:
                self.process.close()


def admission_lease_interval(client):
    # This is the original configured five-second supply-chain lease, not a
    # readiness witness. Reopening occurs only after actual clean retirement.
    until = time.monotonic() + 6
    require(until < client.deadline, "original-admission-lease-interval")
    while time.monotonic() < until:
        client.cancellation.check()
        time.sleep(min(0.1, until - time.monotonic()))


def publish(client, signed: Path, items) -> dict[str, str]:
    release_set = read_json(signed / "release-set.json")
    require(release_set["trust"] == "ephemeral-native-package-test-only"
            and int(release_set["expiresAtUnixSeconds"]) > time.time() + 300, "fresh-native-package-fixture-trust")
    result = {}
    for item in items:
        if item.name == "forbidden-http":
            continue
        selected = [row for row in release_set["releases"] if row["name"] == "java718-" + item.name]
        require(len(selected) == 1 and selected[0]["componentDigest"] == item.component_digest,
                "original-signed-component-association")
        original = selected[0]
        root = signed / original["name"]
        operation = "java-publish-" + item.name
        data = client.call("release", "publish-package", root / "package", "--evidence", root / "evidence/index.json",
                           "--operation-id", operation, "--expected-generation", "0")["data"]
        actual = data["operation"]
        require(data["release"]["digest"] == item.component_digest
                and actual["publication"]["id"].startswith("publication:sha256:"), "actual-signed-publication")
        require(client.call("release", "operation", operation)["data"]["receipt"] == actual,
                "original-publication-operation-lookup")
        result[item.name] = actual["publication"]["id"]
        client.evidence.passed("publish-" + item.name, {"signed": original, "admission": actual})
    require(len(result) == 4 and len(set(result.values())) == 4, "exact-distinct-original-publications")
    return result


def inspect(client, node: Path, configuration: Path, operations):
    from .policies import ObservedHosts
    value = decode(native(client, node, "transaction-host-inspection", "inspect-transaction-hosts",
                          "--config", configuration, timeout=120), 262144)
    return ObservedHosts.read(value, operations)


def namespace_arguments(publication: str):
    require(re.fullmatch(r"publication:sha256:[0-9a-f]{64}", publication), "original-authorization-publication")
    return ("--namespace", cfg.NAMESPACE, "--incarnation", "1", "--authorization-publication", publication)


def schema(item) -> str:
    raw = read_file(item.directory / "project/transaction-binding.json", 128 * 1024)
    require(digest(raw) == item.companion_digest, "retained-original-companion")
    value = decode(raw)
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", value["stateSchema"]), "original-signed-state-schema")
    return value["stateSchema"]


def create_namespace(client, item, publication):
    quotas = {name: "8388608" for name in ("stateBytes", "resultBytes", "effectBytes", "payloadBytes")}
    quotas.update(stateKeys="4096", resultRows="4096", effectRows="4096", recoveryBytes="1048576")
    path = client.directory / "namespace-create.json"
    write_json(path, {"stateSchema": schema(item), "quota": quotas})
    result = client.call("state", "create", *namespace_arguments(publication), "--operation-id", "java-create",
                         "--expected-generation", "0", "--configuration", path)
    actual = result["data"]["receipt"]
    require(result["outcomeKnown"] and actual["operationId"] == "java-create"
            and actual["authenticatedOperator"] == cfg.OPERATOR
            and actual["stateSchema"] == schema(item)
            and result["data"]["auditAcknowledgement"] is not None, "actual-authorized-namespace-create")
    client.evidence.passed("namespace-create", result["data"])
    return actual


def inspect_namespace(client, publication):
    value = client.call("state", "inspect", *namespace_arguments(publication))["data"]["namespace"]
    require(isinstance(value, dict) and re.fullmatch(r"0|[1-9][0-9]*", value["commandCount"]),
            "actual-namespace-command-count")
    return value


def deploy(client, signed: Path, item, publication: str, grants, authority: str):
    manifest = read_json(signed / ("java718-" + item.name) / "deployment.json")
    require(manifest["spec"]["release"] == item.component_digest, "original-deployment-component")
    manifest["spec"].update(publication=publication, grants=grants)
    prior = client.call("deployment", "get", cfg.DEPLOYMENT, "--operation-snapshot", codes=(0, 6))["data"]
    path = client.directory / f"deployment-{client.calls}.json"
    write_json(path, manifest)
    operation = f"java-deploy-{client.calls}"
    receipt(client.call("--rpc-timeout-ms", "300000", "deployment", "apply", path, "--operation-id", operation,
        "--expected-generation", prior["deployment"]["generation"] if prior.get("deployment") else "0",
        "--expected-state-version", prior["stateVersion"], timeout=310), operation)
    deployed = client.call("deployment", "get", cfg.DEPLOYMENT)["data"]["deployment"]
    snapshot = client.call("route", "get")["data"]["snapshot"]
    selected = [row for row in snapshot["services"] if row["routeId"] == cfg.DEPLOYMENT]
    require(len(selected) == 1 and len(selected[0]["revisions"]) == 1, "one-actual-route-revision")
    target = {"service": cfg.SERVICE, "contract": cfg.CONTRACT, "route": cfg.DEPLOYMENT,
        "publication": publication, "revision": selected[0]["revisions"][0]["revisionId"],
        "deploymentGeneration": int(deployed["generation"])}
    for mode in PATHS:
        function = mode if mode in {"query", "scan"} else "update"
        _trigger(client, authority, item, dict(target, function=function), mode)
    client.evidence.passed("deploy-" + item.name, {"deployment": deployed, "selectedTarget": target})
    return target


def _trigger(client, authority, item, target, mode):
    name = "java-transaction-" + mode
    prior = client.call("trigger", "get", name, codes=(0, 6))["data"]
    configuration = {"profile": "transaction-http-v1", "scheme": "http", "host": authority,
        "path": PATHS[mode], "pathMatch": "exact", "method": "POST" if mode == "command" else "GET",
        "transactionMode": "query" if mode == "scan" else mode,
        "namespace": cfg.NAMESPACE, "incarnation": "1", "stateSchema": schema(item),
        "companionDigest": item.companion_digest, "stateBinding": cfg.DEPLOYMENT, "resultPolicy": cfg.RESULT_POLICY}
    if mode == "command":
        configuration["preconditionKey"] = base64.b64encode(KEY).decode()
    path = client.directory / f"{name}-{client.calls}.json"
    write_json(path, {"apiVersion": "latent.dev/v1alpha1", "kind": "HttpTrigger",
        "metadata": {"name": name, "tenant": cfg.TENANT}, "spec": {"target": target, "configuration": configuration}})
    operation = f"java-trigger-{client.calls}"
    result = client.call("trigger", "apply", path, "--operation-id", operation,
        "--expected-generation", prior["trigger"]["generation"] if prior["trigger"] else "0",
        "--expected-state-version", prior["stateVersion"])
    receipt(result, operation)


@contextmanager
def as_user(client, subject=cfg.ALICE):
    require(subject in cfg.TOKENS and client.node is not None, "actual-configured-transport-user")
    path = client.directory / f"user-profile-{client.calls}.json"
    write_json(path, {"formatVersion": 1, "defaultProfile": "operator", "profiles": [{"name": "operator",
        "endpoint": "http://" + client.node.startup_record["endpoint"],
        "tenant": "foreign" if subject == cfg.FOREIGN else cfg.TENANT, "token": cfg.TOKENS[subject],
        "connectTimeoutMillis": 2000, "rpcTimeoutMillis": 15000}]})
    original = client.config
    client.config = path
    try:
        yield
    finally:
        client.config = original


def lookup(client, publication, original_key):
    with as_user(client):
        return client.call("transaction", "lookup", *namespace_arguments(publication),
                           "--operation", "update", "--client-key", original_key)["data"]["command"]


def effect(client, publication, original_key, effect_id):
    with as_user(client):
        return client.call("transaction", "effect", *namespace_arguments(publication), "--operation", "update",
                           "--client-key", original_key, "--effect-id", effect_id)["data"]["effect"]


def require_retirement(report):
    """Positive actual owner counters; idle work is not physical retirement."""
    require(report["clean"] is True, "actual-node-clean-retirement")
    for name in ("activeConnections", "activeRpcs", "activeControlJobs", "activeActivations",
                 "cancellationRegistrations", "observerCorrelations", "quotaReservations", "queuedReservations",
                 "reservedCpuFuel", "reservedMemoryBytes", "activeLeases", "queuedActivations", "quarantinedCells",
                 "activeBackendInvocations", "instanceReservations", "preparingComponents", "liveStores",
                 "liveHostStates", "liveInstances", "liveTemporaryBuffers", "liveCancellationProbes"):
        require(type(report[name]) is int and report[name] == 0, "actual-node-retired-owner-counter")
    state = report.get("state")
    require(isinstance(state, dict) and state["clean"] is True
            and state["nativeQuarantined"] is False and state["storeQuarantined"] is False
            and state["storeEngine"] == "closed" and state["storeThreadsJoined"] > 0,
            "actual-protected-engine-closed")
    for name in ("ordinaryReservations", "ordinaryBytes", "recoveryReservations", "recoveryBytes",
                 "storeAcceptedJobs", "storeRetainedBytes", "storePhysicalOwners", "storeQueuedRetirements",
                 "storeLiveWorkers"):
        require(type(state[name]) is int and state[name] == 0, "actual-state-physical-retirement")
