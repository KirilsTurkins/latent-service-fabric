"""Shared real-node setup for management and SDK provider workflows."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import sys
import time

from tools.phase2_operator_process import Process, read_json, require, write_json
from tools.phase2_operator_scenario import configure_node

TENANT = "tests"
SERVICE = "generic"
MEDIA_TYPE = "application/vnd.latent.wit-values.v1+json"
HTTP_CONTRACT = "tests:http/api@1.0.0"
BLOB_CONTRACT = "tests:local-blobs/api@1.0.0"
PROVIDER_CREDENTIAL = b"LSF-PUBLIC-PROVIDER-WORKFLOW-TEST-ONLY"


def configure_provider_node(directory, fixture, http_port):
    require(1 <= http_port <= 65535, "http-fixture-port")
    original = configure_node(directory, fixture, TENANT)
    value = read_json(original)
    value["budgetProfile"] = {"mode": "phase3", "maximumOutboundRequests": 8,
                              "maximumBlobReadBytes": 65536, "maximumBlobWriteBytes": 65536}
    value["capabilityPolicies"] = {"formatVersion": 1, "maximumControlJobs": 2}
    value["shutdownGraceMillis"] = 5000
    value["audit"].update(records=1024, diskBytes=16777216)
    secrets = directory / "provider-credentials"
    secrets.mkdir(mode=0o700)
    credential = secrets / "authorization"
    with credential.open("xb") as target:
        target.write(PROVIDER_CREDENTIAL)
    credential.chmod(0o600)
    origin = {"scheme": "http", "host": "localhost", "port": http_port}
    value["providers"] = {
        "formatVersion": 1,
        "http": {
            "identity": {"id": "http", "tenant": TENANT, "service": "http-host", "epoch": 1},
            "configuration": {
                "formatVersion": 1,
                "destinations": [{"origin": origin,
                                  "addresses": {"networks": ["127.0.0.0/8"], "specialAddresses": ["127.0.0.1"]},
                                  "resolution": {"kind": "static", "addresses": ["127.0.0.1"]},
                                  "allowedRequestHeaders": [], "redirectDestinations": []}],
                "limits": {"maximumRequestBodyBytes": 4096, "maximumResponseBodyBytes": 4096,
                           "maximumEncodedResponseBytes": 8192, "maximumHeaderBytes": 4096,
                           "maximumHeaders": 16, "maximumRedirects": 0},
                "extraRoots": [], "publicRoots": False,
            },
            "credentialDirectory": "provider-credentials",
            "credentials": [{"reference": "workflow-upstream", "file": "authorization",
                             "destination": 0, "header": "authorization"}],
        },
        "blob": {"identity": {"id": "blob", "tenant": TENANT, "service": "blob-host", "epoch": 1},
                 "namespace": "workflow"},
        "bindings": [{"name": f"{name}-binding", "tenant": TENANT, "consumerService": SERVICE,
                      "providerService": f"{name}-host", "contract": capability,
                      "providerBinding": f"{name}-installed", "route": f"guest-{name}"}
                     for name, capability in (("http", "latent:http/client@0.2.0"), ("blob", "latent:blob/blob@0.2.0"))],
    }
    path = directory / "phase3-node.json"
    write_json(path, value)
    return path


def installed_descriptors(node):
    descriptors = node.startup_record.get("providers")
    require(isinstance(descriptors, list) and len(descriptors) == 2, "installed-provider-count")
    result = {}
    for entry in descriptors:
        require(set(entry) == {"id", "tenant", "service", "capability", "profile",
                               "configurationDigest", "configurationEpoch"}, "installed-provider-fields")
        name = entry["id"]
        require(name in {"http", "blob"} and name not in result and entry["tenant"] == TENANT,
                "installed-provider-scope")
        capability, profile = {
            "http": ("latent:http/client@0.2.0", "bounded-http-v1"),
            "blob": ("latent:blob/blob@0.2.0", "linux-immutable-blobs-v1"),
        }[name]
        require(entry["service"] == f"{name}-host" and entry["capability"] == capability
                and entry["profile"] == profile, "installed-provider-profile")
        require(entry["configurationEpoch"] == "1", "installed-provider-epoch")
        require(isinstance(entry["configurationDigest"], str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", entry["configurationDigest"]),
                "installed-provider-digest")
        result[name] = entry
    return result


def invocation_budget(provider="blob"):
    return {"cpuFuel": 10000000000, "memoryBytes": 16777216, "wallTimeLimitMillis": 5000,
            "childCalls": 0, "outboundRequests": 8, "stateReadBytes": 0, "stateWriteBytes": 0,
            "blobReadBytes": 65536 if provider == "blob" else 0,
            "blobWriteBytes": 65536 if provider == "blob" else 0, "logBytes": 0, "effectCount": 0}


def publish_and_deploy_guests(client, fixture, node, http_port):
    descriptors = installed_descriptors(node)
    summary = read_json(fixture / "fixture.json")
    require(summary["schemaVersion"] == "latent.phase3.provider.fixture.v1"
            and summary["tenant"] == TENANT and summary["mediaType"] == MEDIA_TYPE,
            "provider-fixture-profile")
    records = {entry["name"]: entry for entry in summary["fixtures"]}
    require(set(records) == {"rust-http", "rust-blob", "rust-callee"} and len(summary["fixtures"]) == 3,
            "provider-fixture-guests")
    deployed = {}
    for name in ("http", "blob"):
        source = fixture / f"rust-{name}"
        published = client.call("release", "publish-package", source / "package",
                                "--evidence", source / "evidence/index.json",
                                "--operation-id", f"publish-{name}", "--expected-generation", "0")
        require(published["outcomeKnown"], "provider-publication-uncertain")
        operation = published["data"]["operation"]
        publication = operation["publication"]["id"]
        descriptor = descriptors[name]
        binding_path = client.directory / f"{name}-binding.json"
        write_json(binding_path, {"formatVersion": 1, "tenant": TENANT,
                                  "capability": descriptor["capability"], "providerProfile": descriptor["profile"],
                                  "configurationDigest": descriptor["configurationDigest"], "configurationEpoch": 1,
                                  "restriction": {"operations": []}})
        client.call("policy", "--kind", "provider-binding", "apply", "--id", f"{name}-installed",
                    "--file", binding_path, "--operation-id", f"install-{name}", "--expected-generation", "0")
        resources = ({"kind": "http", "origins": [{"scheme": "http", "host": "localhost", "port": http_port}],
                      "methods": ["GET", "HEAD", "POST"], "paths": ["/allowed"], "pathPrefixes": []}
                     if name == "http" else {"kind": "blob", "namespaces": ["workflow"]})
        operations = ["send"] if name == "http" else ["create", "open", "write", "read", "seal"]
        policy_path = client.directory / f"{name}-policy.json"
        write_json(policy_path, {"formatVersion": 1, "tenant": TENANT, "rules": [{
            "id": "allow", "effect": "allow", "principals": [{"kind": "administrator", "subject": "workflow-operator"}],
            "services": [SERVICE], "publications": [publication], "capability": descriptor["capability"],
            "operations": operations, "resources": resources,
            "ceiling": {"operations": 32, "inputBytes": 65536, "outputBytes": 65536, "wallTimeMillis": 5000}}]})
        policy = client.call("policy", "apply", "--id", f"{name}-allow", "--file", policy_path,
                             "--operation-id", f"grant-{name}", "--expected-generation", "0")["data"]
        deployment = {"apiVersion": "latent.dev/v1alpha1", "kind": "Deployment",
                      "metadata": {"name": f"guest-{name}", "tenant": TENANT},
                      "spec": {"service": SERVICE, "release": records[f"rust-{name}"]["componentDigest"],
                               "publication": publication, "route": {"weight": 10000},
                               "grants": [{"capability": descriptor["capability"], "policy": f"{name}-allow"}],
                               "resources": invocation_budget(name),
                               "availability": {"minimumCachedCopies": 1, "minimumZones": 1},
                               "placement": {"trustClass": "internal", "architectures": ["x86_64"]}}}
        path = client.directory / f"{name}-deployment.json"
        write_json(path, deployment)
        snapshot = client.call("deployment", "get", f"guest-{name}", "--operation-snapshot", codes=(6,))["data"]
        result = client.call("deployment", "apply", path, "--operation-id", f"deploy-{name}",
                             "--expected-generation", "0", "--expected-state-version", snapshot["stateVersion"])
        require(result["outcomeKnown"], "provider-deployment-uncertain")
        deployed[name] = {"publication": publication, "componentDigest": records[f"rust-{name}"]["componentDigest"],
                          "service": SERVICE, "route": f"guest-{name}",
                          "contract": HTTP_CONTRACT if name == "http" else BLOB_CONTRACT,
                          "function": "run", "budget": invocation_budget(name),
                          "policyGeneration": policy["receipt"]["generation"]}
    return deployed


def invoke_guest(client, target, which, text="", handle=0, codes=(0,)):
    serial = client.calls
    path = client.directory / f"invoke-{serial}.json"
    budget = client.directory / f"budget-{serial}.json"
    write_json(path, [which, text, str(handle)])
    write_json(budget, target["budget"])
    result = client.call("--rpc-timeout-ms", "5000", "invoke", "--service", target["service"], "--route", target["route"],
                         "--contract", target["contract"], "--function", target["function"],
                         "--input", path, "--budget", budget, "--budget-profile", "phase3", codes=codes)
    if result.get("category") != "success":
        return result, None
    payload = result["data"]["payload"]
    require(payload["encoding"] == "base64" and payload["mediaType"] == MEDIA_TYPE, "provider-output-format")
    value = json.loads(base64.b64decode(payload["data"], validate=True))
    require(isinstance(value, list) and len(value) == 1 and isinstance(value[0], str)
            and re.fullmatch(r"0|[1-9][0-9]{0,19}", value[0])
            and int(value[0]) <= 18446744073709551615, "provider-output-value")
    return result, int(value[0])


def start_http_fixture(client, directory):
    process = Process([sys.executable, str(Path(__file__).with_name("phase3_http_fixture.py"))],
                      directory, client.environment, client.cancellation, maximum=4096)
    try:
        started = process.line(min(client.deadline, time.monotonic() + 10))
        require(set(started) == {"port"} and type(started["port"]) is int
                and 1 <= started["port"] <= 65535, "http-fixture-startup")
        return process, started["port"]
    except BaseException:
        process.close()
        raise


def stop_http_fixture(process):
    process.stop()
    lines = bytes(process.buffers[0]).splitlines()
    require(len(lines) == 1, "http-fixture-shutdown-record")
    report = json.loads(lines[0])
    require(set(report) == {"requests", "authorized", "unexpected"}
            and all(type(count) is int and 0 <= count <= 32 for count in report.values()),
            "http-fixture-shutdown-bound")
    require(process.closed and process.owner.finished and process.owner.process.returncode == 0,
            "http-fixture-not-reaped")
    return report
