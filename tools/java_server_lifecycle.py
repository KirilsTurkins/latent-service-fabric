"""Additional real-catalog/shared-ingress Java server revision controls.

Consumes two independently built, signed ordinary-source server fixtures. It
does not construct HTTP activation inputs, execute Java on the host, retry an
operation, or report a pass from source/model inspection.
"""
from __future__ import annotations

import copy
import http.client
from pathlib import Path
import socket
import threading
import time

from tools import server_routes, server_source
from tools.dev_workflow import state
from tools.dev_workflow.common import DevError, digest, encode, require
from tools.phase2_operator_process import read_json, write_json
from tools.rust_capsule_node import deploy
from tools.rust_capsule_project import read_file
from tools.java_server_lifecycle_peer import GatePeer
from tools.phase3_resource_identity import file_identity

HTTP = "latent:http/streaming@0.3.0"
HTTP_OPERATIONS = ["open", "write", "finish", "read", "chunk-bytes", "trailers", "abort-upload", "abort-body"]


def roots(client, service):
    rows, token = [], None
    for _page in range(4):
        command = ["activation", "roots", "--service", service, "--page-size", 32]
        if token is not None:
            command += ["--page-token", token]
        value = client.call(*command)["data"]
        require(value["schemaVersion"] == 1 and value["retainedHistoryOnly"], "server-lifecycle-root-schema")
        rows.extend(value["nodes"])
        require(len(rows) <= 128, "server-lifecycle-root-bound")
        token = value["nextPageToken"]
        if token is None:
            return rows
    raise RuntimeError("server-lifecycle-root-pagination-bound")


def one_new_root(client, service, before):
    selected = [row for row in roots(client, service) if row["activationId"] not in before]
    require(len(selected) == 1, "server-lifecycle-exact-one-actual-http-root")
    return selected[0]["activationId"]


def status(client, activation, selected, *, terminal=None):
    observed = client.call("activation", "get", activation)["data"]
    metadata = observed["metadata"]
    require(observed["activationId"] == activation
            and metadata.get("revision") == selected["revision"]
            and metadata.get("release") == selected["componentDigest"]
            and metadata.get("route-generation") == selected["deploymentGeneration"],
            "server-lifecycle-original-resolved-pin-changed")
    if terminal is not None:
        require(observed["terminalState"] == terminal and observed["finalConsumption"] is not None,
                "server-lifecycle-terminal-outcome")
    return observed


class HeldIngress:
    def __init__(self, endpoint, tls_context, deadline):
        _host, port = endpoint.rsplit(":", 1)
        self.connection = http.client.HTTPSConnection("localhost", int(port),
            timeout=min(125, deadline - time.monotonic()), context=tls_context)
        self.deadline, self.response, self.failure = deadline, None, None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, name="java-server-owned-ingress", daemon=False)
        self.thread.start()

    def _run(self):
        try:
            self.connection.request("GET", "/gate", headers={"Host": "java.server.test", "Connection": "close"})
            response = self.connection.getresponse()
            body = response.read(262145)
            require(len(body) <= 262144, "server-lifecycle-held-response-bound")
            self.response = {"status": response.status, "body": body.hex()}
        except BaseException as error:
            self.failure = error
        finally:
            self.connection.close()
            self.done.set()

    def disconnect(self):
        transport = self.connection.sock
        require(transport is not None and not self.done.is_set(), "server-lifecycle-live-disconnect-required")
        transport.shutdown(socket.SHUT_RDWR)

    def finish(self):
        self.thread.join(max(0, min(125, self.deadline - time.monotonic())))
        require(not self.thread.is_alive(), "server-lifecycle-ingress-owner-not-reaped")
        if self.failure is not None:
            raise self.failure
        return self.response

    def close(self):
        if self.thread.is_alive():
            try:
                self.disconnect()
            except OSError:
                pass
        self.thread.join(2)
        require(not self.thread.is_alive(), "server-lifecycle-ingress-cleanup-unconfirmed")


