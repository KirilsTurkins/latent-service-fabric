"""Protected stream policy administration through the existing public RPCs.

Installation and live provider rotation remain node-owner operations. These
helpers grant/revoke one exact installed TCP destination and retain uncertain
policy requests for explicit receipt lookup. They never retry a mutation.
"""
from __future__ import annotations

import copy
import ipaddress
import os
from pathlib import Path
import re
import stat

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow import journal, paths, policy_operations, state
from tools.dev_workflow.client import successful
from tools.dev_workflow.common import DevError, digest, encode, members, require, sha


CAPABILITY = "latent:network/streams@0.1.0"
PROFILE = "lsf-outbound-streams-v1"
OPERATIONS = ["connect", "read", "write", "ready", "inspect", "shutdown", "close", "chunk-bytes"]
MAXIMUM_RECORDS = 32
CEILING = {"operations": 128, "inputBytes": 1048576, "outputBytes": 1048576, "wallTimeMillis": 10000}
STAMP_FIELDS = ("tenant", "id", "recordKind", "generation", "contentDigest", "revoked")


def _private_read(path, maximum=65536):
    path = Path(path).absolute()
    paths.private_root(path.parent)
    with paths.opened(path.parent, path.name) as descriptor:
        before = os.fstat(descriptor)
        if os.name == "posix":
            require(before.st_uid == os.geteuid() and stat.S_IMODE(before.st_mode) in {0o400, 0o600},
                    "stream-operator-file-protection")
        require(before.st_size <= maximum, "stream-operator-file-byte-bound")
        chunks, used = [], 0
        while True:
            raw = os.read(descriptor, min(65536, maximum + 1 - used))
            if not raw:
                break
            used += len(raw)
            require(used <= maximum, "stream-operator-file-byte-bound")
            chunks.append(raw)
        after = os.fstat(descriptor)
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_mode, before.st_uid)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_mode, after.st_uid),
                "stream-operator-file-changed-during-read")
        return b"".join(chunks)


