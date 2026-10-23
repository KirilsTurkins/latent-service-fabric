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
from tools.dev_workflow.common import MAX_DOCUMENT, DevError, decode, digest, encode, members, require, sha


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
    require(all(isinstance(settings.get(key), dict) for key in
                ("budgetProfile", "audit", "capabilityPolicies")), "stream-operator-required-node-owners")
    require(settings.get("budgetProfile", {}).get("mode") == "phase3"
            and settings.get("audit", {}).get("mode") == "durable"
            and settings.get("capabilityPolicies", {}).get("formatVersion") == 1,
            "stream-operator-required-node-owners")
    result = copy.deepcopy(settings)
    providers = result.setdefault("providers", {"formatVersion": 1, "bindings": []})
    require(isinstance(providers, dict) and "outboundStreams" not in providers
            and isinstance(providers.get("bindings"), list)
            and all(isinstance(binding, dict) and isinstance(binding.get("name"), str)
                    for binding in providers["bindings"]),
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
    _validate_schema(providers, "node-providers.schema.json")
    require(len(encode(result)) <= 65536, "stream-operator-node-configuration-byte-bound")
    return result


def rotate_configuration(settings, rotation, *, development_profile=False):
    """Prepare only the epoch/limits change accepted by the protected reload owner.

    The epoch belongs to this supplied file; live currentness still requires the
    actual node owner. This neither replaces that file nor rotates any provider.
    """
    require(development_profile is True, "stream-operator-development-profile-required")
    _validate_schema(rotation, "outbound-stream-rotation.schema.json")
    require(type(rotation["formatVersion"]) is int, "stream-operator-integer-input-required")
    require(isinstance(settings, dict)
            and all(isinstance(settings.get(key), dict) for key in
                    ("budgetProfile", "audit", "capabilityPolicies", "providers")),
            "stream-operator-required-node-owners")
    require(settings["budgetProfile"].get("mode") == "phase3"
            and settings["audit"].get("mode") == "durable"
            and settings["capabilityPolicies"].get("formatVersion") == 1,
            "stream-operator-required-node-owners")
    providers = settings["providers"]
    installed = providers.get("outboundStreams")
    require(isinstance(installed, dict), "stream-operator-rotation-installation-required")
    _validate_schema(providers, "node-providers.schema.json")
    identity = installed["identity"]
    for epoch in (identity["epoch"], rotation["expectedEpoch"], rotation["newEpoch"]):
        require(type(epoch) is int and 1 <= epoch <= 18446744073709551615,
                "stream-operator-rotation-epoch")
    require(rotation["provider"] == {key: identity[key] for key in ("id", "tenant", "service")},
            "stream-operator-rotation-provider-mismatch")
    require(rotation["expectedEpoch"] == identity["epoch"], "stream-operator-rotation-base-epoch-mismatch")
    require(rotation["newEpoch"] > identity["epoch"], "stream-operator-rotation-epoch-not-newer")
    for limits in (installed["configuration"]["limits"], rotation["limits"]):
        require(all(type(value) is int for value in limits.values()), "stream-operator-integer-input-required")
        require(limits["idleTimeoutMillis"] <= limits["absoluteTimeoutMillis"],
                "stream-operator-rotation-deadlines")
    for destination in installed["configuration"]["destinations"]:
        endpoint(destination["endpoint"])
    result = copy.deepcopy(settings)
    selected = result["providers"]["outboundStreams"]
    selected["identity"]["epoch"] = rotation["newEpoch"]
    selected["configuration"]["limits"] = copy.deepcopy(rotation["limits"])
    require(len(encode(result)) <= 65536, "stream-operator-node-configuration-byte-bound")
    return result


def _validate_schema(value, name):
    import jsonschema
    from referencing import Registry, Resource
    registry = Registry()
    for resource in ("node-providers.schema.json", "outbound-stream-provider.schema.json"):
        schema = _schema_document(resource)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    try:
        jsonschema.Draft202012Validator(_schema_document(name), registry=registry).validate(value)
    except jsonschema.ValidationError:
        raise DevError("stream-operator-configuration-invalid") from None



def _schema_document(name):
    from importlib import resources
    from tools.dev_workflow.common import decode
    try:
        selected = resources.files("tools.dev_workflow").joinpath("data/schemas/" + name)
        if not selected.is_file():
            require(Path(__file__).is_file(), "stream-operator-schema-not-packaged")
            selected = Path(__file__).resolve().parents[1] / "schemas" / name
        with selected.open("rb") as source:
            value = decode(source.read(65537), 65536, maximum_items=4096)
        require(isinstance(value, dict), "stream-operator-schema-shape")
        return value
    except OSError:
        raise DevError("stream-operator-schema-not-packaged") from None


def prepare_configuration(base_config, installation_record, output, node, *, development_profile=False):
    """Write one new protected input and ask the selected real node to check it.

    A rejected or interrupted check leaves the prepared file for owner review.
    It never starts a node, grants authority, replaces an input, or retries.
    """
    from tools.dev_workflow.common import decode
    require(development_profile is True, "stream-operator-development-profile-required")
    output = Path(output).absolute()
    node = Path(node).absolute()
    node_identity = paths.digest_file(node.parent, node.name, 256 * 1024 * 1024)
    require(node_identity[1] > 0, "stream-operator-node-binary-empty")
    paths.private_root(output.parent)
    selected = decode(_private_read(installation_record), 65536, maximum_items=4096)
    members(selected, {"installation", "bindings"})
    settings = decode(_private_read(base_config), 65536, maximum_items=4096)
    raw = encode(configure(settings, selected["installation"], selected["bindings"],
                           development_profile=True))
    return _write_and_check_configuration(output, node, node_identity, raw)


def prepare_rotation_configuration(base_config, rotation_record, output, node, *, development_profile=False):
    from tools.dev_workflow.common import decode
    require(development_profile is True, "stream-operator-development-profile-required")
    output = Path(output).absolute()
    node = Path(node).absolute()
    node_identity = paths.digest_file(node.parent, node.name, 256 * 1024 * 1024)
    require(node_identity[1] > 0, "stream-operator-node-binary-empty")
    paths.private_root(output.parent)
    rotation = decode(_private_read(rotation_record), 65536, maximum_items=4096)
    settings = decode(_private_read(base_config), 65536, maximum_items=4096)
    raw = encode(rotate_configuration(settings, rotation, development_profile=True))
    result = _write_and_check_configuration(output, node, node_identity, raw)
    return {**result, "outcome": "prepared-rotation-configuration-check-accepted"}


def _write_and_check_configuration(output, node, node_identity, raw):
    from tools.dev_workflow import process
    try:
        paths.write_new(output, raw)
    except OSError:
        raise DevError("stream-operator-output-not-new-or-unavailable") from None
    # Never return a node's stdout/stderr: it may contain private input details.
    # The existing process owner bounds both pipes, time and descendant cleanup.
    result = process.run([str(node), "check-config", "--config", str(output)],
                         output.parent, timeout=30, maximum=65536)
    require(paths.digest_file(node.parent, node.name, 256 * 1024 * 1024) == node_identity,
            "stream-operator-node-binary-changed")
    require(_private_read(output) == raw, "stream-operator-prepared-configuration-changed")
    require(result.returncode == 0, "stream-operator-node-check-rejected-prepared-file-retained")
    return {"outcome": "prepared-configuration-check-accepted", "configurationDigest": digest(raw),
            "nodeBinary": {"sha256": node_identity[0], "size": node_identity[1]},
            "executionPermission": False, "providerReadiness": "not-observed"}


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


def _client_adoption_document(raw, tenant):
    """Resolve the same default/single profile as the native CLI, without output.

    The replacement CLI still validates the complete native configuration before
    its first read RPC. This finite local view only permits one token to change.
    """
    value = decode(raw, 65536, maximum_items=4096)
    members(value, {"formatVersion", "profiles"}, {"defaultProfile"})
    profiles = value["profiles"]
    require(type(value["formatVersion"]) is int and value["formatVersion"] == 1
            and isinstance(profiles, list) and 1 <= len(profiles) <= 16,
            "stream-operator-client-profile-shape")
    names = set()
    for profile in profiles:
        members(profile, {"name", "endpoint", "tenant", "token"},
                {"connectTimeoutMillis", "rpcTimeoutMillis", "limits"})
        name, token = profile["name"], profile["token"]
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name)
                and name not in names and isinstance(token, str)
                and re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token),
                "stream-operator-client-profile-shape")
        names.add(name)
        for field in ("endpoint", "tenant"):
            require(isinstance(profile[field], str), "stream-operator-client-profile-shape")
        for field in ("connectTimeoutMillis", "rpcTimeoutMillis"):
            require(field not in profile or type(profile[field]) is int
                    and 1 <= profile[field] <= 300000, "stream-operator-client-profile-shape")
        if "limits" in profile:
            bounds = {"maximumComponentBytes": 64 * 1024 * 1024,
                      "maximumPayloadBytes": 1024 * 1024, "maximumResponseBytes": 16 * 1024 * 1024}
            limits = members(profile["limits"], set(), set(bounds))
            require(all(type(number) is int and 1 <= number <= bounds[field]
                        for field, number in limits.items()), "stream-operator-client-profile-shape")
    selected = value.get("defaultProfile")
    require(selected is None or isinstance(selected, str) and selected in names,
            "stream-operator-client-profile-selection")
    require(selected is not None or len(profiles) == 1, "stream-operator-client-profile-selection")
    index = next(i for i, profile in enumerate(profiles) if selected is None or profile["name"] == selected)
    require(profiles[index]["tenant"] == tenant, "stream-operator-client-tenant-changed")
    masked = copy.deepcopy(value)
    masked["profiles"][index]["token"] = None
    return masked, profiles[index]["token"]


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

    def adopt_client(self, replacement):
        """Authenticate one token-only replacement; never replay a mutation."""
        with state.lock(self.root, "stream-operator.lock"):
            names = ("stream-operator-owner.json", "operations.json", "stream-policy-receipts.json")

            def snapshot():
                return {name: _private_read(self.root / name, MAX_DOCUMENT)
                        if (self.root / name).exists() else None for name in names}

            before = snapshot()
            self._owned()
            require(self.journal.read()["pending"] is None,
                    "recover-original-operation-before-client-adoption")
            require(Path(replacement.binary).absolute() == Path(self.client.binary).absolute()
                    and Path(replacement.directory).absolute() == Path(self.client.directory).absolute()
                    and replacement.deadline == self.client.deadline
                    and Path(replacement.config).absolute() != Path(self.client.config).absolute(),
                    "stream-operator-client-owner-changed")
            original = _private_read(self.client.config)
            candidate = _private_read(replacement.config)
            old, old_token = _client_adoption_document(original, self.owner["tenant"])
            new, new_token = _client_adoption_document(candidate, self.owner["tenant"])
            require(old == new and old_token != new_token, "stream-operator-client-token-only-replacement")
            records = self._records()
            for kind, field in (("provider-binding", "bindingId"), ("policy", "policyId")):
                previous = records.get(kind + ":" + self.owner[field])
                require(isinstance(previous, dict) and isinstance(previous.get("receipt"), dict)
                        and isinstance(previous.get("document"), dict)
                        and all(stamp in previous["receipt"] for stamp in STAMP_FIELDS),
                        "stream-operator-no-owned-grant")

            def read(*arguments):
                observed = replacement.call(*arguments)
                require(isinstance(observed, dict) and type(observed.get("outcomeKnown")) is bool
                        and isinstance(observed.get("category"), str) and isinstance(observed.get("data"), dict),
                        "stream-operator-client-observation-unavailable")
                return successful(observed)

            observed = read("node", "get", self.owner["node"])
            inventory = observed.get("inventory")
            require(isinstance(inventory, dict) and isinstance(inventory.get("node"), dict)
                    and inventory["node"].get("id") == self.owner["node"],
                    "stream-operator-client-node-changed")
            for kind, field in (("provider-binding", "bindingId"), ("policy", "policyId")):
                observed = read("policy", "--kind", kind, "get", "--id", self.owner[field])
                current = observed.get("policy")
                previous = records[kind + ":" + self.owner[field]]
                require(isinstance(current, dict)
                        and all(type(current.get(stamp)) is type(previous["receipt"][stamp])
                                and current.get(stamp) == previous["receipt"][stamp] for stamp in STAMP_FIELDS)
                        and encode(current.get("document")) == encode(previous["document"]),
                        "stream-operator-policy-changed")
            self._owned()
            require(snapshot() == before, "stream-operator-client-adoption-state-changed")
            require(_private_read(self.client.config) == original and _private_read(replacement.config) == candidate,
                    "stream-operator-client-adoption-input-changed")
            owner = {**self.owner, "clientConfigurationDigest": digest(candidate)}
            state.atomic(self.root, "stream-operator-owner.json", owner)
            self.owner, self.client = owner, replacement
            return {"executionPermission": False, "outcome": "client-token-adopted-original-grants-retained"}

    def inspect(self, deployment):
        _token(deployment)
        with state.lock(self.root, "stream-operator.lock"):
            self._owned()
            result = self.client.call("capability", "list", "--deployment", deployment,
                "--provider", PROFILE, "--contract-prefix", CAPABILITY,
                "--include-node-usage", "--page-size", "1")
            value = successful(result)
            revision = value.get("revision")
            require(value.get("executionPermission") is False
                    and isinstance(revision, dict) and revision.get("deploymentId") == deployment,
                    "stream-operator-inspection-is-not-authority")
            require(revision.get("publicationId") == self.owner["publication"],
                    "stream-operator-inspection-publication-changed")
            capabilities = value.get("capabilities")
            require(isinstance(capabilities, list) and len(capabilities) <= 1
                    and all(isinstance(entry, dict) and entry.get("id") == CAPABILITY
                            and entry.get("contract") == CAPABILITY and entry.get("provider") == PROFILE
                            and isinstance(entry.get("inspection"), dict)
                            and entry["inspection"].get("providerProfile") == PROFILE
                            for entry in capabilities), "stream-operator-inspection-scope-changed")
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
    parser.add_argument("command", choices=("grant", "revoke", "recover", "inspect", "adopt", "adopt-client", "prepare", "prepare-rotation"))
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--client-config", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--specification", type=Path)
    parser.add_argument("--deployment")
    parser.add_argument("--provider-record", type=Path)
    parser.add_argument("--replacement-client-config", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--base-config", type=Path)
    parser.add_argument("--installation-record", type=Path)
    parser.add_argument("--rotation-record", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--development-profile", action="store_true")
    args = parser.parse_args(argv)
    try:
        require((args.command == "adopt-client") == (args.replacement_client_config is not None),
                "stream-operator-replacement-client-only-for-adoption")
        preparing = args.command in {"prepare", "prepare-rotation"}
        rotating = args.command == "prepare-rotation"
        policy_arguments = (args.cli, args.client_config, args.state_dir, args.specification)
        prepare_arguments = (args.node, args.base_config,
                             args.rotation_record if rotating else args.installation_record, args.output)
        require(all(value is not None for value in (prepare_arguments if preparing else policy_arguments))
                and all(value is None for value in (policy_arguments if preparing else prepare_arguments)),
                "stream-operator-command-arguments")
        require((args.installation_record if rotating else args.rotation_record) is None,
                "stream-operator-command-arguments")
        require(preparing or not args.development_profile, "stream-operator-development-flag-only-for-prepare")
        if preparing:
            require(args.deployment is None and args.provider_record is None,
                    "stream-operator-command-arguments")
            with owned_cancellation():
                prepare = prepare_rotation_configuration if rotating else prepare_configuration
                result = prepare(args.base_config, prepare_arguments[2], args.output, args.node,
                                 development_profile=args.development_profile)
            print(json.dumps({"schemaVersion": "latent.outbound-stream.operator.result.v1",
                             "command": args.command, "status": "completed", "result": result}))
            return 0
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
            elif args.command == "adopt-client":
                replacement = Client(client.binary, args.replacement_client_config.absolute(), root,
                                     deadline=client.deadline)
                result = operator.adopt_client(replacement)
            else:
                result = getattr(operator, args.command)()
        print(json.dumps({"schemaVersion": "latent.outbound-stream.operator.result.v1",
                         "command": args.command, "status": "completed", "result": result}))
        return 0
    except (DevError, OSError) as failure:
        error = failure if isinstance(failure, DevError) else DevError("stream-operator-file-unavailable-or-unsafe")
        print(json.dumps({"schemaVersion": "latent.outbound-stream.operator.result.v1",
                         "command": args.command, "status": "failed", "code": error.code,
                         "uncertain": error.uncertain}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
