"""Provision exact native observations through current authenticated policy APIs."""
from __future__ import annotations

from dataclasses import dataclass
import re

from tools.static_api.node import policy

from .configuration import (ALICE, CLOCKS, DISPATCH_POLICY, NAMESPACE, OPERATOR,
                            RESULT_POLICY, SERVICE, STAGING_POLICY, STATE_POLICY, TENANT)
from .inputs import require

STATE_CONTRACT = "latent:state/key-value@0.2.0"
INTENT_CONTRACT = "latent:intents/staging@0.1.0"
DATA_OPERATIONS = ["acquire-command", "acquire-query", "info", "query-info", "get", "get-query",
                   "scan", "scan-query", "describe-page", "page-next", "put", "delete", "commit", "read-result"]
MANAGEMENT_OPERATIONS = ["namespace-create", "namespace-inspect", "namespace-list", "namespace-quiesce",
                         "namespace-retire", "namespace-destroy", "namespace-recreate", "read-result",
                         "inspect-effect", "cancel-command"]
RECOVERY_OPERATIONS = ["namespace-snapshot", "namespace-inspect-restore", "namespace-restore",
                       "namespace-schema-migrate", "namespace-review-recovery", "namespace-resume"]
CALLER_FIELDS = {"subject", "ownerKind", "tenant", "service", "recoveryKind", "recoveryScope"}
PROVIDER_FIELDS = {"id", "tenant", "service", "capability", "profile", "configurationDigest", "configurationEpoch"}
EFFECT_FIELDS = {"tenant", "service", "publication", "namespace", "incarnation", "logicalBinding", "operation",
                 "stagingBinding", "dispatchBinding", "providerProfile", "configurationDigest", "configurationEpoch",
                 "dispatchSubject", "dispatchRecoveryKind", "dispatchRecoveryScope", "resultPolicy"}
INSPECTION_FIELDS = {"schemaVersion", "configuredProviders", "configuredHttpCallers", "configuredTransportCallers",
                     "stateProviderProfile", "stateConfigurationDigest", "stateConfigurationEpoch", "deferredHttp"}


def identifier(value):
    require(isinstance(value, str) and 0 < len(value.encode()) <= 256
            and not any(ord(char) < 32 or ord(char) == 127 for char in value), "bounded-native-identity")
    return value


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value), "native-sha256-observation")
    return value


def epoch(value, *, decimal=False):
    if decimal:
        require(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value), "native-epoch-decimal")
        value = int(value)
    require(type(value) is int and 0 < value <= 2**64 - 1, "native-positive-epoch")
    return value


@dataclass(frozen=True)
class ObservedHosts:
    value: dict
    alice: dict
    operator: dict
    providers: dict
    effects: tuple[dict, ...]

    @classmethod
    def read(cls, value: dict, operations: list[dict]):
        require(isinstance(value, dict) and set(value) == INSPECTION_FIELDS
                and value["schemaVersion"] == "latent.transaction-host-inspection.v1", "actual-native-host-inspection")
        identifier(value["stateProviderProfile"])
        sha(value["stateConfigurationDigest"])
        epoch(value["stateConfigurationEpoch"])
        for name in ("configuredHttpCallers", "configuredTransportCallers"):
            callers = value[name]
            require(isinstance(callers, list) and 0 < len(callers) <= 64, "native-caller-set-bound")
            for caller in callers:
                require(isinstance(caller, dict) and set(caller) == CALLER_FIELDS
                        and caller["ownerKind"] in {"user", "administrator"}
                        and caller["service"] is None and caller["recoveryKind"] == "original-caller",
                        "actual-original-caller-scope")
                for key in ("subject", "tenant", "recoveryScope"):
                    identifier(caller[key])
            require(len({(row["subject"], row["ownerKind"], row["tenant"]) for row in callers}) == len(callers),
                    "unambiguous-native-caller-set")
        alice = _caller(value["configuredHttpCallers"], ALICE, "user")
        operator = _caller(value["configuredTransportCallers"], OPERATOR, "administrator")
        require(alice == _caller(value["configuredTransportCallers"], ALICE, "user"),
                "same-authenticated-http-and-rpc-user-owner")
        rows = value["configuredProviders"]
        require(isinstance(rows, list) and len(rows) == 3, "exact-native-clock-and-http-installations")
        providers = {}
        for row in rows:
            require(isinstance(row, dict) and set(row) == PROVIDER_FIELDS
                    and row["id"] in {*CLOCKS, "http"} and row["tenant"] == TENANT
                    and row["service"] == "runtime-host" and row["id"] not in providers,
                    "exact-native-provider-owner")
            identifier(row["profile"])
            sha(row["configurationDigest"])
            epoch(row["configurationEpoch"], decimal=True)
            expected = CLOCKS[row["id"]][0] if row["id"] in CLOCKS else "latent:http/client@0.2.0"
            require(row["capability"] == expected, "actual-installed-provider-contract")
            providers[row["id"]] = row
        effects = value["deferredHttp"]
        require(isinstance(effects, list) and len(effects) == 3, "exact-three-signed-effect-installations")
        require(all(isinstance(row, dict) and set(row) == EFFECT_FIELDS for row in effects),
                "closed-native-effect-observation")
        selected = {row["publication"]: row for row in operations if "deferredHttp" in row}
        require(len(selected) == len(effects)
                and set(selected) == {row["publication"] for row in effects},
                "same-actual-selected-effect-publications")
        for effect in effects:
            require(isinstance(effect, dict) and set(effect) == EFFECT_FIELDS, "closed-native-effect-observation")
            configured = selected[effect["publication"]]
            deferred = configured["deferredHttp"]
            require(effect["tenant"] == TENANT and effect["service"] == SERVICE
                    and effect["namespace"] == NAMESPACE and effect["incarnation"] == configured["incarnation"]
                    and effect["resultPolicy"] == RESULT_POLICY and effect["logicalBinding"] == "qualified-http"
                    and effect["operation"] == "put-once"
                    and effect["stagingBinding"] == deferred["stagingBinding"]
                    and effect["dispatchBinding"] == deferred["dispatchBinding"]
                    and effect["dispatchRecoveryKind"] == "service-integration", "same-native-effect-scope-and-purpose")
            for key in ("providerProfile", "dispatchSubject", "dispatchRecoveryScope"):
                identifier(effect[key])
            sha(effect["configurationDigest"])
            epoch(effect["configurationEpoch"])
        identities = {(row["providerProfile"], row["configurationDigest"], row["configurationEpoch"])
                      for row in effects}
        require(len(identities) == 1, "single-native-qualified-http-profile")
        return cls(value, alice, operator, providers, tuple(effects))


