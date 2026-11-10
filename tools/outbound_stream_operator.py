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
# Same bound as latent_policy::capability::MAX_DOCUMENT_BYTES.
MAXIMUM_POLICY_BYTES = 64 * 1024
CEILING = {"operations": 128, "inputBytes": 1048576, "outputBytes": 1048576, "wallTimeMillis": 10000}
STAMP_FIELDS = ("tenant", "id", "recordKind", "generation", "contentDigest", "revoked")


def _same_owned_policy(current, previous):
    """Compare the complete retained identity without JSON bool/number coercion."""
    if (not isinstance(current, dict) or not isinstance(previous, dict)
            or not isinstance(previous.get("receipt"), dict)
            or not isinstance(previous.get("document"), dict)
            or not isinstance(current.get("document"), dict)):
        return False
    receipt = previous["receipt"]
    return (all(type(receipt.get(field)) is (bool if field == "revoked" else str)
                and type(current.get(field)) is type(receipt[field])
                and current[field] == receipt[field] for field in STAMP_FIELDS)
            and encode(current["document"]) == encode(previous["document"]))


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
    installation_bytes = _private_read(installation_record)
    selected = decode(installation_bytes, 65536, maximum_items=4096)
    members(selected, {"installation", "bindings"})
    base_bytes = _private_read(base_config)
    settings = decode(base_bytes, 65536, maximum_items=4096)
    raw = encode(configure(settings, selected["installation"], selected["bindings"],
                           development_profile=True))
    inputs = ((installation_record, installation_bytes), (base_config, base_bytes))
    return _write_and_check_configuration(output, node, node_identity, raw, inputs)


def prepare_rotation_configuration(base_config, rotation_record, output, node, *, development_profile=False):
    from tools.dev_workflow.common import decode
    require(development_profile is True, "stream-operator-development-profile-required")
    output = Path(output).absolute()
    node = Path(node).absolute()
    node_identity = paths.digest_file(node.parent, node.name, 256 * 1024 * 1024)
    require(node_identity[1] > 0, "stream-operator-node-binary-empty")
    paths.private_root(output.parent)
    rotation_bytes = _private_read(rotation_record)
    rotation = decode(rotation_bytes, 65536, maximum_items=4096)
    base_bytes = _private_read(base_config)
    settings = decode(base_bytes, 65536, maximum_items=4096)
    raw = encode(rotate_configuration(settings, rotation, development_profile=True))
    inputs = ((rotation_record, rotation_bytes), (base_config, base_bytes))
    result = _write_and_check_configuration(output, node, node_identity, raw, inputs)
    return {**result, "outcome": "prepared-rotation-configuration-check-accepted"}


def _same_preparation_inputs(inputs):
    for path, original in inputs:
        require(_private_read(path) == original, "stream-operator-preparation-input-changed")


def _write_and_check_configuration(output, node, node_identity, raw, inputs):
    from tools.dev_workflow import process
    _same_preparation_inputs(inputs)
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
    _same_preparation_inputs(inputs)
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
        require(str(address) == host and getattr(address, "scope_id", None) is None
                and not getattr(address, "ipv4_mapped", None),
                "stream-operator-noncanonical-host")
    return dict(value)