class RevisionControls:
    def __init__(self, fixture: Path, build: Path, *, second_body: bytes, peer_port: int):
        require(type(peer_port) is int and 1 <= peer_port <= 65535,
                "server-lifecycle-explicit-peer-port")
        self.fixture, self.build, self.second_body, self.peer_port = fixture, build, second_body, peer_port

    def configure(self, settings: dict, service: str):
        providers = settings["providers"]
        require("httpStreaming" not in providers, "server-lifecycle-provider-collision")
        providers["httpStreaming"] = {"identity": {"id": "server-gate-http", "tenant": "examples",
            "service": "server-gate-host", "epoch": 1}, "configuration": {"formatVersion": 1,
            "destinations": [{"origin": {"scheme": "http", "host": "127.0.0.1", "port": self.peer_port},
                "addresses": {"networks": ["127.0.0.1/32"], "specialAddresses": ["127.0.0.1"]},
                "resolution": {"kind": "static", "addresses": ["127.0.0.1"]},
                "allowedRequestHeaders": [], "redirectDestinations": []}],
            "limits": {"maximumRequestBodyBytes": 4096, "maximumResponseBodyBytes": 4096,
                "maximumEncodedResponseBytes": 8192, "maximumHeaderBytes": 1024,
                "maximumHeaders": 8, "maximumRedirects": 0}, "extraRoots": [], "publicRoots": False},
            "limits": {"maximumInputBytes": 4096, "maximumOutputBytes": 4096,
                "maximumChunkBytes": 1024, "maximumOutstandingChunks": 2}}
        providers["bindings"].append({"name": "server-gate-http", "tenant": "examples",
            "consumerService": service, "providerService": "server-gate-host", "contract": HTTP,
            "providerBinding": "server-gate-http-installed"})

    def grant_http(self, client, node, service, publications):
        descriptor = next(row for row in node.startup_record["providers"] if row["id"] == "server-gate-http")
        require(descriptor["capability"] == HTTP and descriptor["profile"] == "bounded-streaming-http-identity-v1"
                and descriptor["tenant"] == "examples", "server-lifecycle-actual-http-provider")
        binding = client.directory / "server-gate-http-binding.json"
        write_json(binding, {"formatVersion": 1, "tenant": "examples", "capability": HTTP,
            "providerProfile": descriptor["profile"], "configurationDigest": descriptor["configurationDigest"],
            "configurationEpoch": 1, "restriction": {"operations": HTTP_OPERATIONS}})
        client.call("policy", "--kind", "provider-binding", "apply", "--id", "server-gate-http-installed",
                    "--file", binding, "--operation-id", "install-server-gate-http", "--expected-generation", "0")
        policy = client.directory / "server-gate-http-policy.json"
        write_json(policy, {"formatVersion": 1, "tenant": "examples", "rules": [{"id": "one-controlled-peer",
            "effect": "allow", "principals": [{"kind": "trigger", "subject": "server-caller"}],
            "services": [service], "publications": publications, "capability": HTTP,
            "operations": HTTP_OPERATIONS, "resources": {"kind": "http",
                "origins": [{"scheme": "http", "host": "127.0.0.1", "port": self.peer_port}],
                "methods": ["GET"], "paths": ["/gate"], "pathPrefixes": []},
            "ceiling": {"operations": 32, "inputBytes": 4096, "outputBytes": 16384, "wallTimeMillis": 120000}}]})
        client.call("policy", "apply", "--id", "server-gate-http-allow", "--file", policy,
                    "--operation-id", "grant-server-gate-http", "--expected-generation", "0")
        return {"capability": HTTP, "policy": "server-gate-http-allow"}

    def configure_ingress(self, settings):
        settings["httpIngress"]["authentication"]["origins"].append({"authority": "competing.server.test",
            "subject": "server-caller", "tenant": "examples"})

    def inputs(self):
        selected = read_json(self.fixture / "release-set.json")["releases"][0]["name"]
        paths = {"observer": Path(__file__), "peer": Path(__file__).with_name("java_server_lifecycle_peer.py"),
            "releaseSet": self.fixture / "release-set.json", "declaration": self.build / "server-source.json",
            "profile": self.build / "server-profile.json", "sourceInputs": self.build / "source-inputs.json",
            "component": self.build / "component.wasm", "buildReceipt": self.build / "BUILD-COMPLETE.json",
            "signedEvidence": self.fixture / selected / "evidence/index.json",
            "deployment": self.fixture / selected / "deployment.json"}
        return {name: file_identity(path) for name, path in paths.items()}

    def stopped(self, record):
        from tools.dev_workflow.node_output import provider_shutdown
        observed = provider_shutdown(record)
        require(observed is not None and observed["clean"]
                and all(observed[key] == 0 for key in ("connections", "pendingRequests", "runningRequests",
                    "workers", "cleanupJobs", "failedCleanup", "sessions", "handles", "calls", "results",
                    "ioCalls", "ioRetainedBytes")), "server-lifecycle-provider-physical-retirement-unconfirmed")
        return observed

    def __call__(self, *, client, node, record, publication, deployment, build, routes,
                 manifests, mounts, route_client, evidence, check, denied_without_cell,
                 grants, tls_context):
        require(tls_context is not None, "server-lifecycle-real-tls-required")
        original_manifest = copy.deepcopy(server_routes.known(
            route_client.call("deployment", "get", deployment["name"]))["deployment"]["manifest"])
        require(original_manifest["metadata"] == {"name": deployment["name"], "tenant": "examples"}
                and original_manifest["spec"]["release"] == record["componentDigest"]
                and original_manifest["spec"]["publication"] == publication,
                "server-lifecycle-original-deployment-association")
        second = read_json(self.fixture / "release-set.json")["releases"][0]
        require(second["service"] == record["service"]
                and second["componentDigest"] != record["componentDigest"],
                "server-lifecycle-distinct-ordinary-source-revision-required")
        raw = read_file(self.build / "server-source.json")
        profile = read_file(self.build / "server-profile.json")
        inputs = read_file(self.build / "source-inputs.json", 4 * 1024 * 1024)
        component = read_file(self.build / "component.wasm", 64 * 1024 * 1024)
        declaration = server_source.validate(raw, component_digest=digest(component),
            source_digest=digest(inputs), profile_digest=digest(profile))
        require(declaration["componentDigest"] == second["componentDigest"],
                "server-lifecycle-signed-component-association")
        server_source.profile(profile)
        observed = {"status": "in-progress", "directSyntheticHttpRpcUsed": False,
                    "cases": [], "sourceDeclaration": declaration["identity"]}

        def case(name, value):
            observed["cases"].append({"case": name, **value})
            write_json(evidence / "lifecycle-current.json", observed)

        # Corruption is rejected by the shipped planner before catalog mutation.
        before = routes.read()
        for key in ("componentDigest", "sourceDigest", "profileDigest", "configurationDigest"):
            changed = {**declaration, key: digest(b"controlled-stale-declaration")}
            try:
                server_routes.plan(encode(changed), encode(mounts),
                    server_routes.observed_pin(route_client, "examples", deployment["name"], record["componentDigest"]),
                    source_digest=digest(read_file(build / "source-inputs.json", 4 * 1024 * 1024)),
                    profile_digest=digest(read_file(build / "server-profile.json")))
            except DevError:
                pass
            else:
                raise RuntimeError("server-lifecycle-forged-declaration-accepted")
            require(routes.read() == before, "server-lifecycle-forged-declaration-changed-owner")
            check("GET", "/hey", 200, b"Hey!")
        case("tampered-declarations-retain-real-last-good-ingress", {"fields": 4})

        package = self.fixture / second["name"] / "package"
        result = client.call("release", "publish-package", package,
            "--evidence", self.fixture / second["name"] / "evidence/index.json",
            "--operation-id", "publish-server-revision-two", "--expected-generation", "0", timeout=125)
        second_publication = result["data"]["operation"]["publication"]["id"]
        require(second_publication != publication, "server-lifecycle-distinct-publication-required")
        case("second-real-source-publication", {"publication": second_publication})

        # Grant each current runtime operation explicitly to the two exact
        # publications. Existing provider bindings and original ceilings remain.
        from tools.java_server_node import CONTEXT
        from tools.guest_runtime_profiles import profiles
        second_grants = []
        for name, (capability, _profile, operation, kind) in {**profiles("java"), "context": CONTEXT}.items():
            policy = client.directory / (name + "-lifecycle-policy.json")
            write_json(policy, {"formatVersion": 1, "tenant": "examples", "rules": [{
                "id": "runtime", "effect": "allow", "principals": [{"kind": "trigger", "subject": "server-caller"}],
                "services": [record["service"]], "publications": [publication, second_publication],
                "capability": capability, "operations": [operation], "resources": {"kind": kind},
                "ceiling": {"operations": 4 if name == "context" else 4096, "inputBytes": 0,
                    "outputBytes": 512 if name == "context" else 32768, "wallTimeMillis": 5000}}]})
            client.call("policy", "apply", "--id", name + "-lifecycle-allow", "--file", policy,
                        "--operation-id", "grant-lifecycle-" + name, "--expected-generation", "0")
            second_grants.append({"capability": capability, "policy": name + "-lifecycle-allow"})

        http_grant = self.grant_http(client, node, record["service"], [publication, second_publication])
        second_grants.append(http_grant)
        original = client.directory / "server-lifecycle-original-deployment.json"
        write_json(original, original_manifest)
        current = deploy(client, original, publication, generation=str(deployment["generation"]),
                         grants=second_grants)
        initial_pin = server_routes.observed_pin(route_client, "examples", current["name"], record["componentDigest"])
        initial_routes = server_routes.plan(read_file(build / "server-source.json"), encode(mounts), initial_pin,
            source_digest=digest(read_file(build / "source-inputs.json", 4 * 1024 * 1024)),
            profile_digest=digest(read_file(build / "server-profile.json")))
        with state.lock(routes.root, "server-routes.lock"):
            routes.apply(initial_routes)
        check("GET", "/hey", 200, b"Hey!")
        prior_roots = {row["activationId"] for row in roots(client, record["service"])}
        with GatePeer(min(client.deadline, time.monotonic() + 125), port=self.peer_port) as peer:
            pending = HeldIngress(node.startup_record["httpEndpoint"], tls_context, client.deadline)
            try:
                peer.wait(peer.started)
                activation = one_new_root(client, record["service"], prior_roots)
                before_cutover = status(client, activation, initial_pin)
                require(before_cutover["terminalState"] is None, "server-lifecycle-inflight-not-live")
                changed = deploy(client, self.fixture / second["name"] / "deployment.json", second_publication,
                                 generation=str(current["generation"]), grants=second_grants)
                selected = server_routes.observed_pin(route_client, "examples", changed["name"], second["componentDigest"])
                configuration = {**mounts, "profileDigest": digest(profile)}
                updated = server_routes.plan(raw, encode(configuration), selected,
                    source_digest=digest(inputs), profile_digest=digest(profile))
                with state.lock(routes.root, "server-routes.lock"):
                    routes.apply(updated)
                after_cutover = status(client, activation, initial_pin)
                peer.release.set()
                response = pending.finish()
                require(response == {"status": 200, "body": b"Hey!".hex()},
                        "server-lifecycle-old-inflight-response-changed")
            finally:
                pending.close()
        from tools.java_server_node import observe_idle
        retirement = observe_idle(client, evidence, "lifecycle-inflight-cutover-retired")
        completed = status(client, activation, initial_pin, terminal="completed")
        case("real-inflight-revision-remains-pinned-across-redeployment", {
            "originalPin": initial_pin, "newPin": selected, "before": before_cutover,
            "after": after_cutover, "terminal": completed, "peer": peer.snapshot(), "retirement": retirement})
        check("GET", "/hey", 200, self.second_body)
        case("real-redeployment-pins-new-publication", {"pin": selected})

        names = [row["metadata"]["name"] for row in manifests]
        before = routes.read()
        try:
            with state.lock(routes.root, "server-routes.lock"):
                routes.rollback_current(names)
        except DevError as error:
            require(error.code == "server-route-rollback-publication-not-current",
                    "server-lifecycle-unexpected-rollback-denial")
        else:
            raise RuntimeError("server-lifecycle-implicit-old-publication-rollback")
        require(routes.read() == before, "server-lifecycle-rejected-rollback-mutated-owner")
        check("GET", "/hey", 200, self.second_body)
        case("rollback-requires-explicit-old-publication-redeployment", {})

        # The old signed deployment belongs to the first actual fixture; its
        # location is supplied by the existing run, not invented by this module.
        restored = deploy(client, original, publication, generation=str(changed["generation"]), grants=second_grants)
        with state.lock(routes.root, "server-routes.lock"):
            routes.rollback_current(names)
        check("GET", "/hey", 200, b"Hey!")
        case("authenticated-explicit-rollback-fresh-generation", {
            "pin": server_routes.observed_pin(route_client, "examples", restored["name"], record["componentDigest"])})
        restored_pin = server_routes.observed_pin(route_client, "examples", restored["name"], record["componentDigest"])

        # A distinct explicitly authorized mount belongs to this controlled
        # competing-owner slice, preserving the original observer's mounts.
        competition_mounts = copy.deepcopy(mounts)
        competition_mounts["mounts"] = [{**mounts["mounts"][0], "name": "server-lifecycle-competing",
                                         "host": "competing.server.test"}]
        # This authority was explicitly added before node startup below.
        competing_root = routes.root.parent / "lifecycle-competing-routes"
        competing_root.mkdir(mode=0o700)
        competing_routes = server_routes.Routes(competing_root, route_client, routes.owner)
        competition = server_routes.plan(read_file(build / "server-source.json"), encode(competition_mounts), restored_pin,
            source_digest=digest(read_file(build / "source-inputs.json", 4 * 1024 * 1024)),
            profile_digest=digest(read_file(build / "server-profile.json")))
        with state.lock(competing_root, "server-routes.lock"):
            competing_routes.apply(competition)
        owned = competing_routes.read()
        name = competition[0]["metadata"]["name"]
        path = client.directory / "server-lifecycle-competing-trigger.json"
        write_json(path, competition[0])
        catalog = competing_routes.observe(name)
        receipt = client.call("trigger", "apply", path, "--operation-id", "server-lifecycle-competing-owner",
            "--expected-generation", catalog["trigger"]["generation"],
            "--expected-state-version", catalog["stateVersion"])
        require(receipt["outcomeKnown"] and receipt["category"] == "success",
                "server-lifecycle-competing-publication-not-confirmed")
        competing = competing_routes.observe(name)
        require(competing["trigger"]["generation"] != owned["routes"][name]["generation"],
                "server-lifecycle-competing-generation-not-changed")
        try:
            with state.lock(competing_root, "server-routes.lock"):
                competing_routes.apply(competition)
        except DevError as error:
            require(error.code == "server-route-concurrent-change-no-overwrite",
                    "server-lifecycle-competing-owner-wrong-denial")
        else:
            raise RuntimeError("server-lifecycle-competing-owner-overwritten")
        require(competing_routes.read() == owned and competing_routes.observe(name) == competing,
                "server-lifecycle-competing-owner-denial-mutated-state")
        check("GET", "/hey", 200, b"Hey!", authority="competing.server.test")
        # Explicit cleanup by the actor that changed the contested generation.
        client.call("trigger", "delete", name, "--operation-id", "server-lifecycle-competing-cleanup",
            "--expected-generation", competing["trigger"]["generation"],
            "--expected-state-version", competing["stateVersion"])
        client.call("trigger", "operation", "server-lifecycle-competing-cleanup")
        require(competing_routes.observe(name)["trigger"] is None, "server-lifecycle-competing-cleanup-not-observed")
        for other in competition[1:]:
            with state.lock(competing_root, "server-routes.lock"):
                competing_routes.remove([other["metadata"]["name"]])
        case("competing-publication-denied-without-overwrite", {"operation": receipt,
            "originalOwner": owned, "competingCatalog": competing, "explicitCleanup": True})
        # Retain the contested owner rather than adopt another actor's receipt.
        # Remaining failures use the original non-contested routes.
        try:
            check("GET", "/fresh", 200, b"1")
            check("GET", "/fresh", 200, b"1")
            case("ordinary-static-state-is-fresh-per-invocation", {})
            before = {row["activationId"] for row in roots(client, record["service"])}
            with GatePeer(min(client.deadline, time.monotonic() + 125), port=self.peer_port) as peer:
                pending = HeldIngress(node.startup_record["httpEndpoint"], tls_context, client.deadline)
                try:
                    peer.wait(peer.started)
                    activation = one_new_root(client, record["service"], before)
                    status(client, activation, restored_pin)
                    pending.disconnect()
                    peer.wait(peer.closed)
                    try:
                        pending.finish()
                    except (OSError, http.client.HTTPException):
                        pass
                    else:
                        raise RuntimeError("server-lifecycle-disconnected-request-returned-response")
                finally:
                    pending.close()
            retirement = observe_idle(client, evidence, "lifecycle-disconnect-retired")
            canceled = status(client, activation, restored_pin, terminal="cancelled")
            case("actual-client-disconnect-retires-original-http-owner", {
                "terminal": canceled, "peer": peer.snapshot(), "retirement": retirement})
            check("GET", "/hey", 200, b"Hey!")
            before = {row["activationId"] for row in roots(client, record["service"])}
            check("GET", "/fuel", 503)
            activation = one_new_root(client, record["service"], before)
            exhausted = status(client, activation, restored_pin, terminal="resource_exhausted")
            require(exhausted["terminalOutcome"]["kind"] == "platform-failure"
                    and exhausted["terminalOutcome"]["error"]["code"] == "resource-exhausted",
                    "server-lifecycle-fuel-not-real-platform-exhaustion")
            tree = client.call("activation", "tree", activation, "--page-size", 8)["data"]
            require(tree["historyAvailable"] and tree["nextPageToken"] is None and len(tree["nodes"]) == 1
                    and tree["nodes"][0]["diagnostic"]["stage"] == 5
                    and tree["nodes"][0]["diagnostic"]["reason"] == 11,
                    "server-lifecycle-exact-fuel-diagnostic-required")
            case("original-one-billion-fuel-ceiling-with-fresh-reuse", {"terminal": exhausted})
            check("GET", "/hey", 200, b"Hey!")
            # A separately recorded narrower deployment deadline demonstrates
            # the existing root ceiling without changing any original limit.
            shortened = copy.deepcopy(original_manifest)
            shortened["spec"]["resources"]["wallTimeLimitMillis"] = 750
            deadline_source = client.directory / "server-lifecycle-narrow-deadline.json"
            write_json(deadline_source, shortened)
            limited = deploy(client, deadline_source, publication,
                generation=str(restored["generation"]), grants=second_grants)
            limited_pin = server_routes.observed_pin(route_client, "examples", limited["name"], record["componentDigest"])
            limited_routes = server_routes.plan(read_file(build / "server-source.json"), encode(mounts), limited_pin,
                source_digest=digest(read_file(build / "source-inputs.json", 4 * 1024 * 1024)),
                profile_digest=digest(read_file(build / "server-profile.json")))
            with state.lock(routes.root, "server-routes.lock"):
                routes.apply(limited_routes)
            before = {row["activationId"] for row in roots(client, record["service"])}
            with GatePeer(min(client.deadline, time.monotonic() + 125), port=self.peer_port) as peer:
                pending = HeldIngress(node.startup_record["httpEndpoint"], tls_context, client.deadline)
                try:
                    peer.wait(peer.started)
                    try:
                        pending.finish()
                    except (OSError, http.client.HTTPException):
                        pass
                    else:
                        raise RuntimeError("server-lifecycle-deadline-returned-successful-http-response")
                    peer.wait(peer.closed)
                finally:
                    pending.close()
            activation = one_new_root(client, record["service"], before)
            expired = status(client, activation, limited_pin, terminal="deadline_exceeded")
            case("narrower-root-deadline-closes-original-peer", {
                "explicitWallTimeMillis": 750, "originalWallTimeMillis": deployment["budget"]["wallTimeLimitMillis"],
                "terminal": expired, "peer": peer.snapshot(),
                "retirement": observe_idle(client, evidence, "lifecycle-deadline-retired")})
            restored = deploy(client, original, publication, generation=str(limited["generation"]), grants=second_grants)
            restored_pin = server_routes.observed_pin(route_client, "examples", restored["name"], record["componentDigest"])
            restored_routes = server_routes.plan(read_file(build / "server-source.json"), encode(mounts), restored_pin,
                source_digest=digest(read_file(build / "source-inputs.json", 4 * 1024 * 1024)),
                profile_digest=digest(read_file(build / "server-profile.json")))
            with state.lock(routes.root, "server-routes.lock"):
                routes.apply(restored_routes)
            check("GET", "/hey", 200, b"Hey!")
        finally:
            observe_idle(client, evidence, "lifecycle-final-retirement")
        observed["status"] = "passed"
        write_json(evidence / "lifecycle-conformance.json", observed)
        return observed
