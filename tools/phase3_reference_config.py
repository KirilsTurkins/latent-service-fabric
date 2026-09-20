"""Closed host authority and exact two-build inputs for reference delivery."""
from __future__ import annotations

import copy
import re
import socket

from tools.phase2_operator_process import read_json, require, write_json
from tools.phase3_management_scenario import PROVIDER_CREDENTIAL
from tools.phase3_web_scenario import MIB, TENANT, configure_angular_node
from tools.run_security_profile_workflow import replace_config

HTTP_CAPABILITY = "latent:http/client@0.2.0"
USERS = (("Alice<unsafe>", "LSF-PUBLIC-REFERENCE-ALICE-TEST-ONLY"),
         ("Bob", "LSF-PUBLIC-REFERENCE-BOB-TEST-ONLY"))
ROUTES = ("/", "/about", "/account", "/failure", "/data", "/denied", "/slow", "/offline")


def fixtures(root):
    metadata = read_json(root / "fixture.json")
    require(metadata.get("schemaVersion") == "latent.angular.reference.fixture.v1"
            and metadata.get("tenant") == TENANT and metadata.get("actualAngularBuilds") is True
            and metadata.get("reproducibility") == "not-checked"
            and metadata.get("dependencyCompleteness") == "declared-inputs-incomplete", "reference-fixture-profile")
    records = {record["name"]: record for record in metadata["fixtures"]}
    require(len(metadata["fixtures"]) == 2 and set(records) == {"green", "blue"}, "reference-fixture-count")
    for name, record in records.items():
        require(record["service"] == "angular-reference" and record["version"] == "reference-" + name,
                "reference-service-version")
        require({route["path"] for route in record["routes"]} == set(ROUTES)
                and len(record["routes"]) == len(ROUTES), "reference-routes")
        for field in ("packageDigest", "componentDigest", "assetsDigest", "manifestDigest", "sourceSnapshotDigest", "buildObservationDigest"):
            require(re.fullmatch(r"sha256:[0-9a-f]{64}", record[field]) is not None, "reference-fixture-digest")
    for field in ("packageDigest", "componentDigest", "assetsDigest", "sourceSnapshotDigest"):
        require(records["green"][field] != records["blue"][field], "reference-wrapper-only-builds")
    return metadata, records


def configure(client, directory, fixture, compiler):
    path, value = configure_angular_node(client, directory, fixture, compiler)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    host = f"reference.test:{port}"
    foreign = f"foreign.test:{port}"
    value["credentials"] += [{"token": token, "subject": subject, "tenant": TENANT, "role": "invoke"}
                             for subject, token in USERS]
    value["budgetProfile"] = {"mode": "phase3", "maximumOutboundRequests": 1,
                              "maximumBlobReadBytes": 0, "maximumBlobWriteBytes": 0}
    value["capabilityPolicies"] = {"formatVersion": 1, "maximumControlJobs": 2}
    value["httpIngress"].update(bind=f"127.0.0.1:{port}", authentication={"mode": "public-origins", "origins": [
        {"authority": host, "subject": "reference-public", "tenant": TENANT},
        {"authority": foreign, "subject": "foreign-public", "tenant": "foreign"}]})
    value["httpIngress"]["limits"].update(maximumRequestsPerConnection=32, maximumConnectionAgeMillis=120000)
    secrets = directory / "provider-credentials"
    secrets.mkdir(mode=0o700)
    credential = secrets / "authorization"
    with credential.open("xb") as output:
        output.write(PROVIDER_CREDENTIAL)
    credential.chmod(0o600)
    value["providers"] = {"formatVersion": 1, "http": {
        "identity": {"id": "http", "tenant": TENANT, "service": "reference-http-host", "epoch": 1},
        "configuration": {"formatVersion": 1, "destinations": [{
            "origin": {"scheme": "http", "host": "127.0.0.1", "port": 19090},
            "addresses": {"networks": ["127.0.0.0/8"], "specialAddresses": ["127.0.0.1"]},
            "resolution": {"kind": "static", "addresses": ["127.0.0.1"]},
            "allowedRequestHeaders": [], "redirectDestinations": []}],
            "limits": {"maximumRequestBodyBytes": 4096, "maximumResponseBodyBytes": 4096,
                       "maximumEncodedResponseBytes": 8192, "maximumHeaderBytes": 4096,
                       "maximumHeaders": 16, "maximumRedirects": 0}, "extraRoots": [], "publicRoots": False},
        "credentialDirectory": "provider-credentials", "credentials": [{"reference": "reference-upstream",
            "file": "authorization", "destination": 0, "header": "authorization"}]},
        "bindings": [{"name": "reference-http-" + name, "tenant": TENANT, "consumerService": "angular-reference",
                      "providerService": "reference-http-host", "contract": HTTP_CAPABILITY,
                      "providerBinding": "reference-http-installed", "route": name} for name in ("green", "blue")]}
    replace_config(path, value)
    return path, value, host, foreign


def authenticate_config(configured, host):
    value = copy.deepcopy(configured)
    value["httpIngress"]["authentication"] = {"mode": "bearer"}
    value["httpIngress"]["browserOrigins"] = [{"authority": host, "tenant": TENANT}]
    return value


def configure_grant(client, node, publications):
    installed = node.startup_record.get("providers")
    require(isinstance(installed, list) and len(installed) == 1, "reference-installed-provider-count")
    provider = installed[0]
    require(provider["id"] == "http" and provider["tenant"] == TENANT
            and provider["service"] == "reference-http-host" and provider["capability"] == HTTP_CAPABILITY
            and provider["profile"] == "bounded-http-v1" and provider["configurationEpoch"] == "1",
            "reference-installed-provider-identity")
    binding = client.directory / "reference-binding.json"
    write_json(binding, {"formatVersion": 1, "tenant": TENANT, "capability": HTTP_CAPABILITY,
                         "providerProfile": provider["profile"], "configurationDigest": provider["configurationDigest"],
                         "configurationEpoch": 1, "restriction": {"operations": []}})
    result = client.call("policy", "--kind", "provider-binding", "apply", "--id", "reference-http-installed",
                         "--file", binding, "--operation-id", "install-reference-http", "--expected-generation", "0")
    require(result["outcomeKnown"], "reference-provider-binding-uncertain")
    policy = client.directory / "reference-policy.json"
    principals = [{"kind": "administrator", "subject": "workflow-operator"},
                  {"kind": "trigger", "subject": "reference-public"}]
    # Account rendering only reads authenticated invocation context. Give the
    # backend HTTP capability to the operator and public trigger that exercise it;
    # display subjects (including escaping probes) are not policy identifiers.
    write_json(policy, {"formatVersion": 1, "tenant": TENANT, "rules": [{
        "id": "reference-get", "effect": "allow", "principals": principals,
        "services": ["angular-reference"], "publications": list(publications.values()),
        "capability": HTTP_CAPABILITY, "operations": ["send"], "resources": {"kind": "http",
            "origins": [{"scheme": "http", "host": "127.0.0.1", "port": 19090}],
            "methods": ["GET"], "paths": ["/message", "/slow"], "pathPrefixes": []},
        "ceiling": {"operations": 1, "inputBytes": 16384, "outputBytes": 16384, "wallTimeMillis": 5000}}]})
    result = client.call("policy", "apply", "--id", "reference-http", "--file", policy,
                         "--operation-id", "grant-reference-http", "--expected-generation", "0")
    require(result["outcomeKnown"], "reference-grant-uncertain")
    return {"provider": provider, "grant": result["data"]}
