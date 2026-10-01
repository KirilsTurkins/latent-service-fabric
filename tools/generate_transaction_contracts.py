#!/usr/bin/env python3
"""Reproduce Phase 4 ABI matrix and boundary vectors; --check is read-only."""
from __future__ import annotations

import argparse
import base64
import copy
import json
from pathlib import Path
import re
import struct
import sys
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.transaction_contracts import command_identity, digest, fingerprint

ROOT = Path(__file__).resolve().parents[1]


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def matrix():
    previous = json.loads((ROOT / "wit/host-abi-phase3-v4.json").read_text())
    interfaces = copy.deepcopy(previous["interfaces"][:5])
    for interface, package, source in (
        ("latent:state/key-value@0.2.0", "latent:state", "wit/platform/state/package.wit"),
        ("latent:intents/staging@0.1.0", "latent:intents", "wit/platform/intents/package.wit"),
    ):
        interfaces.append(dict(interface=interface, package=package, source=source,
            sourceSha256=digest((ROOT / source).read_bytes()), binding="provider", asynchronous=True, installed=False))
    identity = b"lsf-host-abi-profile-v1\0"
    frame = lambda value: struct.pack("<Q", len(value)) + value
    identity += frame(b"lsf-host-abi-phase4-v1") + struct.pack("<Q", len(interfaces))
    for item in interfaces:
        identity += frame(item["interface"].encode()) + frame(item["package"].encode())
        identity += bytes([item["binding"] == "provider", item["asynchronous"]])
        identity += frame((ROOT / item["source"]).read_bytes())
    pins = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
    return dict(formatVersion=1, id="lsf-host-abi-phase4-v1", world="latent:platform/capsule@0.5.0",
        digest=digest(identity), wasmtimeVersion=pins["rust"]["dependencies"]["wasmtime"],
        guestGenerator="wit-bindgen@" + pins["rust"]["dependencies"]["wit-bindgen"], interfaces=interfaces)


def vectors():
    key = dict(tenant="tenant", namespace="app", incarnation="i1", recoveryScope="caller/alice", operation="save", clientKey="one")
    body = dict(inputFormat="raw-v1", input=dict(bytes="", mediaType="application/octet-stream", metadata=[]), expectedVersions=[])
    identities = []
    for name, changes in (("caller-default", {}), ("different-caller", {"recoveryScope": "caller/bob"}),
                          ("new-incarnation", {"incarnation": "i2"}), ("delegated-shared-scope", {"recoveryScope": "shared/team"}),
                          ("entity-selection", {"entity": "document-1"})):
        value = {**key, **changes}
        identities.append(dict(name=name, value=value, framedHex=command_identity(value).hex(), sha256=digest(command_identity(value))))
    fingerprints = []
    for name, conditions, data in (("empty", [], b""), ("changed-body", [], b"different"),
        ("expected-absent", [{"key": "YQ==", "absent": True}], b""),
        ("expected-version", [{"key": "YQ==", "version": "aTE6Mg=="}], b"")):
        value = copy.deepcopy(body)
        value["input"]["bytes"] = base64.b64encode(data).decode()
        value["expectedVersions"] = conditions
        fingerprints.append(dict(name=name, value=value, framedHex=fingerprint(value).hex(), sha256=digest(fingerprint(value))))
    scenarios = [
        ("absent-empty-max", ["absent", "empty-present", "maximum", "over-limit"], "preserve-presence-and-reject-over-limit"),
        ("mismatched-command-body", ["admit", "replay-changed-fingerprint"], "fingerprint-mismatch-without-execution"),
        ("same-tenant-different-caller", ["commit-as-alice", "lookup-as-bob"], "permission-denied"),
        ("delegated-scope", ["host-approve-shared-scope", "replay-current-authorized-reader"], "same-command-with-current-read-check"),
        ("revoked-result-read", ["commit", "revoke-result-read", "lookup"], "permission-denied-despite-retained-decoder"),
        ("rejection-after-state-change", ["business-reject", "change-business-state", "replay"], "original-durable-rejection-no-reexecution"),
        ("concurrent-proven-abort-retry", ["technical-abort-and-owner-retired", "two-explicit-fenced-attempts"], "one-next-attempt-original-receipt-retained"),
        ("unknown-expired-not-abort", ["unknown-or-expired-lookup", "retry-without-fence"], "recovery-required-no-execution"),
        ("fresh-query-after-ack", ["commit-ack", "fresh-query-minimum-view"], "view-at-least-acknowledged-version"),
        ("stale-edit-precondition", ["user-read", "intervening-write", "command-expected-old-version"], "stale-input-distinct-from-occ-conflict"),
        ("uncertain-commit", ["atomic-write", "lose-transport-ack", "lookup-current-authorized-reader"], "committed-or-recovery-required-never-invent-abort"),
        ("cancel-after-commit", ["commit", "cancel-or-cleanup-failure"], "already-committed-with-receipt"),
        ("effect-uncertainty", ["dispatch", "provider-ack-lost"], "uncertain-after-dispatch-no-unqualified-retry"),
        ("bounded-paging", ["page-max", "wrong-prefix-or-view-cursor", "cross-request-query-cursor"], "bounded-page-or-invalid-cursor"),
        ("source-identity", ["commit-revision-a", "route-to-revision-b", "replay"], "original-exact-source-current-permission"),
        ("retained-old-format", ["retain-result-v1", "upgrade-active-result-format", "decode-v1-current-authorized-reader"], "original-application-bytes-no-security-header-replay"),
        ("unknown-enum-version", ["unknown-profile-or-enum-or-record-version"], "unsupported-before-execution-no-default-success"),
        ("restore-incarnation", ["acknowledge-i1", "restore-older-history-as-i2", "query-or-command-with-i1"], "incarnation-mismatch"),
    ]
    return dict(schemaVersion="latent.transaction.boundary-vectors.v1", evidenceKind="contract-vocabulary",
        executionQualified=False, encodings=dict(bytes="canonical-padded-base64", u64="canonical-decimal-string", strings="strict-utf8"),
        identities=identities, fingerprints=fingerprints,
        unsigned64=["0", "9007199254740991", "9007199254740992", "9223372036854775808", "18446744073709551615"],
        invalidUnsigned64=["", "01", "-1", "18446744073709551616"],
        boundaries=dict(identityUtf8Bytes=256, keyBytes=1024, valueBytes=1048576, metadataPairs=32,
            metadataBytes=8192, pageEntries=128, pageBytes=1048576, stagedBytes=8388608),
        scenarios=[dict(id=name, actions=actions, expected=expected, consumers=["guest-model", "external-client-model", "http-model", "actual-execution"])
            for name, actions, expected in scenarios])


