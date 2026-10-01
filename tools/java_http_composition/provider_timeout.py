"""Finite actual HTTP -> Java child -> managed HTTP provider timeout campaign.

The hosted conductor owns compiler/package/native identities and installs these
explicit fixture changes before its fresh build and deployment. This helper does
not execute compilers, start another node, retry a send or infer external outcome.
"""
from __future__ import annotations

import copy
import http.client
import json
import math
from pathlib import Path
import re
import time

from tools.java_http_composition.context import hops, roots, tree
from tools.java_http_composition.node import ADAPTER, CHILD_SUBJECT, DOMAIN, MEDIA, TENANT, idle
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase3_management_scenario import http_provider
from tools.rust_capsule_project import ROOT, digest, read_file
from tools.static_api.node import policy

PREFIX = "provider-fixture:"
TIMEOUT_MILLIS = 250
MODE = "hold-java-provider-timeout"
CAPABILITY = "latent:http/client@0.2.0"
BINDING = "java-domain-http-timeout"
POLICY = "java-domain-http-timeout-allow"


def adapt_domain(project: Path) -> dict:
    """Adapt only a fresh observed domain project, preserving all its exports."""
    source_path, wit_path = project / "src/dev/latent/app/Capsule.java", project / "wit/world.wit"
    source, wit = read_file(source_path, 32768).decode(), read_file(wit_path, 32768).decode()
    original = "public String text(String value) { return value; }"
    require(source.count(original) == 1 and wit.count("world service {") == 1
            and CAPABILITY not in wit, "java-provider-domain-adaptation-shape")
    template = read_file(ROOT / "sdk/java-guest/templates/http-status.java", 32768).decode()
    method = re.search(r"    public Result<Integer, Bindings\.LatentHttpClientHttpError> check\(String url\) \{.*?\n    \}",
                       template, re.S)
    require(method is not None, "java-provider-maintained-template-shape")
    helper = method[0].replace("public Result", "private Result", 1).replace(" check(", " providerCheck(", 1)
    options = "Option.none(), Option.none(), Option.none(), Option.none());"
    require(helper.count(options) == 1, "java-provider-maintained-template-options")
    helper = helper.replace(options, "Option.none(), Option.none(), Option.none(), "
                           f"Option.some(new Unsigned64({TIMEOUT_MILLIS})));", 1)
    replacement = '''public String text(String value) {
        if (!value.startsWith("provider-fixture:")) return value;
        var result = providerCheck(value.substring(17));
        return result.isError() ? "provider-error" : Integer.toString(result.value());
    }'''
    source = source.replace(original, replacement, 1)
    require(source.rstrip().endswith("}"), "java-provider-domain-class-shape")
    if "import dev.latent.guest.Option;" not in source:
        source = source.replace("import dev.latent.guest.Result;", "import dev.latent.guest.Result;\nimport dev.latent.guest.Option;", 1)
    source = source.rstrip()[:-1] + helper + "\n}\n"
    wit = wit.replace("world service {", "world service {\n    import " + CAPABILITY + ";", 1)
    descriptor, lock = read_json(project / "capsule-project.json"), read_json(project / "sdk-lock.json")
    descriptor["limits"]["outboundRequests"] = 1
    lock["template"] = {"name": "java-provider-timeout-v1", "sourceDigest": digest(source.encode()),
                        "witDigest": digest(wit.encode())}
    source_path.write_text(source, encoding="utf-8", newline="\n")
    wit_path.write_text(wit, encoding="utf-8", newline="\n")
    for name, document in (("capsule-project.json", descriptor), ("sdk-lock.json", lock)):
        (project / name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"sourceDigest": lock["template"]["sourceDigest"], "witDigest": lock["template"]["witDigest"],
            "templateDigest": digest(template.encode()), "recipeDigest": digest(read_file(Path(__file__))),
            "providerTimeoutMillis": TIMEOUT_MILLIS, "domainOutboundRequests": 1}


def adapt_adapter(project: Path) -> dict:
    """Explicit fixture budget edit after generator checks, before build capture."""
    path = project / "capsule-project.json"
    descriptor = read_json(path)
    require(descriptor["service"] == ADAPTER and descriptor["limits"]["outboundRequests"] == 0,
            "java-provider-adapter-original-budget")
    # The actual common child broker halves the parent's remaining allowance.
    descriptor["limits"]["outboundRequests"] = 2
    path.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"descriptorDigest": digest(read_file(path)), "adapterOutboundRequests": 2,
            "sourceDigest": digest(read_file(project / "src/dev/latent/app/Capsule.java"))}


