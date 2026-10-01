"""Signed ordinary Java server execution through the authenticated shared listener."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import ssl
import tempfile
import time

from tools.build_process_signals import owned_cancellation
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.dev_workflow import state
from tools.dev_workflow.client import Client as RouteClient
from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import read_json, write_json, require, stopped_record
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_node import RecordingClient, deploy
from tools.rust_capsule_project import digest, fresh, read_file
from tools import server_routes, server_source

CONTEXT = ("latent:context/context@0.1.0", "activation-context-v1", "activation-id", "context")
IDLE_OWNERS = {
    "execution-cell-leases", "prepared-instance-reservations", "guest-invocations", "guest-stores",
    "guest-host-states", "guest-component-instances", "guest-value-buffers", "guest-cancellation-probes",
    "resident-service-processes", "resident-service-threads", "resident-service-listeners",
    "invocation-cleanup-slots", "http-exchanges", "http-buffer-reservations",
}


def runtime_config(settings: dict, service: str) -> None:
    settings["providers"] = {"formatVersion": 1, "bindings": []}
    for name, (capability, _profile, _operation, _kind) in {**profiles("java"), "context": CONTEXT}.items():
        settings["providers"][name] = {"identity": {"id": name, "tenant": "examples", "service": "runtime-host", "epoch": 1}}
        settings["providers"]["bindings"].append({"name": name + "-server", "tenant": "examples",
            "consumerService": service, "providerService": "runtime-host", "contract": capability,
            "providerBinding": name + "-installed"})


def grant_runtime(client, node, record, publication) -> list[dict]:
    grants = []
    for name, (capability, profile, operation, kind) in {**profiles("java"), "context": CONTEXT}.items():
        descriptor = next(row for row in node.startup_record["providers"] if row["id"] == name)
        binding, policy = client.directory / (name + "-binding.json"), client.directory / (name + "-policy.json")
        write_json(binding, {"formatVersion": 1, "tenant": "examples", "capability": capability,
            "providerProfile": profile, "configurationDigest": descriptor["configurationDigest"],
            "configurationEpoch": 1, "restriction": {"operations": [operation]}})
        client.call("policy", "--kind", "provider-binding", "apply", "--id", name + "-installed", "--file", binding,
                    "--operation-id", "install-" + name, "--expected-generation", "0")
        write_json(policy, {"formatVersion": 1, "tenant": "examples", "rules": [{
            "id": "runtime", "effect": "allow", "principals": [{"kind": "trigger", "subject": "server-caller"}],
            "services": [record["service"]], "publications": [publication], "capability": capability,
            "operations": [operation], "resources": {"kind": kind},
            "ceiling": {"operations": 4 if name == "context" else 4096, "inputBytes": 0,
                        "outputBytes": 512 if name == "context" else 32768, "wallTimeMillis": 5000}}]})
        client.call("policy", "apply", "--id", name + "-allow", "--file", policy,
                    "--operation-id", "grant-" + name, "--expected-generation", "0")
        grants.append({"capability": capability, "policy": name + "-allow"})
    return grants


def observe_idle(client, evidence: Path, name: str) -> dict:
    deadline = min(client.deadline, time.monotonic() + 5)
    for _attempt in range(100):
        inventory = client.call("node", "get", "operator-workflow-test")["data"]["inventory"]
        require(inventory["topology"]["available"], "java-server-ownership-unavailable")
        entries = {row["name"]: row for row in inventory["topology"]["entries"]}
        require(IDLE_OWNERS <= entries.keys(), "java-server-ownership-missing")
        usage = inventory["quotas"]["usage"]
        cells = inventory["cellCapacity"]
        require(cells and all(row["observationAvailable"] for row in cells), "java-server-cell-observation-unavailable")
        idle = (all(entries[key]["activeCount"] == "0" for key in IDLE_OWNERS)
            and all(row["active"] == 0 and row["quarantined"] == 0 and row["available"] == row["total"] for row in cells)
            and all(int(usage[key]) == 0 for key in ("activeActivations", "queuedActivations", "reservedCpuFuel", "reservedMemoryBytes")))
        if idle:
            observation = {"owners": {key: entries[key] for key in sorted(IDLE_OWNERS)}, "quotas": usage,
                           "cells": cells, "topologyComplete": inventory["topology"]["complete"]}
            write_json(evidence / (name + ".json"), observation)
            return observation
        require(time.monotonic() < deadline, "java-server-physical-retirement-deadline")
        time.sleep(0.025)
    raise RuntimeError("java-server-physical-retirement-attempt-bound")


def request(endpoint: str, method: str, path: str, *, authority="java.server.test", body=None, headers=None,
            tls_context=None) -> dict:
    host, port = endpoint.rsplit(":", 1)
    connection = (http.client.HTTPConnection(host, int(port), timeout=125) if tls_context is None else
                  http.client.HTTPSConnection("localhost", int(port), timeout=125, context=tls_context))
    try:
        connection.request(method, path, body=body, headers={"Host": authority, **(headers or {})})
        response = connection.getresponse()
        value = response.read(262145)
        require(len(value) <= 262144, "java-server-http-response-limit")
        return {"method": method, "path": path, "authority": authority,
                "scheme": "http" if tls_context is None else "https", "status": response.status,
                "headers": response.getheaders(), "body": value.hex()}
    finally:
        connection.close()


def run(binary: Path, node_binary: Path, fixture: Path, build: Path, evidence: Path, *, helper=False,
        tls_tool: Path | None = None) -> dict:
    evidence = fresh(evidence)
    record = read_json(fixture / "release-set.json")["releases"][0]
    result = {"schemaVersion": "lsf.java.server.node-conformance.v1", "status": "in-progress", "http": [],
              "componentDigest": record["componentDigest"], "sourceSnapshotDigest": record["sourceSnapshotDigest"],
              "profile": "lsf.java.httpserver.buffered.v1", "helperSource": helper}
    observed_paths = {"cli": binary, "node": node_binary, "workflow": Path(__file__),
        "declaration": build / "server-source.json", "profile": build / "server-profile.json",
        "sourceInputs": build / "source-inputs.json", "component": build / "component.wasm"}
    if helper:
        require(tls_tool is not None, "java-server-cookie-qualification-requires-tls-fixture-tool")
        observed_paths["tlsFixtureTool"] = tls_tool
    result["inputs"] = {name: file_identity(path) for name, path in observed_paths.items()}
    node = None
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix="lsf-java-server-node-") as temporary:
        root = Path(temporary)
        for name in ("client", "node", "routes"): (root / name).mkdir(mode=0o700)
        client = RecordingClient(binary, root / "client", cancellation, time.monotonic() + 900,
            evidence=evidence / "control", control_timeout_millis=125000)
        try:
            tls_context = None
            transport = {"mode": "loopback"}
            scheme = "http"
            if helper:
                tls_directory = root / "tls"
                tls = run_bounded_result([str(tls_tool), "fixture-tls", str(tls_directory)], root,
                                         build_environment(root), 30, 16384)
                require(tls.returncode == 0, "java-server-tls-fixture-preparation")
                tls_context = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(read_file(tls_directory / "ca.der")))
                transport = {"mode": "tls", "certificateFile": str(tls_directory / "server.pem"),
                             "privateKeyFile": str(tls_directory / "key.pem")}
                scheme = "https"
                result["tls"] = {"certificate": file_identity(tls_directory / "server.pem"),
                    "certificateAuthority": file_identity(tls_directory / "ca.der"),
                    "verifiedTransportHostname": "localhost", "logicalAuthority": "java.server.test"}
            config = configure_node(root / "node", fixture, "examples")
            settings = read_json(config)
            settings["engine"] = {"javaGuest": True}
            settings["credentials"].append({"token": "LSF-PUBLIC-JAVA-SERVER-FOREIGN-TEST-ONLY",
                "subject": "foreign-operator", "tenant": "foreign", "role": "operator"})
            settings["execution"].update(maximumWallTimeMillis=120000, maximumCpuFuel=10000000000)
            settings["limits"] = {"maximumComponentBytes": 16777216, "maximumPayloadBytes": 2097152}
            settings["budgetProfile"] = {"mode": "phase3", "maximumOutboundRequests": 8,
                "maximumBlobReadBytes": 65536, "maximumBlobWriteBytes": 65536}
            settings["capabilityPolicies"] = {"formatVersion": 1, "maximumControlJobs": 2, "store": {
                "maximumRecords": 64, "maximumOutcomes": 128, "maximumCatalogBytes": 4194304,
                "maximumReadOwners": 64, "maximumPageRecords": 16}}
            runtime_config(settings, record["service"])
            settings["httpIngress"] = {"formatVersion": 1, "bind": "127.0.0.1:0", "transport": transport,
                "authentication": {"mode": "public-origins", "origins": [
                    {"authority": "java.server.test", "subject": "server-caller", "tenant": "examples"},
                    {"authority": "foreign.server.test", "subject": "foreign-caller", "tenant": "foreign"}]},
                "limits": {"maximumConnections": 4, "maximumExchanges": 2, "maximumBufferBytes": 16777216,
                    "maximumRequestsPerConnection": 4, "maximumConnectionAgeMillis": 180000}}
            config.write_bytes(json.dumps(settings, separators=(",", ":")).encode())
            node = connect(client, node_binary, root / "node", config, "examples", 1)
            result["startup"] = node.startup_record
            observe_idle(client, evidence, "dormant-before-publication")
            package = fixture / record["name"] / "package"
            unsigned = client.call("release", "publish-package", package, "--operation-id", "unsigned-server",
                                   "--expected-generation", "0", codes=(4,))
            require(unsigned["error"]["code"] == "permission-denied", "unsigned-server-admitted")
            published = client.call("release", "publish-package", package,
                "--evidence", fixture / record["name"] / "evidence/index.json", "--operation-id", "publish-server",
                "--expected-generation", "0", timeout=125)
            publication = published["data"]["operation"]["publication"]["id"]
            result["publication"] = publication
            deployed = deploy(client, fixture / record["name"] / "deployment.json", publication, grants=[])
            result["deployment"] = deployed
            declaration = read_file(build / "server-source.json")
            profile = read_file(build / "server-profile.json")
            source = read_file(build / "source-inputs.json", 4 * 1024 * 1024)
            route_cli = RouteClient(binary, client.config, root / "routes", deadline=client.deadline)
            selected = server_routes.observed_pin(route_cli, "examples", deployed["name"], record["componentDigest"])
            mounts = {"schemaVersion": server_source.CONFIGURATION, "profileDigest": digest(profile), "mounts": [{
                "endpoint": "server", "name": "java-server", "scheme": scheme, "host": "java.server.test", "path": "/",
                "pathMatch": "prefix", "methods": ["GET", "HEAD", "POST"] if helper else ["GET", "HEAD"], "dispatch": "guest"}]}
            mounts["mounts"].append({**mounts["mounts"][0], "name": "java-server-foreign", "host": "foreign.server.test"})
            manifests = server_routes.plan(declaration, json.dumps(mounts, separators=(",", ":")).encode(), selected,
                source_digest=digest(source), profile_digest=digest(profile))
            owner = {"tenant": "examples", "route": deployed["name"], "clientConfigDigest": digest(read_file(client.config))}
            routes = server_routes.Routes(root / "routes", route_cli, owner)
            with state.lock(root / "routes", "server-routes.lock"): result["routes"] = routes.apply(manifests)
            endpoint = node.startup_record["httpEndpoint"]

            def check(method, path, expected, value=None, **options):
                observed = request(endpoint, method, path, tls_context=tls_context, **options)
                result["http"].append(observed)
                ordinal = str(len(result["http"]))
                write_json(evidence / ("http-" + ordinal + ".json"), observed)
                require(observed["status"] == expected, "java-server-shared-http-status-" + ordinal)
                if value is not None: require(bytes.fromhex(observed["body"]) == value, "java-server-shared-http-body-" + ordinal)
                observe_idle(client, evidence, "retirement-" + ordinal)
                return observed

            def denied_without_cell(method, path, expected, **options):
                before = observe_idle(client, evidence, "before-denial-" + str(len(result["http"]) + 1))
                check(method, path, expected, **options)
                after = observe_idle(client, evidence, "after-denial-" + str(len(result["http"])))
                require([row["granted"] for row in before["cells"]] == [row["granted"] for row in after["cells"]],
                        "denied-server-route-created-cell")

            before_grants = observe_idle(client, evidence, "before-runtime-grants")
            check("GET", "/hey", 403)
            after_denial = observe_idle(client, evidence, "after-runtime-grant-denial")
            result["missingRuntimeGrants"] = {"status": "denied", "httpStatus": 403,
                "cellLeasesBefore": [row["granted"] for row in before_grants["cells"]],
                "cellLeasesAfter": [row["granted"] for row in after_denial["cells"]],
                "retirement": after_denial, "storeCreation": "not-observed"}
            grants = grant_runtime(client, node, record, publication)
            deployed = deploy(client, fixture / record["name"] / "deployment.json", publication,
                generation=str(deployed["generation"]), grants=grants)
            result["deployment"] = deployed
            selected = server_routes.observed_pin(route_cli, "examples", deployed["name"], record["componentDigest"])
            manifests = server_routes.plan(declaration, json.dumps(mounts, separators=(",", ":")).encode(), selected,
                source_digest=digest(source), profile_digest=digest(profile))
            with state.lock(root / "routes", "server-routes.lock"): result["routes"] = routes.apply(manifests)
            denied_without_cell("GET", "/hey", 403, authority="unconfigured.server.test")
            denied_without_cell("GET", "/hey", 403, authority="foreign.server.test")
            denied_without_cell("DELETE", "/hey", 403)
            denied_without_cell("DELETE", "/hey", 404, headers={"Origin": scheme + "://java.server.test"})
            denied_without_cell("GET", "/hey", 401, headers={"Authorization": "Bearer qualification-only"})
            for path in ("/hey/%2Fsecret", "/hey/%252fsecret", "/hey/../case", "/hey//child"):
                denied_without_cell("GET", path, 400)
            for path, expected in (("/hey", 200), ("/hey/child", 201 if helper else 200), ("/heyday", 200),
                                   ("/hey?x=1", 200), ("/hey/", 201 if helper else 200), ("/HEY", 404), ("/absent", 404)):
                check("GET", path, expected, b"Hey!" if expected == 200 else b"L" if expected == 201 else None)
            if helper:
                head = check("HEAD", "/hey", 200, b"")
                require([value for name, value in head["headers"] if name.lower() == "content-length"] == ["4"],
                        "java-server-head-representation-length")
                raw = check("GET", "/case?raw", 200, bytes((0, 1, 128, 255)))
                require([value for name, value in raw["headers"] if name.lower() == "set-cookie"]
                    == ["__Host-a=1; Secure; HttpOnly; SameSite=Strict; Path=/",
                        "__Host-b=2; Secure; HttpOnly; SameSite=Strict; Path=/"], "java-server-repeated-response-cookies")
                check("GET", "/case?query&x=%2F&x=+", 200, b"query&x=%2F&x=+")
                check("POST", "/case?input", 200, bytes((255, 0, 128)), body=bytes((255, 0, 128)),
                      headers={"Content-Type": "application/octet-stream", "Origin": scheme + "://java.server.test"})
                check("GET", "/case?error", 500, b"E")
                check("GET", "/case?no-body", 204, b"")
                for case in ("throw", "over", "under", "double", "before", "closed", "flush", "chunk", "forbidden", "unsafe-cookie", "oversize", "memory"):
                    check("GET", "/case?" + case, 502)
                    check("GET", "/hey", 200, b"Hey!")
                check("POST", "/case?input", 502, body=b"x" * 65537,
                      headers={"Content-Type": "application/octet-stream", "Origin": scheme + "://java.server.test"})
                check("GET", "/hey", 200, b"Hey!")
            result["idle"] = observe_idle(client, evidence, "dormant-after-requests")
            with state.lock(root / "routes", "server-routes.lock"):
                routes.remove([row["metadata"]["name"] for row in manifests])
            denied_without_cell("GET", "/hey", 404)
            stop(client, node)
            result["shutdown"] = stopped_record(node)
            require(result["shutdown"]["reaped"] and result["shutdown"]["record"]["clean"], "java-server-clean-shutdown")
            result["inputsAfter"] = {name: file_identity(path) for name, path in observed_paths.items()}
            require(result["inputsAfter"] == result["inputs"], "java-server-source-or-binary-changed")
            result["status"] = "passed"
        except BaseException as error:
            result.update(status="failed", reason=str(error) if isinstance(error, RuntimeError) else type(error).__name__,
                          failedCall=client.failed_call)
            if client.node is not None:
                try: write_json(evidence / "failure-inventory.json", client.call("node", "get", "operator-workflow-test")["data"])
                except Exception as failure: result["observationFailure"] = type(failure).__name__
                try:
                    for page in range(4):
                        arguments = ("audit", "query", "--scope", "tenant", "--page-size", "64")
                        if page:
                            arguments += ("--page-token", token)
                        data = client.call(*arguments)["data"]
                        write_json(evidence / ("failure-audit-" + str(page) + ".json"), data)
                        token = data["page"]["nextPageToken"]
                        if token is None: break
                    result["failureAuditComplete"] = token is None
                except Exception as failure: result["auditObservationFailure"] = type(failure).__name__
            raise
        finally:
            client.node = None
            if node is not None: node.close()
            write_json(evidence / "conformance.json", result)
    return result