def preparation():
    value = dict(schemaVersion="latent.transaction-contract.preparation-profile.v1",
        profile="lsf-transaction-http-preparation-v1", engine="wasmtime@" + matrix()["wasmtimeVersion"],
        componentAsync=True, hostAbiDigest=matrix()["digest"], codec="application/vnd.latent.wit-values.v1+json",
        hostcallFuel=2097152, limits=dict(maxInputBytes=2097152, maxOutputBytes=2097152, maxDepth=32,
            maxNodes=32768, maxStringBytes=524288, maxCollectionItems=4096, maxTypeNodes=4096,
            maxTypeNameBytes=256, maxLiftedBytes=67108864, maxDecodedValueBytes=16777216),
        runtimeInstallation=False, runtimeExecutionQualified=False)
    identity = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {**value, "digest": digest(b"lsf-transaction-preparation-profile-v1\0" + identity)}


def requirements():
    """Freeze separate complete guest and external-client definition owners."""
    guest = []
    for interface, source in (("latent:state/key-value@0.2.0", "wit/platform/state/package.wit"),
                              ("latent:intents/staging@0.1.0", "wit/platform/intents/package.wit")):
        text = (ROOT / source).read_text(encoding="utf-8")
        guest.append(dict(interface=interface, source=source, sourceSha256=digest((ROOT / source).read_bytes()),
            operations=[dict(name=name, asynchronous=bool(asynchronous))
                for name, asynchronous in re.findall(r"^    ([a-z-]+): (async )?func\(", text, re.MULTILINE)],
            ownedResources=re.findall(r"^    resource ([a-z-]+);", text, re.MULTILINE)))
    client = []
    for service, source in (("latent.transaction.v1.TransactionService", "api/proto/latent/transaction/v1/transaction.proto"),
                            ("latent.control.v1.StateService", "api/proto/latent/control/v1/state.proto")):
        text = (ROOT / source).read_text(encoding="utf-8")
        client.append(dict(service=service, source=source, sourceSha256=digest((ROOT / source).read_bytes()),
            operations=[dict(name=name, request=request, response=response)
                for name, request, response in re.findall(r"^  rpc (\w+)\((\w+)\) returns \((\w+)\);", text, re.MULTILINE)],
            messages=re.findall(r"^message (\w+) \{", text, re.MULTILINE),
            enums=re.findall(r"^enum (\w+) \{", text, re.MULTILINE)))
    return dict(schemaVersion="latent.transaction-contract.requirements.v1", evidenceKind="contract-definition",
        wireProfile="lsf-transaction-v1", hostAbiDigest=matrix()["digest"], preparationProfileDigest=preparation()["digest"],
        languages=["rust", "c", "typescript", "go", "java", "dotnet"], boundaryVectors="sdk/profile/transaction-vectors.json",
        guest=dict(profile="latent.guest.transaction.v1", requiredInterfaces=guest,
            explicitResourceDrop=True, implicitReplay=False, executionQualified=False,
            executionOwnerIssues=[389, 718]),
        externalClient=dict(profile="latent.client.transaction.v1", requiredServices=client,
            requiredHttpEnvelopes=["command", "query", "recovery", "response"],
            applicationSchema="schemas/transaction-api.schema.json", managementAuthority="current-authenticated-host-policy",
            implicitReplay=False, transportExecutionQualified=False, executionOwnerIssues=[401]),
        independentQualification=True, runtimeInstallation=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for relative, value in (("wit/host-abi-phase4-v1.json", matrix()), ("sdk/profile/transaction-vectors.json", vectors()),
                            ("sdk/profile/transaction-preparation-v1.json", preparation()),
                            ("sdk/profile/transaction-requirements-v1.json", requirements())):
        expected, path = encode(value), ROOT / relative
        if args.check:
            if not path.is_file() or path.read_bytes() != expected:
                raise ValueError("transaction generated contract drift: " + relative)
        else:
            path.write_bytes(expected)
    # Keep native admission/client negotiation on the same exact generated
    # profiles. Protobuf decoding alone never installs or authorizes a runtime.
    native = (
        "// Generated by tools/generate_transaction_contracts.py; do not edit.\n"
        'pub const PROFILE: &str = "lsf-transaction-v1";\n'
        f'pub const HOST_ABI_DIGEST: &str =\n    "{matrix()["digest"]}";\n'
        f'pub const PREPARATION_PROFILE_DIGEST: &str =\n    "{preparation()["digest"]}";\n'
    ).encode("utf-8")
    path = ROOT / "crates/latent-rpc/src/phase4/profile.rs"
    if args.check:
        if not path.is_file() or path.read_bytes() != native:
            raise ValueError("transaction native profile drift: " + str(path.relative_to(ROOT)))
    else:
        path.write_bytes(native)


if __name__ == "__main__":
    main()
