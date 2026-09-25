"""Publish narrowly scoped test policy data through the ordinary operator API."""
from __future__ import annotations

from . import paths, policy_operations, state
from .common import decode, digest, encode, require


def selection(root, descriptor, publication, execution, installed, client, journal):
    by_capability = {entry["capability"]: (name, entry) for name, entry in installed.items()}
    require(set(execution["grants"]) <= by_capability.keys(), "test-capability-profile-unsupported")
    node = decode(paths.read(root / "runtime/config", "node.json"))
    operators = [item for item in node["credentials"] if item["tenant"] == descriptor["tenant"] and item["role"] == "operator"]
    require(len(operators) == 1, "test-requires-exact-scoped-operator")
    from tools.guest_runtime_profiles import RUNTIME
    from . import blob_fixture, http_fixture
    profiles = {**RUNTIME, "http": http_fixture.PROVIDER, "blob": blob_fixture.PROVIDER}
    grants = []
    for capability in sorted(execution["grants"]):
        name, entry = by_capability[capability]
        _capability, profile, operation, kind = profiles[name]
        operations = [operation] if isinstance(operation, str) else list(operation)
        binding = {"formatVersion": 1, "tenant": descriptor["tenant"], "capability": capability,
            "providerProfile": profile, "configurationDigest": entry["configurationDigest"],
            "configurationEpoch": 1, "restriction": {"operations": operations}}
        policy_operations.apply(root, client, journal, "dev-" + name, "provider-binding", binding)
        policy = {"formatVersion": 1, "tenant": descriptor["tenant"], "rules": [{
            "id": "runtime", "effect": "deny" if capability in execution.get("deniedCapabilities", []) else "allow",
            "principals": [{"kind": "administrator", "subject": operators[0]["subject"]}],
            "services": [descriptor["service"]], "publications": [publication], "capability": capability,
            "operations": operations, "resources": {"kind": kind},
            "ceiling": {"operations": 4096, "inputBytes": 8 if kind == "random" else 0,
                        "outputBytes": 32768, "wallTimeMillis": 5000}}]}
        if kind == "http":
            fixture = state.load(root, "test-profile.json")["fixtures"]["http"]
            http_fixture.credential(root, fixture)
            policy["rules"][0].update(resources=http_fixture.resources(fixture),
                ceiling={"operations": 8, "inputBytes": 32768, "outputBytes": 65536, "wallTimeMillis": 5000})
        if kind == "blob":
            fixture = blob_fixture.validate(state.load(root, "test-profile.json")["fixtures"]["blob"])
            policy["rules"][0].update(resources={"kind": "blob", "namespaces": [fixture["namespace"]]},
                ceiling={"operations": 32, "inputBytes": 65536, "outputBytes": 65536, "wallTimeMillis": 5000})
        identity = "dev-runtime-" + digest(encode(policy))[7:39]
        policy_operations.apply(root, client, journal, identity, "policy", policy)
        grants.append({"capability": capability, "policy": identity})
    return grants