def _caller(callers, subject, kind):
    rows = [row for row in callers if row["subject"] == subject and row["ownerKind"] == kind and row["tenant"] == TENANT]
    require(len(rows) == 1, "actual-unique-authenticated-caller")
    return rows[0]


def scope(caller, *, kind=None, recovery=None):
    return {"namespace": NAMESPACE, "incarnation": 1, "entity": None,
            "recoveryKind": kind or caller["recoveryKind"],
            "recoveryScope": recovery or caller["recoveryScope"], "resultPolicy": RESULT_POLICY}


def binding(capability, profile, digest, version, operations):
    return {"formatVersion": 1, "tenant": TENANT, "capability": capability,
            "providerProfile": profile, "configurationDigest": sha(digest),
            "configurationEpoch": epoch(version), "restriction": {"operations": operations}}


def rule(name, kind, subject, publications, capability, operations, resources, *, input_bytes=2097152,
         output_bytes=2097152, calls=256, wall=30000):
    return {"id": name, "effect": "allow", "principals": [{"kind": kind, "subject": subject}],
            "services": [SERVICE], "publications": sorted(publications), "capability": capability,
            "operations": operations, "resources": resources,
            "ceiling": {"operations": calls, "inputBytes": input_bytes,
                        "outputBytes": output_bytes, "wallTimeMillis": wall}}


def documents(hosts: ObservedHosts, publications: dict[str, str]) -> dict:
    """Reviewed test policy proposals only; they become authority solely via apply."""
    pubs = sorted(publications.values())
    require(len(pubs) == 4 and len(set(pubs)) == 4
            and all(re.fullmatch(r"publication:sha256:[0-9a-f]{64}", pub) for pub in pubs),
            "actual-four-distinct-admitted-publications")
    result = {"bindings": {}, "policies": {}, "deploymentGrants": []}
    result["bindings"]["transaction-java-aggregate"] = binding(STATE_CONTRACT,
        hosts.value["stateProviderProfile"], hosts.value["stateConfigurationDigest"],
        hosts.value["stateConfigurationEpoch"], [])
    state_rules = []
    for caller, operations in ((hosts.alice, DATA_OPERATIONS + ["inspect-effect", "cancel-command"]),
                               (hosts.operator, MANAGEMENT_OPERATIONS)):
        state_rules.append(rule(caller["ownerKind"], caller["ownerKind"], caller["subject"], pubs,
            STATE_CONTRACT, operations, {"kind": "state", "scopes": [scope(caller)]}))
    # Empty binding restriction preserves explicit, purpose-specific caller
    # rules. The native resolver canary qualifies this inheritance; the binding
    # never grants an operation by itself, and each rule remains within 16.
    state_rules.append(rule("native-recovery", "administrator", hosts.operator["subject"], pubs,
        STATE_CONTRACT, RECOVERY_OPERATIONS, {"kind": "state", "scopes": [scope(hosts.operator)]},
        input_bytes=64 * 1024 * 1024, output_bytes=64 * 1024 * 1024, calls=1, wall=60000))
    result["policies"][STATE_POLICY] = {"formatVersion": 1, "tenant": TENANT, "rules": state_rules}
    for name, (capability, operation) in CLOCKS.items():
        descriptor = hosts.providers[name]
        result["bindings"][name + "-installed"] = binding(capability, descriptor["profile"],
            descriptor["configurationDigest"], epoch(descriptor["configurationEpoch"], decimal=True), [operation])
        result["policies"][name + "-allow"] = {"formatVersion": 1, "tenant": TENANT, "rules": [
            rule("clock", "user", ALICE, pubs, capability, [operation], {"kind": "clock"},
                 input_bytes=0, output_bytes=32768, calls=4096, wall=120000)]}
        result["deploymentGrants"].append({"capability": capability, "policy": name + "-allow"})
    effect = hosts.effects[0]
    for selected, operation in (("java-staging-installed", "stage"), ("java-dispatch-installed", "dispatch")):
        result["bindings"][selected] = binding(INTENT_CONTRACT, effect["providerProfile"],
            effect["configurationDigest"], effect["configurationEpoch"], [operation])
    effect_pubs = sorted(row["publication"] for row in hosts.effects)
    require(set(effect_pubs) <= set(pubs), "native-effect-publication-is-original-admitted-source")
    result["policies"][STAGING_POLICY] = {"formatVersion": 1, "tenant": TENANT, "rules": [
        rule("original-caller", "user", ALICE, effect_pubs, INTENT_CONTRACT, ["stage"],
             {"kind": "state", "scopes": [scope(hosts.alice)]}, input_bytes=65536, output_bytes=65536, calls=1)]}
    result["policies"][DISPATCH_POLICY] = {"formatVersion": 1, "tenant": TENANT, "rules": [
        rule(f"original-source-{index}", "service", row["dispatchSubject"], [row["publication"]],
             INTENT_CONTRACT, ["dispatch"], {"kind": "state", "scopes": [scope(hosts.alice,
                 kind=row["dispatchRecoveryKind"], recovery=row["dispatchRecoveryScope"])]},
             input_bytes=27, output_bytes=2048, calls=1, wall=2000)
        for index, row in enumerate(hosts.effects)]}
    return result


