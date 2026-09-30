#!/usr/bin/env python3
"""Reproduce Phase 4 ABI matrix and boundary vectors; --check is read-only."""
from __future__ import annotations

import argparse
import base64
import copy
import json
from pathlib import Path
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for relative, value in (("wit/host-abi-phase4-v1.json", matrix()), ("sdk/profile/transaction-vectors.json", vectors())):
        expected, path = encode(value), ROOT / relative
        if args.check:
            if not path.is_file() or path.read_bytes() != expected:
                raise ValueError("transaction generated contract drift: " + relative)
        else:
            path.write_bytes(expected)


if __name__ == "__main__":
    main()
