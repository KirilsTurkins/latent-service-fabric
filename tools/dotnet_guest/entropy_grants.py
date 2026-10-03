"""Explicit, finite entropy authority for the SDK-owned library experiment."""
from __future__ import annotations

from pathlib import Path
import re

from tools.dotnet_guest.runtime import CLOCK, RANDOM
from tools.phase2_operator_process import require, write_json
from tools.rust_capsule_project import ROOT, snapshot

PROVIDER = "noncrypto-random"
BINDING = PROVIDER + "-installed"
POLICY = PROVIDER + "-allow"
PROFILE = "system-random-v1"


def declare(project: Path) -> None:
    """An experiment edits its authoritative world before capturing/building."""
    path = project / "wit/world.wit"
    world = path.read_text(encoding="utf-8")
    require(world.count("world service {") == 1 and RANDOM not in world,
            "dotnet-entropy-fixture-world")
    path.write_text(world.replace("world service {", "world service {\n    import " + RANDOM + ";"),
                    encoding="utf-8", newline="\n")
    for name, body in snapshot(ROOT / "wit/platform/random").items():
        destination = project / "wit/deps/random" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(body)


def configure(settings: dict, *, service="examples/my-greeting") -> None:
    require(isinstance(service, str) and len(service) <= 256
            and re.fullmatch(r"examples/[a-z][a-z0-9]*(?:-[a-z0-9]+)*", service),
            "dotnet-entropy-fixture-service")
    providers = settings["providers"]
    require("random" not in providers, "dotnet-entropy-fixture-provider-already-present")
    bindings = providers["bindings"]
    require(len(bindings) < 16 and not any(row.get("name") == PROVIDER for row in bindings),
            "dotnet-entropy-fixture-binding-bound")
    providers["random"] = {"identity": {"id": PROVIDER, "tenant": "examples",
        "service": "entropy-host", "epoch": 1}}
    bindings.append({"name": PROVIDER, "tenant": "examples", "consumerService": service,
        "providerService": "entropy-host", "contract": RANDOM, "providerBinding": BINDING})


def grant(client, node, deployment: Path, publication: str, target: dict, result: dict) -> dict:
    from tools.rust_capsule_node import call, deploy
    capabilities = {row["capability"] for row in target["grants"]}
    require(CLOCK in capabilities and RANDOM not in capabilities, "dotnet-entropy-fixture-existing-grants")
    denied = call(client, target, "greeting", "greet", ["Ada"], "noncrypto-entropy-grant-denied")
    response = denied["response"]
    consumption = response["data"]["consumption"]
    require(denied["exitCode"] == 4 and response["category"] == "platform-failure"
            and response["outcomeKnown"] is True and response["error"]["code"] == "permission-denied"
            and int(consumption["cpuFuel"]) == 0 and int(consumption["peakMemoryBytes"]) == 0
            and consumption["effectCount"] == 0, "dotnet-entropy-requires-explicit-grant")
    result["noncryptoEntropyGrantDenied"] = denied
    installed = [row for row in node.startup_record["providers"] if row["id"] == PROVIDER]
    require(len(installed) == 1 and installed[0]["tenant"] == "examples"
            and installed[0]["service"] == "entropy-host" and installed[0]["capability"] == RANDOM
            and installed[0]["profile"] == PROFILE and installed[0]["configurationEpoch"] == "1",
            "dotnet-entropy-provider-installation-identity")
    descriptor = installed[0]
    binding = client.directory / (PROVIDER + "-binding.json")
    write_json(binding, {"formatVersion": 1, "tenant": "examples", "capability": RANDOM,
        "providerProfile": PROFILE, "configurationDigest": descriptor["configurationDigest"],
        "configurationEpoch": 1, "restriction": {"operations": ["bytes"]}})
    client.call("policy", "--kind", "provider-binding", "apply", "--id", BINDING, "--file", binding,
        "--operation-id", "install-" + PROVIDER, "--expected-generation", "0")
    policy = client.directory / (PROVIDER + "-policy.json")
    specification = {"formatVersion": 1, "tenant": "examples", "rules": [{
        "id": "hash-seed", "effect": "allow",
        "principals": [{"kind": "administrator", "subject": "workflow-operator"}],
        "services": [target["service"]], "publications": [publication], "capability": RANDOM,
        "operations": ["bytes"], "resources": {"kind": "random"},
        "ceiling": {"operations": 16, "inputBytes": 8, "outputBytes": 4096, "wallTimeMillis": 5000}}]}
    write_json(policy, specification)
    client.call("policy", "apply", "--id", POLICY, "--file", policy,
        "--operation-id", "grant-" + PROVIDER, "--expected-generation", "0")
    selected = deploy(client, deployment, publication, generation=str(target["generation"]),
        grants=[*target["grants"], {"capability": RANDOM, "policy": POLICY}])
    result["noncryptoEntropyAuthority"] = {"provider": descriptor, "policy": specification,
        "scope": "explicit SDK library fixture only", "secureRandom": "unchanged-denial"}
    return selected