def configure(settings, installation, bindings, *, development_profile=False):
    """Construct the explicitly gated node input; actual check-config is required.

    Existing installations, credentials, budgets and binding definitions stay
    intact. Replacing an installed provider requires its live node-owner path.
    """
    require(development_profile is True, "stream-operator-development-profile-required")
    require(isinstance(settings, dict) and isinstance(installation, dict)
            and isinstance(bindings, list) and 0 < len(bindings) <= 16,
            "stream-operator-configuration-shape")
    require(settings.get("budgetProfile", {}).get("mode") == "phase3"
            and settings.get("audit", {}).get("mode") == "durable"
            and settings.get("capabilityPolicies", {}).get("formatVersion") == 1,
            "stream-operator-required-node-owners")
    result = copy.deepcopy(settings)
    providers = result.setdefault("providers", {"formatVersion": 1, "bindings": []})
    require("outboundStreams" not in providers and isinstance(providers.get("bindings"), list),
            "stream-operator-installed-provider-needs-owner-rotation")
    selected = copy.deepcopy(installation)
    pending = [(selected, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        require(depth <= 16 and count <= 4096, "stream-operator-configuration-structure-bound")
        require(not isinstance(value, float), "stream-operator-integer-input-required")
        if isinstance(value, dict):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
    members(selected, {"identity", "configuration"})
    identity = selected["identity"]
    members(identity, {"id", "tenant", "service", "epoch"})
    for field in ("id", "tenant", "service"):
        _token(identity[field])
    require(type(identity["epoch"]) is int and 1 <= identity["epoch"] <= 18446744073709551615,
            "stream-operator-installed-provider-epoch")
    for name, provider in providers.items():
        if name in {"formatVersion", "bindings"}:
            continue
        other = provider.get("identity", {}) if isinstance(provider, dict) else {}
        require(other.get("id") != identity["id"]
                and (other.get("tenant"), other.get("service")) != (identity["tenant"], identity["service"]),
                "stream-operator-provider-identity-collision")
    names = {binding.get("name") for binding in providers["bindings"]}
    for binding in bindings:
        members(binding, {"name", "tenant", "consumerService", "providerService", "contract", "providerBinding"})
        require(binding["name"] not in names and binding["tenant"] == identity["tenant"]
                and binding["providerService"] == identity["service"] and binding["contract"] == CAPABILITY,
                "stream-operator-binding-scope")
        for field in ("name", "consumerService", "providerBinding"):
            _token(binding[field])
        names.add(binding["name"])
        providers["bindings"].append(copy.deepcopy(binding))
    providers["outboundStreams"] = selected
    configuration = selected["configuration"]
    require(isinstance(configuration, dict) and isinstance(configuration.get("destinations"), list)
            and 0 < len(configuration["destinations"]) <= 8, "stream-operator-destination-bound")
    for destination in configuration["destinations"]:
        require(isinstance(destination, dict) and "endpoint" in destination, "stream-operator-destination-shape")
        endpoint(destination["endpoint"])
    import json
    import jsonschema
    from referencing import Registry, Resource
    source = Path(__file__).resolve().parents[1] / "schemas"
    schema = json.loads((source / "node-providers.schema.json").read_text(encoding="utf-8"))
    stream_schema = json.loads((source / "outbound-stream-provider.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(stream_schema["$id"], Resource.from_contents(stream_schema))
    try:
        jsonschema.Draft202012Validator(schema, registry=registry).validate(providers)
    except jsonschema.ValidationError:
        raise DevError("stream-operator-configuration-invalid") from None
    require(len(encode(result)) <= 65536, "stream-operator-node-configuration-byte-bound")
    return result


def _token(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/@-]{1,128}", value),
            "stream-operator-invalid-identity")
    return value


def endpoint(value):
    members(value, {"host", "port", "transport"})
    host = value["host"]
    require(isinstance(host, str) and 0 < len(host) <= 253
            and type(value["port"]) is int and 1 <= value["port"] <= 65535
            and value["transport"] == "tcp", "stream-operator-unsupported-endpoint")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        require(all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
                and not labels[-1].isdigit()
                and not (host.startswith("0x") and re.fullmatch(r"[0-9a-f]+", host[2:])),
                "stream-operator-noncanonical-host")
    else:
        require(str(address) == host and not getattr(address, "ipv4_mapped", None),
                "stream-operator-noncanonical-host")
    return dict(value)


def descriptor(value, tenant):
    members(value, {"id", "tenant", "service", "capability", "profile",
                    "configurationDigest", "configurationEpoch"})
    _token(value["id"]); _token(value["service"])
    require(value["tenant"] == tenant and value["capability"] == CAPABILITY
            and value["profile"] == PROFILE, "stream-operator-installed-provider-scope")
    sha(value["configurationDigest"])
    epoch = value["configurationEpoch"]
    require(isinstance(epoch, str) and re.fullmatch(r"[1-9][0-9]{0,19}", epoch)
            and int(epoch) <= 18446744073709551615, "stream-operator-installed-provider-epoch")
    return dict(value)


class StreamOperator:
    """One private owner, exact publication/destination, and a durable journal."""

    def __init__(self, root: Path, client, *, node: str, tenant: str, provider: dict,
                 consumer: str, publication: str, principal: dict, destination: dict,
                 binding_id: str, policy_id: str):
        paths.private_root(root)
        members(principal, {"kind", "subject"})
        require(principal["kind"] in {"user", "service", "node", "trigger", "administrator"},
                "stream-operator-principal-kind")
        _token(principal["subject"])
        for value in (node, tenant, consumer, publication, binding_id, policy_id):
            _token(value)
        require(binding_id != policy_id, "stream-operator-distinct-record-identities")
        config = Path(client.config).absolute()
        config_digest = digest(_private_read(config))
        self.root, self.client = root, client
        self.owner = {
            "schemaVersion": "latent.outbound-stream.operator.v1", "node": node, "tenant": tenant,
            "provider": descriptor(provider, tenant), "consumer": consumer, "publication": publication,
            "principal": dict(principal), "endpoint": endpoint(destination),
            "bindingId": binding_id, "policyId": policy_id, "clientConfigurationDigest": config_digest,
        }
        with state.lock(root, "stream-operator.lock"):
            if (root / "stream-operator-owner.json").exists():
                require(state.load(root, "stream-operator-owner.json") == self.owner,
                        "stream-operator-owner-changed")
            else:
                require(not (root / "operations.json").exists()
                        and not (root / "stream-policy-receipts.json").exists(),
                        "stream-operator-state-not-owned")
                state.atomic(root, "stream-operator-owner.json", self.owner)
        self.journal = journal.Journal(root, node, tenant, settle=self._settle)

    def _owned(self):
        require(state.load(self.root, "stream-operator-owner.json") == self.owner,
                "stream-operator-owner-changed")
        config = Path(self.client.config).absolute()
        require(digest(_private_read(config))
                == self.owner["clientConfigurationDigest"], "stream-operator-client-identity-changed")

    def _records(self):
        records = state.load(self.root, "stream-policy-receipts.json") if (
            self.root / "stream-policy-receipts.json").exists() else {}
        require(isinstance(records, dict) and len(records) <= MAXIMUM_RECORDS,
                "stream-operator-retained-record-bound")
        return records

    def _settle(self, operation, result):
        if result["category"] != "success":
            return
        receipt = result["data"]["receipt"]
        key = receipt["recordKind"] + ":" + receipt["id"]
        records = self._records()
        require(key in records or len(records) < MAXIMUM_RECORDS, "stream-operator-retained-record-bound")
        records[key] = {"receipt": receipt, "document": operation["intent"]["document"]}
        state.atomic(self.root, "stream-policy-receipts.json", records)

    def _apply(self, kind, record_id, document):
        require(self.journal.read()["pending"] is None, "recover-original-operation-before-new-mutation")
        records = self._records()
        key = kind + ":" + record_id
        observed = self.client.call("policy", "--kind", kind, "get", "--id", record_id)
        require(observed.get("outcomeKnown") is True and observed.get("category") in {"success", "not-found"},
                "stream-operator-policy-observation-unavailable")
        if key in records:
            current = observed.get("data", {}).get("policy")
            previous = records[key]
            require(observed["category"] == "success" and isinstance(current, dict)
                    and all(current.get(field) == previous["receipt"].get(field) for field in STAMP_FIELDS)
                    and current.get("document") == previous["document"], "stream-operator-policy-changed")
            if current["document"] == document:
                return record_id
            expected = current["generation"]
        else:
            require(observed["category"] == "not-found", "stream-operator-policy-not-owned")
            expected = "0"
        state.atomic(self.root, "selected-stream-policy.json", document)
        try:
            result = self.journal.execute("policy", {"policyId": record_id, "recordKind": kind,
                "document": document, "expectedGeneration": expected}, lambda operation:
                self.client.call("policy", "--kind", kind, "apply", "--id", record_id,
                    "--file", self.root / "selected-stream-policy.json", "--operation-id", operation,
                    "--expected-generation", expected))
        except DevError as error:
            if self.journal.read()["pending"] is not None:
                raise DevError(error.code, uncertain=True) from None
            raise
        successful(result)
        return record_id

    def _policy(self, effect):
        return {"formatVersion": 1, "tenant": self.owner["tenant"], "rules": [{
            "id": "stream", "effect": effect, "principals": [copy.deepcopy(self.owner["principal"])],
            "services": [self.owner["consumer"]], "publications": [self.owner["publication"]],
            "capability": CAPABILITY, "operations": list(OPERATIONS),
            "resources": {"kind": "stream", "endpoints": [copy.deepcopy(self.owner["endpoint"])]},
            "requireAudit": True, "ceiling": dict(CEILING)}]}

    def grant(self):
        with state.lock(self.root, "stream-operator.lock"):
            self._owned()
            provider = self.owner["provider"]
            self._apply("provider-binding", self.owner["bindingId"], {
                "formatVersion": 1, "tenant": self.owner["tenant"], "capability": CAPABILITY,
                "providerProfile": PROFILE, "configurationDigest": provider["configurationDigest"],
                "configurationEpoch": int(provider["configurationEpoch"]),
                "restriction": {"operations": list(OPERATIONS)}})
            self._apply("policy", self.owner["policyId"], self._policy("allow"))
            return {"capability": CAPABILITY, "policy": self.owner["policyId"]}

    def revoke(self):
        with state.lock(self.root, "stream-operator.lock"):
            self._owned()
            require("policy:" + self.owner["policyId"] in self._records(), "stream-operator-no-owned-grant")
            # Apply a durable deny at the original owned policy generation. No
            # deletion/new grant, provider replay or early physical refund.
            return self._apply("policy", self.owner["policyId"], self._policy("deny"))

    def recover(self):
        with state.lock(self.root, "stream-operator.lock"):
            self._owned()
            return self.journal.recover(lambda kind, operation: policy_operations.lookup(self.client, operation))

    def adopt_provider(self, provider):
        """Explicitly record an observed new generation, without any mutation RPC.

        The same protected owner, exact endpoint and publication remain bound.
        A later grant must separately apply the new binding and observe its
        receipt; adoption neither rotates a provider nor grants authority.
        """
        with state.lock(self.root, "stream-operator.lock"):
            self._owned()
            require(self.journal.read()["pending"] is None,
                    "recover-original-operation-before-provider-adoption")
            replacement = descriptor(provider, self.owner["tenant"])
            previous = self.owner["provider"]
            require(all(replacement[field] == previous[field] for field in
                        ("id", "tenant", "service", "capability", "profile"))
                    and int(replacement["configurationEpoch"]) > int(previous["configurationEpoch"]),
                    "stream-operator-replacement-provider-scope")
            records = self._records()
            for kind, field in (("provider-binding", "bindingId"), ("policy", "policyId")):
                key = kind + ":" + self.owner[field]
                require(key in records, "stream-operator-no-owned-grant")
                observed = self.client.call("policy", "--kind", kind, "get", "--id", self.owner[field])
                current = observed.get("data", {}).get("policy")
                expected = records[key]
                require(observed.get("outcomeKnown") is True and observed.get("category") == "success"
                        and isinstance(current, dict)
                        and all(current.get(stamp) == expected["receipt"].get(stamp) for stamp in STAMP_FIELDS)
                        and current.get("document") == expected["document"],
                        "stream-operator-policy-changed")
            owner = {**self.owner, "provider": replacement}
            state.atomic(self.root, "stream-operator-owner.json", owner)
            self.owner = owner
            return {"provider": replacement, "executionPermission": False,
                    "outcome": "descriptor-adopted-binding-grant-still-required"}

    def inspect(self, deployment):
        _token(deployment)
        with state.lock(self.root, "stream-operator.lock"):
            self._owned()
            result = self.client.call("capability", "list", "--deployment", deployment,
                "--provider", self.owner["provider"]["id"], "--include-node-usage", "--page-size", "1")
            value = successful(result)
            require(value.get("executionPermission") is False
                    and value.get("revision", {}).get("deploymentId") == deployment,
                    "stream-operator-inspection-is-not-authority")
            return value


def main(argv=None):
    import argparse
    import json
    import sys
    import time
    from tools.build_process_signals import owned_cancellation
    from tools.dev_workflow.client import Client
    from tools.dev_workflow.common import decode
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("grant", "revoke", "recover", "inspect", "adopt"))
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--client-config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--specification", type=Path, required=True)
    parser.add_argument("--deployment")
    parser.add_argument("--provider-record", type=Path)
    args = parser.parse_args(argv)
    try:
        source = args.specification.absolute()
        specification = decode(_private_read(source), 65536)
        members(specification, {"node", "tenant", "provider", "consumer", "publication", "principal",
                                "destination", "bindingId", "policyId"})
        root = args.state_dir.absolute()
        paths.private_root(root)
        require((args.command == "inspect") == (args.deployment is not None),
                "stream-operator-deployment-only-for-inspection")
        require((args.command == "adopt") == (args.provider_record is not None),
                "stream-operator-provider-record-only-for-adoption")
        with owned_cancellation():
            client = Client(args.cli.absolute(), args.client_config.absolute(), root,
                            deadline=time.monotonic() + 90)
            operator = StreamOperator(root, client, **{key: value for key, value in specification.items()
                if key not in {"bindingId", "policyId"}}, binding_id=specification["bindingId"],
                policy_id=specification["policyId"])
            if args.command == "inspect":
                result = operator.inspect(args.deployment)
            elif args.command == "adopt":
                result = operator.adopt_provider(decode(_private_read(args.provider_record.absolute()), 65536))
            else:
                result = getattr(operator, args.command)()
        print(json.dumps({"schemaVersion": "latent.outbound-stream.operator.result.v1",
                         "command": args.command, "status": "completed", "result": result}))
        return 0
    except DevError as error:
        print(json.dumps({"schemaVersion": "latent.outbound-stream.operator.result.v1",
                         "command": args.command, "status": "failed", "code": error.code,
                         "uncertain": error.uncertain}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
