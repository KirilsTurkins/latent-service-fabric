"""Same-node positive tenant isolation through ordinary TLS ingress and CLI."""
from pathlib import Path
import json

from tools import server_routes, server_source
from tools.dev_workflow import state
from tools.dev_workflow.common import digest, require
from tools.java_server_lifecycle import execution_pin, one_new_root, roots, status
from tools.java_server_node import CONTEXT, RecordedRouteClient, grant_runtime, observe_idle
from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import read_json, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_node import RecordingClient, deploy
from tools.rust_capsule_project import read_file

FOREIGN_TOKEN = "LSF-PUBLIC-JAVA-SERVER-FOREIGN-TEST-ONLY"


def select_foreign_deployment(source):
    require(source["metadata"].get("tenant") == "examples", "tenant-isolation-original-deployment-scope")
    selected = json.loads(json.dumps(source))
    # Deployment IDs share one catalog. A second tenant creates its own
    # operator object instead of attempting to replace the examples object.
    selected["metadata"].update(tenant="foreign", name=source["metadata"]["name"] + "-foreign")
    return selected


def require_runtime_grant_denial(observed, before, after):
    outcome = observed.get("terminalOutcome")
    require(isinstance(outcome, dict), "tenant-isolation-missing-grants-must-reject")
    failure = outcome.get("error")
    require(isinstance(failure, dict) and observed.get("terminalState") == "rejected"
            and outcome.get("kind") == "platform-failure"
            and failure.get("code") == "permission-denied"
            and failure.get("retryable") is False,
            "tenant-isolation-missing-grants-must-reject")
    consumption = observed.get("finalConsumption")
    fields = ("cpuFuel", "peakMemoryBytes", "childCalls", "outboundRequests", "effectCount",
              "stateReadBytes", "stateWriteBytes", "blobReadBytes", "blobWriteBytes", "logBytes")
    require(isinstance(consumption, dict) and all(
        type(consumption.get(key)) is int and consumption[key] == 0
        or type(consumption.get(key)) is str and consumption[key] == "0" for key in fields),
        "tenant-isolation-missing-grants-entered-guest")
    counters = []
    for observation in (before, after):
        selected = {}
        for row in observation["cells"]:
            require(row["class"] not in selected, "tenant-isolation-duplicate-cell-class")
            selected[row["class"]] = server_routes.counter(row["granted"])
        counters.append(selected)
    require(counters[0].keys() == counters[1].keys() and bool(counters[0]),
            "tenant-isolation-denial-cell-classes-changed")
    deltas = {name: counters[1][name] - value for name, value in counters[0].items()}
    require(all(value >= 0 for value in deltas.values()) and sum(deltas.values()) <= 1,
            "tenant-isolation-denial-extra-cell-leases")
    return deltas


def runtime_grant_denial(foreign, client, service, pin, evidence, check):
    prior = {row["activationId"] for row in roots(foreign, service)}
    expected = execution_pin(foreign, pin)
    before = observe_idle(client, evidence, "before-foreign-runtime-grant-denial")
    check("GET", "/hey", 403, authority="foreign.server.test")
    after = observe_idle(client, evidence, "after-foreign-runtime-grant-denial")
    activation = one_new_root(foreign, service, prior)
    observed = status(foreign, activation, expected, terminal="rejected")
    deltas = require_runtime_grant_denial(observed, before, after)
    return {"case": "foreign-needs-independent-grants", "status": "denied-before-guest",
            "activationId": activation, "expectedPin": expected, "retained": observed,
            "cellLeaseDelta": deltas, "retirement": after}


