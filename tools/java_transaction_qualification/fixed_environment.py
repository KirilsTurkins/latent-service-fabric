"""Exact reviewed fixture data; native current checks remain authoritative."""
from __future__ import annotations

from pathlib import Path
import re

from tools.rust_capsule_project import read_file
from .inputs import decode, digest, require


def load(args):
    path = getattr(args, "reviewed_policy_environment", None)
    expected = getattr(args, "reviewed_policy_environment_digest", None)
    require((path is None) == (expected is None), "paired-reviewed-environment-required")
    if path is None:
        return None
    require(isinstance(path, Path) and path.is_absolute() and path.is_file() and not path.is_symlink()
            and isinstance(expected, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", expected),
            "original-reviewed-environment-input")
    raw = read_file(path, 262144)
    require(digest(raw) == expected, "reviewed-environment-byte-drift")
    value = decode(raw, 262144)
    require(isinstance(value, dict)
            and value.get("schemaVersion") == "latent.java-transaction.stable-unsigned-review.v1"
            and value.get("nativeSource") == args.native_source_commit
            and value.get("originalCompilerSource") == "ff9ecd0733456bceacf5b96f14274b9c2dc0e8e6",
            "reviewed-environment-source-drift")
    recipient = value.get("recipient")
    require(isinstance(recipient, dict) and type(recipient.get("port")) is int
            and 1 <= recipient["port"] <= 65535
            and recipient.get("origin") == {"scheme": "https", "host": "localhost", "port": recipient["port"]}
            and isinstance(recipient.get("providerIncarnation"), str)
            and re.fullmatch(r"[0-9a-f]{64}", recipient["providerIncarnation"]),
            "closed-reviewed-recipient-selector")
    match = re.fullmatch(r"localhost:([1-9][0-9]{0,4})", recipient.get("ingressAuthority", ""))
    require(match is not None and 1 <= int(match[1]) <= 65535
            and int(match[1]) != recipient["port"]
            and recipient.get("ingressBind") == "127.0.0.1:" + match[1],
            "closed-reviewed-ingress-selector")
    bounds = value.get("environment", {})
    require(bounds.get("originalNonrenewableQualificationSeconds") == 1200
            and bounds.get("maximumNodeSessions") == 6 and bounds.get("maximumOfflineNativeActions") == 12,
            "original-reviewed-campaign-bounds")
    rows = value.get("unsignedMutations")
    require(isinstance(rows, list) and len(rows) == 10 and isinstance(value.get("nativeTools"), dict),
            "original-reviewed-policy-count")
    seen = set()
    for row in rows:
        require(isinstance(row, dict) and set(row) == {
            "kind", "id", "file", "operationId", "expectedGeneration", "digest", "bytes"}
            and row["kind"] in {"provider-binding", "policy"}
            and isinstance(row["id"], str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", row["id"])
            and row["file"] == f'authority-{row["kind"]}-{row["id"]}.json'
            and row["operationId"] == f'java-reviewed-{row["kind"]}-{row["id"]}'
            and type(row["expectedGeneration"]) is int and row["expectedGeneration"] == 0
            and type(row["bytes"]) is int and 0 < row["bytes"] <= 262144
            and (row["kind"], row["id"]) not in seen, "closed-reviewed-policy-row")
        seen.add((row["kind"], row["id"]))
        original = read_file(path.parent / "policies" / row["file"], 262144)
        require(len(original) == row["bytes"] and digest(original) == row["digest"],
                "reviewed-policy-original-byte-drift")
    hosts = read_file(path.parent / "observed-native-hosts-reference.json", 262144)
    require(digest(hosts) == value.get("observedHostsReferenceSha256"), "reviewed-host-reference-byte-drift")
    from .reviewed_tls import selected
    selected(args, value)
    return value


def identity(args):
    value = load(args)
    if value is None:
        return None
    result = {"file": str(args.reviewed_policy_environment), "digest": args.reviewed_policy_environment_digest,
              "recipient": value["recipient"]}
    if "reviewedTlsFixture" in value:
        result["reviewedTlsFixture"] = value["reviewedTlsFixture"]
    return result


def check_tools(args, actual):
    value = load(args)
    if value is not None:
        require(actual == value["nativeTools"], "reviewed-native-tools-drift")


def check_inputs(args, items):
    value = load(args)
    if value is not None:
        actual = [{"variant": item.name, "componentDigest": item.component_digest,
                   "companionDigest": item.companion_digest, "sourceDigest": item.source_digest,
                   "compilerSource": item.compiler_source, "hostAbiDigest": item.host_abi_digest,
                   "requirementsDigest": item.requirements_digest} for item in items]
        keys = set(actual[0]) if actual else set()
        expected = [{key: row.get(key) for key in keys} for row in value["originalCompiledInputs"]]
        require(actual == expected, "reviewed-original-compiled-input-drift")


def check_authority(args, client, hosts, mutations):
    value = load(args)
    if value is None:
        return
    reference = decode(read_file(args.reviewed_policy_environment.parent
                                 / "observed-native-hosts-reference.json", 262144), 262144)
    require(hosts == reference, "reviewed-current-native-host-drift")
    require(mutations == value["unsignedMutations"], "reviewed-current-policy-programme-drift")
    for row in mutations:
        raw = read_file(client.directory / row["file"], 262144)
        require(len(raw) == row["bytes"] and digest(raw) == row["digest"], "reviewed-current-policy-byte-drift")