def apply(client, proposals: dict) -> dict:
    receipts = {}
    for family, kind in (("bindings", "provider-binding"), ("policies", "policy")):
        for name, document in proposals[family].items():
            receipts[name] = policy(client, kind, name, document)
    return receipts


def prepare_mutations(client, proposals: dict) -> list[dict]:
    """Freeze the ordinary CLI documents and original absent-row preconditions.

    This writes private review inputs only. It calls no policy mutation and
    derives no permission from an installed provider or signed declaration.
    """
    from tools.phase2_operator_process import write_json
    from tools.rust_capsule_project import read_file
    from .inputs import digest
    result = []
    for family, kind in (("bindings", "provider-binding"), ("policies", "policy")):
        for name, document in proposals[family].items():
            require(isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
                    and len(result) < 16, "bounded-original-policy-mutation-set")
            source = client.directory / f"authority-{kind}-{name}.json"
            write_json(source, document)
            raw = read_file(source, 262144)
            result.append({"kind": kind, "id": name, "file": source.name,
                "operationId": f"java-reviewed-{kind}-{name}", "expectedGeneration": 0,
                "digest": digest(raw), "bytes": len(raw)})
    require(result, "nonempty-original-policy-mutation-set")
    return result


def apply_retained(client, proposals: dict, mutations: list[dict]) -> dict:
    """Apply each exact reviewed file once through the existing native CLI.

    Validate the complete retained program before its first mutation. No read
    refreshes an operation ID, precondition, provider profile or document.
    """
    from tools.rust_capsule_project import read_file
    from .inputs import decode, digest
    expected = [(kind, name, document) for family, kind in (("bindings", "provider-binding"), ("policies", "policy"))
                for name, document in proposals[family].items()]
    require(isinstance(mutations, list) and len(expected) == len(mutations) and 0 < len(mutations) <= 16,
            "original-policy-mutation-count")
    for row, (kind, name, document) in zip(mutations, expected):
        require(isinstance(row, dict) and set(row) == {"kind", "id", "file", "operationId", "expectedGeneration", "digest", "bytes"}
                and isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
                and row["kind"] == kind and row["id"] == name
                and row["file"] == f"authority-{kind}-{name}.json"
                and row["operationId"] == f"java-reviewed-{kind}-{name}"
                and type(row["expectedGeneration"]) is int and row["expectedGeneration"] == 0
                and type(row["bytes"]) is int and 0 < row["bytes"] <= 262144,
                "closed-original-policy-mutation")
        raw = read_file(client.directory / row["file"], 262144)
        require(len(raw) == row["bytes"] and digest(raw) == row["digest"] and decode(raw) == document,
                "original-policy-document-byte-drift")
    receipts = {}
    for row in mutations:
        result = client.call("policy", "--kind", row["kind"], "apply", "--id", row["id"],
            "--file", client.directory / row["file"], "--operation-id", row["operationId"],
            "--expected-generation", row["expectedGeneration"])
        require(result["outcomeKnown"] is True and result["data"]["receipt"]["operationId"] == row["operationId"],
                "original-policy-mutation-receipt")
        receipts[row["id"]] = result["data"]["receipt"]
    return receipts