def _canonical_publication(value):
    # Exact latent_core::PublicationId grammar; this is identity, not authority.
    return isinstance(value, str) and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", value) is not None


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
            existing = (root / "stream-operator-owner.json").exists()
            if existing:
                require(encode(state.load(root, "stream-operator-owner.json")) == encode(self.owner),
                        "stream-operator-owner-changed")
            else:
                require(_canonical_publication(publication), "stream-operator-invalid-publication")
                require(not (root / "operations.json").exists()
                        and not (root / "stream-policy-receipts.json").exists(),
                        "stream-operator-state-not-owned")
            client.pin_config(config_digest)
            if not existing:
                state.atomic(root, "stream-operator-owner.json", self.owner)
        self.journal = journal.Journal(root, node, tenant, settle=self._settle)

    def _owned(self):
        require(encode(state.load(self.root, "stream-operator-owner.json")) == encode(self.owner),
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
        require(_canonical_publication(self.owner["publication"]), "stream-operator-invalid-publication")
        records = self._records()
        key = kind + ":" + record_id
        require(key in records or len(records) < MAXIMUM_RECORDS,
                "stream-operator-retained-record-bound")
        observed = self.client.call("policy", "--kind", kind, "get", "--id", record_id)
        self._owned()
        require(observed.get("outcomeKnown") is True and observed.get("category") in {"success", "not-found"},
                "stream-operator-policy-observation-unavailable")
        if key in records:
            current = observed.get("data", {}).get("policy")
            previous = records[key]
            require(observed["category"] == "success" and _same_owned_policy(current, previous),
                    "stream-operator-policy-changed")
            if encode(current["document"]) == encode(document):
                return record_id
            expected = current["generation"]
        else:
            require(observed["category"] == "not-found", "stream-operator-policy-not-owned")
            expected = "0"
        # The journal and child consume one frozen encoding. The selected file
        # remains for private review, but is never reopened as the RPC payload.
        selected = copy.deepcopy(document)
        payload = encode(selected)
        require(len(payload) <= MAX_DOCUMENT, "state-byte-limit")
        require(len(payload) <= MAXIMUM_POLICY_BYTES, "stream-operator-policy-byte-bound")
        state.atomic(self.root, "selected-stream-policy.json", selected)
        try:
            result = self.journal.execute("policy", {"policyId": record_id, "recordKind": kind,
                "document": selected, "expectedGeneration": expected}, lambda operation:
                self.client.call("policy", "--kind", kind, "apply", "--id", record_id,
                    "--file", "-", "--operation-id", operation,
                    "--expected-generation", expected, stdin=payload))
        except (DevError, OSError) as error:
            if self.journal.read()["pending"] is not None:
                code = error.code if isinstance(error, DevError) else "stream-operator-mutation-unavailable"
                raise DevError(code, uncertain=True) from None
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

    def _binding(self):
        provider = self.owner["provider"]
        return {"formatVersion": 1, "tenant": self.owner["tenant"], "capability": CAPABILITY,
                "providerProfile": PROFILE, "configurationDigest": provider["configurationDigest"],
                "configurationEpoch": int(provider["configurationEpoch"]),
                "restriction": {"operations": list(OPERATIONS)}}

    def grant(self):
        with state.lock(self.root, "stream-operator.lock"):
            self._owned()
            require(self.journal.read()["pending"] is None, "recover-original-operation-before-new-mutation")
            records = self._records()
            keys = ("provider-binding:" + self.owner["bindingId"], "policy:" + self.owner["policyId"])
            require(len(records) + sum(key not in records for key in keys) <= MAXIMUM_RECORDS,
                    "stream-operator-retained-record-bound")
            self._apply("provider-binding", self.owner["bindingId"], self._binding())
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
            names = ("stream-operator-owner.json", "operations.json", "stream-policy-receipts.json")

            def snapshot():
                return {name: _private_read(self.root / name, MAX_DOCUMENT)
                        if os.path.lexists(self.root / name) else None for name in names}

            try:
                self._owned()
                before = snapshot()
                pending = self.journal.read()["pending"]
                if pending is not None:
                    self._pending_client_operation(pending)
                require(snapshot() == before, "stream-operator-recovery-state-changed")

                def lookup(kind, operation):
                    require(snapshot() == before, "stream-operator-recovery-state-changed")
                    current = self.journal.read()["pending"]
                    self._pending_client_operation(current)
                    require(kind == current["kind"] and operation == current["id"],
                            "stream-operator-recovery-journal-changed")
                    result = policy_operations.lookup(self.client, operation)
                    self._owned()
                    require(snapshot() == before, "stream-operator-recovery-state-changed")
                    return result

                return self.journal.recover(lookup)
            except DevError as error:
                if error.code == "no-pending-operation":
                    raise
                raise DevError(error.code, uncertain=True) from None
            except (OSError, KeyError, TypeError, AttributeError):
                raise DevError("stream-operator-recovery-state-unavailable", uncertain=True) from None

    def adopt_provider(self, provider):
        """Explicitly record an observed new generation, without any mutation RPC.

        The same protected owner, exact endpoint and publication remain bound.
        A later grant must separately apply the new binding and observe its
        receipt; adoption neither rotates a provider nor grants authority.
        """
        with state.lock(self.root, "stream-operator.lock"):
            names = ("stream-operator-owner.json", "operations.json", "stream-policy-receipts.json")

            def snapshot():
                return {name: _private_read(self.root / name, MAX_DOCUMENT)
                        if (self.root / name).exists() else None for name in names}

            before = snapshot()
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
                        and _same_owned_policy(current, expected),
                        "stream-operator-policy-changed")
            self._owned()
            require(snapshot() == before, "stream-operator-provider-adoption-state-changed")
            owner = {**self.owner, "provider": replacement}
            state.atomic(self.root, "stream-operator-owner.json", owner)
            self.owner = owner
            return {"provider": replacement, "executionPermission": False,
                    "outcome": "descriptor-adopted-binding-grant-still-required"}

    def _pending_client_operation(self, pending):
        """Accept only this owner's original bounded stream-policy intent."""
        members(pending, {"id", "kind", "intent", "requestDigest", "node", "tenant", "state"})
        intent = members(pending["intent"], {"policyId", "recordKind", "document", "expectedGeneration"})
        require(pending["kind"] == "policy" and pending["node"] == self.owner["node"]
                and pending["tenant"] == self.owner["tenant"] and pending["state"] == "prepared"
                and isinstance(pending["id"], str) and re.fullmatch(r"dev-[0-9a-f]{32}", pending["id"])
                and pending["requestDigest"] == digest(encode(intent)),
                "stream-operator-pending-operation-scope")
        generation = intent["expectedGeneration"]
        require(type(generation) is str and re.fullmatch(r"0|[1-9][0-9]{0,19}", generation)
                and int(generation) <= 18446744073709551615,
                "stream-operator-pending-operation-generation")
        if intent["recordKind"] == "provider-binding":
            record_id, documents = self.owner["bindingId"], (self._binding(),)
        else:
            require(intent["recordKind"] == "policy", "stream-operator-pending-operation-scope")
            record_id = self.owner["policyId"]
            documents = (self._policy("allow"), self._policy("deny"))
        require(intent["policyId"] == record_id
                and any(encode(intent["document"]) == encode(document) for document in documents),
                "stream-operator-pending-operation-scope")
        return intent["recordKind"] + ":" + record_id

    def adopt_client(self, replacement, *, preserve_pending=False):
        """Authenticate a token-only handoff, optionally retaining a verified intent.

        The explicit pending path observes the original receipt without settling
        it. A separate recover must still confirm it using the adopted client.
        """
        require(type(preserve_pending) is bool, "stream-operator-pending-adoption-option")
        try:
            return self._adopt_client(replacement, preserve_pending=preserve_pending)
        except (DevError, OSError) as error:
            if not preserve_pending:
                raise
            code = error.code if isinstance(error, DevError) else "stream-operator-file-unavailable-or-unsafe"
            raise DevError(code, uncertain=True) from None

    def _adopt_client(self, replacement, *, preserve_pending):
        with state.lock(self.root, "stream-operator.lock"):
            names = ("stream-operator-owner.json", "operations.json", "stream-policy-receipts.json")

            def snapshot():
                return {name: _private_read(self.root / name, MAX_DOCUMENT)
                        if (self.root / name).exists() else None for name in names}

            before = snapshot()
            self._owned()
            pending = self.journal.read()["pending"]
            if preserve_pending:
                require(pending is not None, "stream-operator-pending-adoption-requires-operation")
                pending_key = self._pending_client_operation(pending)
            else:
                require(pending is None, "recover-original-operation-before-client-adoption")
                pending_key = None
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
            replacement.pin_config(digest(candidate))
            records = self._records()
            for kind, field in (("provider-binding", "bindingId"), ("policy", "policyId")):
                key = kind + ":" + self.owner[field]
                if preserve_pending and key not in records:
                    # A first binding may be uncertain before either receipt is
                    # retained. A pending policy still requires its owned binding.
                    require(key == pending_key or pending["intent"]["recordKind"] == "provider-binding"
                            and kind == "policy", "stream-operator-no-owned-grant")
                    continue
                previous = records.get(key)
                require(isinstance(previous, dict) and isinstance(previous.get("receipt"), dict)
                        and isinstance(previous.get("document"), dict)
                        and all(stamp in previous["receipt"] for stamp in STAMP_FIELDS),
                        "stream-operator-no-owned-grant")

            if preserve_pending:
                previous = records.get(pending_key)
                if previous is None:
                    require(pending["intent"]["expectedGeneration"] == "0",
                            "stream-operator-pending-operation-precondition")
                elif previous["receipt"].get("operationId") == pending["id"]:
                    # A crash may retain the confirmed local receipt before
                    # Journal.finish clears pending. Validate, but do not settle.
                    policy_operations.confirm(pending, {"data": {"receipt": previous["receipt"],
                        "policy": {**previous["receipt"], "document": previous["document"]}}})
                else:
                    require(previous["receipt"].get("generation") == pending["intent"]["expectedGeneration"],
                            "stream-operator-pending-operation-precondition")

            def read(*arguments, absent=False):
                observed = replacement.call(*arguments)
                require(isinstance(observed, dict) and type(observed.get("outcomeKnown")) is bool
                        and isinstance(observed.get("category"), str) and isinstance(observed.get("data"), dict),
                        "stream-operator-client-observation-unavailable")
                if absent:
                    require(observed["outcomeKnown"] and observed["category"] == "not-found",
                            "stream-operator-policy-not-owned")
                    return None
                return successful(observed)

            observed = read("node", "get", self.owner["node"])
            inventory = observed.get("inventory")
            require(isinstance(inventory, dict) and isinstance(inventory.get("node"), dict)
                    and inventory["node"].get("id") == self.owner["node"],
                    "stream-operator-client-node-changed")
            if preserve_pending:
                receipt_data = read("policy", "operation", "--operation-id", pending["id"])
                require(receipt_data.get("mutationOutcome") != "unknown"
                        and isinstance(receipt_data.get("receipt"), dict),
                        "original-operation-unknown-or-expired-no-replay")
            for kind, field in (("provider-binding", "bindingId"), ("policy", "policyId")):
                key = kind + ":" + self.owner[field]
                absent = preserve_pending and key != pending_key and key not in records
                observed = read("policy", "--kind", kind, "get", "--id", self.owner[field], absent=absent)
                if absent:
                    continue
                current = observed.get("policy")
                if key == pending_key:
                    # Verify the exact receipt and complete original document;
                    # do not call Journal.finish or release its pending intent.
                    policy_operations.confirm(pending, {"data": {
                        "receipt": receipt_data["receipt"], "policy": current}})
                else:
                    require(_same_owned_policy(current, records[key]),
                            "stream-operator-policy-changed")
            self._owned()
            require(snapshot() == before, "stream-operator-client-adoption-state-changed")
            require(_private_read(self.client.config) == original and _private_read(replacement.config) == candidate,
                    "stream-operator-client-adoption-input-changed")
            owner = {**self.owner, "clientConfigurationDigest": digest(candidate)}
            state.atomic(self.root, "stream-operator-owner.json", owner)
            self.owner, self.client = owner, replacement
            if preserve_pending:
                return {"executionPermission": False, "recoveryRequired": True,
                        "outcome": "client-token-adopted-original-operation-pending"}
            return {"executionPermission": False, "outcome": "client-token-adopted-original-grants-retained"}

    def inspect(self, deployment):
        _token(deployment)
        with state.lock(self.root, "stream-operator.lock"):
            self._owned()
            result = self.client.call("capability", "list", "--deployment", deployment,
                "--provider", PROFILE, "--contract-prefix", CAPABILITY,
                "--include-node-usage", "--page-size", "1")
            self._owned()
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
    parser.add_argument("--preserve-pending", action="store_true",
                        help="adopt-client only: verify the original receipt and retain pending recovery")
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
        require(not args.preserve_pending or args.command == "adopt-client",
                "stream-operator-preserve-pending-only-for-client-adoption")
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
                result = operator.adopt_client(replacement, preserve_pending=args.preserve_pending)
            else:
                result = getattr(operator, args.command)()
        print(json.dumps({"schemaVersion": "latent.outbound-stream.operator.result.v1",
                         "command": args.command, "status": "completed", "result": result}))
        return 0
    except (DevError, OSError) as failure:
        error = failure if isinstance(failure, DevError) else DevError("stream-operator-file-unavailable-or-unsafe")
        print(json.dumps({"schemaVersion": "latent.outbound-stream.operator.result.v1",
                         "command": args.command, "status": "failed", "code": error.code,
                         "uncertain": error.uncertain or (args.command == "adopt-client" and args.preserve_pending)}),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