def configure(directory: Path, settings: dict, port: int) -> dict:
    """Add the existing common provider installation before actual node startup."""
    require(settings.get("budgetProfile", {}).get("mode") == "phase3"
            and settings.get("providers", {}).get("formatVersion") == 1,
            "java-provider-original-node-profile")
    result = copy.deepcopy(settings)
    providers = result["providers"]
    require(not providers.get("http"), "java-provider-existing-http-owner")
    maximum = result["budgetProfile"].get("maximumOutboundRequests", 0)
    require(type(maximum) is int and 0 <= maximum <= 8, "java-provider-original-outbound-bound")
    result["budgetProfile"]["maximumOutboundRequests"] = max(maximum, 2)
    bindings = providers["bindings"]
    require(len(bindings) < 16 and all(row["name"] != BINDING for row in bindings),
            "java-provider-binding-bound")
    providers["http"] = http_provider(directory, TENANT, port)
    bindings.append({"name": BINDING, "tenant": TENANT, "consumerService": DOMAIN,
        "providerService": "http-host", "contract": CAPABILITY, "providerBinding": BINDING})
    return result


def grant(client, node, domain_publication: str, port: int) -> dict:
    """Use actual installed identity and original source-service/caller policy."""
    require(type(port) is int and 1 <= port <= 65535
            and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", domain_publication),
            "java-provider-selected-publication")
    installed = [row for row in node.startup_record["providers"] if row["id"] == "http"]
    require(len(installed) == 1, "java-provider-original-installed-owner")
    actual = installed[0]
    require(actual["tenant"] == TENANT and actual["service"] == "http-host"
            and actual["capability"] == CAPABILITY and actual["profile"] == "bounded-http-v1"
            and actual["configurationEpoch"] == "1"
            and re.fullmatch(r"sha256:[0-9a-f]{64}", actual["configurationDigest"]),
            "java-provider-installed-profile")
    policy(client, "provider-binding", BINDING, {"formatVersion": 1, "tenant": TENANT,
        "capability": CAPABILITY, "providerProfile": actual["profile"],
        "configurationDigest": actual["configurationDigest"], "configurationEpoch": 1,
        "restriction": {"operations": ["send"]}})
    policy(client, "policy", POLICY, {"formatVersion": 1, "tenant": TENANT, "rules": [{
        "id": "selected-domain", "effect": "allow", "principals": [
            {"kind": "administrator", "subject": "workflow-operator"},
            {"kind": "service", "subject": CHILD_SUBJECT}],
        "services": [DOMAIN], "publications": [domain_publication], "capability": CAPABILITY,
        "operations": ["send"], "resources": {"kind": "http",
            "origins": [{"scheme": "http", "host": "localhost", "port": port}],
            "methods": ["GET"], "paths": ["/allowed"], "pathPrefixes": []},
        "ceiling": {"operations": 1, "inputBytes": 4096, "outputBytes": 8192, "wallTimeMillis": 1000}}]})
    return {"capability": CAPABILITY, "policy": POLICY}


def _remaining(client, maximum: float) -> float:
    client.cancellation.check()
    remaining = client.deadline - time.monotonic()
    require(math.isfinite(remaining) and remaining > 0, "java-provider-original-deadline")
    return min(remaining, maximum)


def _marker(client, control: Path, name: str) -> None:
    path = control / name
    deadline = min(client.deadline, time.monotonic() + 3)
    for _ in range(256):
        _remaining(client, 3)
        if path.exists():
            require(read_file(path, 9) == b"observed\n", "java-provider-original-peer-marker")
            return
        require(time.monotonic() < deadline, "java-provider-peer-marker-deadline")
        time.sleep(.01)
    raise RuntimeError("java-provider-peer-marker-observation-bound")


def _observe(client, host: str, port: int) -> tuple[dict, object]:
    before = {row["activationId"] for row in roots(client)}
    connection = http.client.HTTPConnection("127.0.0.1", int(host.rsplit(":", 1)[1]),
                                            timeout=_remaining(client, 125))
    try:
        body = json.dumps([PREFIX + f"http://localhost:{port}/allowed"]).encode()
        connection.request("POST", "/api/text", body=body, headers={"Host": host, "Connection": "close",
            "Origin": "http://" + host, "Content-Type": MEDIA})
        connection.sock.settimeout(_remaining(client, 125))
        response = connection.getresponse()
        raw = response.read(32769)
        require(response.status == 200 and len(raw) <= 32768, "java-provider-composed-response")
        value = json.loads(raw)
    finally:
        connection.close()
    _remaining(client, 125)
    discovered = [row for row in roots(client) if row["activationId"] not in before]
    require(len(discovered) == 1, "java-provider-supported-one-root")
    observation = {"httpStatus": response.status, "tree": tree(client, discovered[0]["activationId"])}
    hops(observation)
    return observation, value