class TenantControls:
    def __init__(self, fixture: Path):
        self.fixture = fixture

    def inputs(self):
        return {"workflow": file_identity(Path(__file__)),
            "signing": file_identity(self.fixture / "release-set.json"),
            "policy": file_identity(self.fixture / "policy.json")}

    def configure(self, settings, service):
        aliases = settings["providers"].setdefault("scalarAliases", [])
        for name, (contract, _profile, _operation, _kind) in {**profiles("java"), "context": CONTEXT}.items():
            aliases.append({"source": name, "identity": {"id": name + "-foreign",
                "tenant": "foreign", "service": "foreign-runtime", "epoch": 1}})
            settings["providers"]["bindings"].append({"name": name + "-server", "tenant": "foreign",
                "consumerService": service, "providerService": "foreign-runtime", "contract": contract,
                "providerBinding": name + "-installed"})

    def configure_ingress(self, settings):
        require(settings["cells"][0]["capacity"] == 1, "tenant-isolation-original-shared-cell")

    def grant_initial_http(self, *_args):
        return None

    def stopped(self, record):
        require(record["clean"] is True and record["report"]["clean"] is True,
                "tenant-isolation-physical-shutdown")
        return {"clean": True, "observation": "actual-shared-node-stopped-record"}

    def __call__(self, *, client, node, record, publication, deployment, build, routes, manifests,
                 mounts, route_client, evidence, check, denied_without_cell, grants, tls_context):
        require(tls_context is not None, "tenant-isolation-verified-tls-required")
        signed = read_json(self.fixture / "release-set.json")
        require(signed.get("tenant") is None and signed.get("tenants") == ["examples", "foreign"]
                and signed.get("trust") == "isolated-neutral-server-two-tenant-test-only",
                "tenant-isolation-explicit-signing-scope")
        foreign_directory = client.directory / "foreign"
        foreign_directory.mkdir(mode=0o700)
        foreign = RecordingClient(Path(client.executable), foreign_directory, client.cancellation, client.deadline,
            evidence=evidence / "foreign-control", control_timeout_millis=125000)
        foreign.config = foreign_directory / "client.json"
        write_json(foreign.config, {"formatVersion": 1, "defaultProfile": "operator", "profiles": [{
            "name": "operator", "endpoint": "http://" + node.startup_record["endpoint"], "tenant": "foreign",
            "token": FOREIGN_TOKEN, "connectTimeoutMillis": 2000, "rpcTimeoutMillis": 15000}]})
        foreign.node = node
        configuration = read_file(foreign.config)
        own_manifests = [row for row in manifests if row["spec"]["configuration"]["host"] == "java.server.test"]
        removed = [row["metadata"]["name"] for row in manifests if row not in own_manifests]
        with state.lock(routes.root, "server-routes.lock"):
            routes.remove(removed)
        manifests[:] = own_manifests
        package = self.fixture / record["name"]
        published = foreign.call("release", "publish-package", package / "package",
            "--evidence", package / "evidence/index.json", "--operation-id", "publish-server",
            "--expected-generation", "0", timeout=125)
        foreign_publication = published["data"]["operation"]["publication"]["id"]
        require(foreign_publication != publication, "tenant-isolation-publication-scopes-must-differ")
        foreign_source = select_foreign_deployment(read_json(package / "deployment.json"))
        foreign_manifest = foreign_directory / "deployment.json"
        write_json(foreign_manifest, foreign_source)
        foreign_deployment = deploy(foreign, foreign_manifest, foreign_publication)
        foreign_cli = RecordedRouteClient(Path(client.executable), foreign.config, foreign_directory,
            evidence=evidence / "foreign-routes", deadline=client.deadline)
        foreign_pin = server_routes.observed_pin(foreign_cli, "foreign", foreign_deployment["name"], record["componentDigest"])
        declaration, source, profile = (read_file(build / name) for name in
            ("server-source.json", "source-inputs.json", "server-profile.json"))
        foreign_mounts = {**mounts, "mounts": [{**mounts["mounts"][0], "host": "foreign.server.test"}]}
        foreign_triggers = server_routes.plan(declaration, json.dumps(foreign_mounts, separators=(",", ":")).encode(),
            foreign_pin, source_digest=digest(source), profile_digest=digest(profile))
        route_directory = foreign_directory / "routes"
        route_directory.mkdir(mode=0o700)
        foreign_routes = server_routes.Routes(route_directory, foreign_cli, {"tenant": "foreign",
            "route": foreign_deployment["name"], "clientConfigDigest": digest(configuration)})
        observations = {"status": "in-progress", "sameComponentDigest": record["componentDigest"],
            "publications": {"examples": publication, "foreign": foreign_publication}, "cases": []}
        try:
            with state.lock(route_directory, "server-routes.lock"):
                foreign_routes.apply(foreign_triggers)
            # Examples grants and the same physical scalar registrations do not
            # authorize an admitted foreign publication or its trigger principal.
            observations["cases"].append(runtime_grant_denial(
                foreign, client, record["service"], foreign_pin, evidence, check))
            foreign_grants = grant_runtime(foreign, node, record, foreign_publication,
                tenant="foreign", principal="foreign-caller", suffix="-foreign")
            foreign_deployment = deploy(foreign, foreign_manifest, foreign_publication,
                generation=str(foreign_deployment["generation"]), grants=foreign_grants)
            foreign_pin = server_routes.observed_pin(foreign_cli, "foreign", foreign_deployment["name"], record["componentDigest"])
            foreign_triggers = server_routes.plan(declaration, json.dumps(foreign_mounts, separators=(",", ":")).encode(),
                foreign_pin, source_digest=digest(source), profile_digest=digest(profile))
            with state.lock(route_directory, "server-routes.lock"):
                foreign_routes.apply(foreign_triggers)
            own_pin = server_routes.observed_pin(route_client, "examples", deployment["name"], record["componentDigest"])
            actual_roots = {}
            for ordinal, (tenant, selected_client, selected_cli, pin, authority) in enumerate([
                ("examples", client, route_client, own_pin, "java.server.test"),
                ("foreign", foreign, foreign_cli, foreign_pin, "foreign.server.test"),
            ] * 3):
                marker = tenant + "-" + str(ordinal)
                payload = bytes((ordinal, 0, 128, 255))
                prior = {row["activationId"] for row in roots(selected_client, record["service"])}
                expected = execution_pin(selected_client, pin)
                check("POST", "/isolation", 200, (marker + "|fresh=1|").encode() + payload,
                    authority=authority, body=payload, headers={"Origin": "https://" + authority,
                        "X-Isolation-Marker": marker, "Content-Type": "application/octet-stream"})
                activation = one_new_root(selected_client, record["service"], prior)
                observed = status(selected_client, activation, expected, terminal="completed")
                require(observed["finalConsumption"] is not None, "tenant-isolation-original-consumption")
                actual_roots[tenant] = activation
                observations["cases"].append({"case": "fresh-state-and-request-objects", "tenant": tenant,
                    "activationId": activation, "expectedPin": expected, "retained": observed})
            for selected_client, activation in ((client, actual_roots["foreign"]), (foreign, actual_roots["examples"])):
                denied = selected_client.call("activation", "get", activation, codes=(4, 6))
                require(denied["outcomeKnown"] is True and "metadata" not in denied["data"],
                        "tenant-isolation-foreign-activation-visible")
            spoof = read_json(foreign.config)
            spoof["profiles"][0]["token"] = "LSF-PUBLIC-OPERATOR-WORKFLOW-TEST-ONLY"
            spoof_path = foreign_directory / "wrong-tenant-credential.json"
            write_json(spoof_path, spoof)
            original_config = foreign.config
            try:
                foreign.config = spoof_path
                denied = foreign.call("deployment", "get", foreign_deployment["name"], codes=(4,))
                require(denied["outcomeKnown"] is True and denied["error"]["code"] == "permission-denied",
                        "tenant-isolation-operator-token-crossed-tenant")
            finally:
                foreign.config = original_config
            observations["cases"].append({"case": "operator-token-cannot-select-other-tenant", "status": "denied"})
            denied_without_cell("GET", "/hey", 401, authority="foreign.server.test",
                headers={"Authorization": "Bearer LSF-PUBLIC-OPERATOR-WORKFLOW-TEST-ONLY"})
            observations["cases"].append({"case": "operator-credential-not-handler-authority", "status": "denied-before-cell"})
            require(read_file(foreign.config) == configuration, "tenant-isolation-client-configuration-changed")
            observations["idle"] = observe_idle(client, evidence, "tenant-isolation-idle")
            observations["status"] = "passed"
            return observations
        finally:
            try:
                with state.lock(route_directory, "server-routes.lock"):
                    owned = foreign_routes.read()
                    require(owned["pending"] is None, "tenant-isolation-uncertain-route-requires-recovery")
                    if owned["routes"]:
                        foreign_routes.remove(list(owned["routes"]))
            except BaseException as cleanup:
                observations["cleanupFailure"] = type(cleanup).__name__
                if observations["status"] == "passed":
                    observations["status"] = "failed"
                    raise
            finally:
                foreign.node = None
                write_json(evidence / "tenant-isolation.json", observations)