def timeout_observation(child: dict) -> str:
    """Absent typed observation stays unavailable; strings cannot classify it."""
    diagnostic = child.get("diagnostic")
    if diagnostic is None:
        return "unavailable"
    if (type(diagnostic.get("stage")) is int and diagnostic["stage"] == 6
            and type(diagnostic.get("reason")) is int and diagnostic["reason"] == 13
            and child.get("diagnosticIsTerminal") is False):
        return "observed"
    return "unexpected"


def qualify(client, host: str, control: Path, port: int) -> dict:
    """Two distinct real requests; the timed-out send is never retried."""
    require(type(port) is int and 1 <= port <= 65535, "java-provider-peer-port")
    require(all(not (control / name).exists() for name in ("mode", "get-" + MODE, "started-" + MODE, "closed-" + MODE)),
            "java-provider-fresh-rendezvous")
    mode = control / "mode"
    with mode.open("xb") as output:
        output.write(MODE.encode())
    mode.chmod(0o600)
    result = {"schemaVersion": "latent.java-provider-timeout.v1", "status": "running",
              "externalMutationDisposition": "unknown", "providerPoolCountersBeforeShutdown": None}
    try:
        failed, value = _observe(client, host, port)
        result["timeout"] = failed
        write_json(client.evidence / "java-provider-timeout-original.json", result)
        require(value == ["provider-error"], "java-provider-original-handled-error")
        for name in ("get-" + MODE, "started-" + MODE, "closed-" + MODE):
            _marker(client, control, name)
        _, child = hops(failed)
        result["typedDiagnostic"] = timeout_observation(child)
        result["peerReceivedGet"] = result["peerSocketPhysicallyClosed"] = True
        result["afterTimeout"] = idle(client)
        mode.unlink()
        fresh, value = _observe(client, host, port)
        result["fresh"] = fresh
        require(value == ["201"], "java-provider-distinct-fresh-success")
        result["afterFresh"] = idle(client)
        result["status"] = "passed" if result["typedDiagnostic"] == "observed" else "typed-diagnostic-" + result["typedDiagnostic"]
        write_json(client.evidence / "java-provider-timeout-campaign.json", result)
        return result
    finally:
        # Remove only this helper's original mode, never a peer's changed input.
        if mode.is_file() and not mode.is_symlink() and mode.read_bytes() == MODE.encode():
            mode.unlink()


def verify_shutdown(shutdown: dict) -> dict:
    """Only the original reaped node report proves all common pool counters zero."""
    require(shutdown.get("reaped") is True and shutdown["record"].get("clean") is True,
            "java-provider-node-not-reaped")
    report = shutdown["record"]["report"]["providers"]
    counters = ("controlOwners", "connections", "pendingRequests", "runningRequests", "workers", "cleanupJobs",
        "failedCleanup", "sessions", "handles", "calls", "results", "ioCalls", "ioRetainedBytes")
    require(report.get("clean") is True and all(type(report.get(name)) is int and report[name] == 0 for name in counters),
            "java-provider-physical-pool-not-retired")
    return {"reaped": True, "clean": True, "counters": {name: report[name] for name in counters}}


def stop_peer(process) -> dict:
    """Reap the original peer, retaining its one held and one fresh request."""
    process.stop()
    lines = bytes(process.buffers[0]).splitlines()
    require(len(lines) == 1 and len(lines[0]) <= 4096, "java-provider-peer-shutdown-record")
    result = json.loads(lines[0])
    require(set(result) == {"requests", "authorized", "unexpected", "holds", "closedHolds"}
            and all(type(value) is int and 0 <= value <= 32 for value in result.values()),
            "java-provider-peer-shutdown-bound")
    require(result["requests"] == result["authorized"] == 2 and result["unexpected"] == 0
            and result["holds"] == result["closedHolds"] == 1,
            "java-provider-peer-authority-or-physical-close")
    require(process.closed and process.owner.finished and process.owner.process.returncode == 0,
            "java-provider-peer-not-reaped")
    return result
