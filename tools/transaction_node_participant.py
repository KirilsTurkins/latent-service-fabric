"""Finite real-SDK fixture process and lossless files from authoritative contracts.

This is test orchestration, not an RPC transport or an authority issuer. The
caller supplies an actually admitted node, authenticated caller and independently
prepared executable. No transport failure causes a retry, refresh or abort claim.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from tools.build_process_linux import OwnedProcess

ROOT = Path(__file__).resolve().parents[1]
MAXIMUM = 2 * 1024 * 1024
MAXIMUM_CALLS = 32
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
LANGUAGES = frozenset(("rust", "typescript", "go", "c", "java", "dotnet"))
OBSERVATIONS = {"command": "CommandInspection", "state": "StateOperationReceipt",
                "namespace": "NamespaceOperationReceipt", "effect": "EffectReceipt",
                "dispatcher": "DispatcherOperationReceipt", "effectPlan": "EffectManagementPlan"}


class FixtureError(RuntimeError):
    """Only finite, fixed fixture diagnostic labels are exposed."""


def require(value, reason):
    if not value:
        raise FixtureError(reason)


def _varint(value):
    require(type(value) is int and 0 <= value < 2**64, "fixture-integer")
    output = bytearray()
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def _consume(data, offset):
    value = 0
    for index in range(10):
        require(offset < len(data), "fixture-truncated-varint")
        byte = data[offset]
        offset += 1
        require(index != 9 or byte < 2, "fixture-varint-overflow")
        value |= (byte & 127) << (7 * index)
        if byte < 128:
            return value, offset
    raise FixtureError("fixture-varint-overflow")


class Contract:
    """Fixture wire files only; SDKs execute their own checked DTO conversions."""

    def __init__(self, root=ROOT):
        current = json.loads((root / "sdk/profile/transaction-client-contract.json").read_text(encoding="utf-8"))
        old = json.loads((root / "sdk/profile/contract.json").read_text(encoding="utf-8"))
        self.messages = {**old["messages"], **current["messages"]}
        self.enums = {**old["enums"], **current["enums"]}
        self.operations = {re.sub(r"(?<!^)(?=[A-Z])", "_", item["name"]).lower(): item for item in current["operations"]}
        require(len(self.operations) == 16, "fixture-operation-closure")
        self.profile = {"profile": current["profile"], "host_abi_digest": current["hostAbiDigest"],
                        "preparation_profile_digest": current["preparationProfileDigest"]}

    def _spend(self, budget, amount=1):
        budget[0] -= amount
        require(budget[0] >= 0, "fixture-graph-bound")

    def _kind(self, field):
        return 2 if field["type"] in ("string", "bytes") or field["type"] in self.messages or field.get("map") else 0

    def _scalar(self, field, value, budget, depth):
        self._spend(budget)
        kind = field["type"]
        if kind in self.messages:
            return self._encode(kind, value, budget, depth + 1)
        if kind == "string":
            require(type(value) is str, "fixture-string")
            return value.encode("utf-8", errors="strict")
        if kind == "bytes":
            require(type(value) is bytes and len(value) <= MAXIMUM, "fixture-bytes")
            return value
        if kind == "bool":
            require(type(value) is bool, "fixture-boolean")
            return _varint(int(value))
        if kind == "uint64":
            require(type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,19}", value), "fixture-unsigned-decimal")
            return _varint(int(value))
        require(type(value) is int, "fixture-integer")
        if kind == "uint32":
            require(0 <= value < 2**32, "fixture-uint32")
        else:
            require((kind == "int32" or kind in self.enums) and -(2**31) <= value < 2**31, "fixture-enum-int32")
        return _varint(value if value >= 0 else 2**64 + value)

    def _encode(self, name, value, budget, depth):
        require(depth <= 16 and type(value) is dict, "fixture-message")
        fields = self.messages[name]
        require(set(value) <= {item["name"] for item in fields}, "fixture-unknown-field")
        self._spend(budget, len(fields) + 1)
        selected = set()
        output = bytearray()
        for field in sorted(fields, key=lambda item: item["number"]):
            if field["name"] not in value:
                continue
            item = value[field["name"]]
            require(item is not None, "fixture-absent-is-omitted")
            if field.get("oneof"):
                require(field["oneof"] not in selected, "fixture-oneof")
                selected.add(field["oneof"])
            if field.get("map"):
                require(type(item) is dict and len(item) <= 32, "fixture-map-bound")
                items = []
                for key, mapped in sorted(item.items()):
                    require(type(key) is str, "fixture-map-key")
                    key_bytes = key.encode("utf-8", errors="strict")
                    encoded = self._scalar(field, mapped, budget, depth)
                    items.append(b"\x0a" + _varint(len(key_bytes)) + key_bytes + _varint(16 | self._kind({**field, "map": False})) +
                                 (_varint(len(encoded)) if self._kind({**field, "map": False}) == 2 else b"") + encoded)
            elif field.get("repeated"):
                require(type(item) is list and len(item) <= (256 if field["name"] == "required_record_ids" else 128), "fixture-list-bound")
                items = [self._scalar(field, entry, budget, depth) for entry in item]
            else:
                items = [self._scalar(field, item, budget, depth)]
            for encoded in items:
                wire = self._kind(field)
                output += _varint(field["number"] * 8 | wire)
                if wire == 2:
                    output += _varint(len(encoded))
                output += encoded
                require(len(output) <= MAXIMUM, "fixture-wire-bound")
        return bytes(output)

    def encode(self, name, value):
        require(name in self.messages, "fixture-message-name")
        return self._encode(name, value, [8192], 0)

    def _default(self, field):
        kind = field["type"]
        if field.get("map"):
            return {}
        if field.get("repeated"):
            return []
        return {"uint64": "0", "string": "", "bytes": b"", "bool": False}.get(kind, 0)

    def _decoded(self, field, data, budget, depth):
        kind = field["type"]
        if kind in self.messages:
            return self._decode(kind, data, budget, depth + 1)
        if kind == "string":
            try:
                return data.decode("utf-8", errors="strict")
            except UnicodeError:
                raise FixtureError("fixture-utf8") from None
        if kind == "bytes":
            return data
        if kind == "bool":
            require(data < 2, "fixture-boolean")
            return bool(data)
        if kind == "uint64":
            return str(data)
        if kind == "uint32":
            require(data < 2**32, "fixture-uint32")
            return data
        value = data if data < 2**63 else data - 2**64
        require(-(2**31) <= value < 2**31, "fixture-enum-int32")
        return value

    def _decode(self, name, data, budget, depth):
        require(type(data) is bytes and len(data) <= MAXIMUM and depth <= 16, "fixture-wire-bound")
        fields = {field["number"]: field for field in self.messages[name]}
        self._spend(budget, 1 + len(fields))
        result = {field["name"]: self._default(field) for field in fields.values()
                  if (not field.get("optional") and field["type"] not in self.messages)
                  or field.get("repeated") or field.get("map")}
        present, selected = set(), set()
        offset = 0
        while offset < len(data):
            tag, offset = _consume(data, offset)
            require(tag // 8 in fields, "fixture-unknown-field")
            field = fields[tag // 8]
            expected = self._kind(field)
            packed = field.get("repeated") and expected == 0 and tag & 7 == 2
            require(tag & 7 == expected or packed, "fixture-field-kind")
            self._spend(budget)
            if not field.get("repeated") and not field.get("map"):
                require(field["number"] not in present, "fixture-duplicate-field")
                present.add(field["number"])
            if field.get("oneof"):
                require(field["oneof"] not in selected, "fixture-oneof")
                selected.add(field["oneof"])
            value, offset = _consume(data, offset)
            if tag & 7 == 2:
                require(value <= len(data) - offset, "fixture-truncated-message")
                content = data[offset:offset + value]
                offset += value
            else:
                content = value
            if field.get("map"):
                # All maintained legacy map values are strings.
                require(field["type"] == "string" and type(content) is bytes, "fixture-map-kind")
                key, mapped, cursor = "", "", 0
                seen = set()
                while cursor < len(content):
                    entry, cursor = _consume(content, cursor)
                    require(entry in (10, 18) and entry not in seen, "fixture-map-entry")
                    seen.add(entry)
                    size, cursor = _consume(content, cursor)
                    require(size <= len(content) - cursor, "fixture-truncated-message")
                    text = self._decoded({"type": "string"}, content[cursor:cursor + size], budget, depth)
                    cursor += size
                    if entry == 10:
                        key = text
                    else:
                        mapped = text
                require(key not in result[field["name"]] and len(result[field["name"]]) < 32, "fixture-map-bound")
                result[field["name"]][key] = mapped
            elif packed:
                cursor = 0
                while cursor < len(content):
                    item, cursor = _consume(content, cursor)
                    self._spend(budget)
                    result[field["name"]].append(self._decoded(field, item, budget, depth))
            else:
                item = self._decoded(field, content, budget, depth)
                if field.get("repeated"):
                    result[field["name"]].append(item)
                else:
                    result[field["name"]] = item
            if field.get("repeated"):
                require(len(result[field["name"]]) <= (256 if field["name"] == "required_record_ids" else 128), "fixture-list-bound")
        return result

    def decode(self, name, data):
        require(name in self.messages, "fixture-message-name")
        return self._decode(name, data, [8192], 0)


def private_read(path, maximum):
    require(path.is_absolute(), "fixture-absolute-path")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        information = os.fstat(fd)
        require(stat.S_ISREG(information.st_mode) and not path.is_symlink() and information.st_size <= maximum
                and information.st_mode & 0o077 == 0, "fixture-private-file")
        if hasattr(os, "geteuid"):
            require(information.st_uid == os.geteuid(), "fixture-file-owner")
        value = bytearray()
        while len(value) <= maximum:
            chunk = os.read(fd, min(65536, maximum + 1 - len(value)))
            if not chunk:
                break
            value.extend(chunk)
        require(len(value) == information.st_size and len(value) <= maximum, "fixture-file-bound")
        return bytes(value)
    finally:
        os.close(fd)


def private_write(path, value):
    require(path.is_absolute() and type(value) is bytes and len(value) <= MAXIMUM, "fixture-write-bound")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as output:
            output.write(value)
            output.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


class Participant:
    """One finite actual client process with one channel and positive group custody."""

    def __init__(self, language, command, endpoint, tenant, credential_file, directory, environment, cancellation, deadline):
        require(os.name == "posix" and language in LANGUAGES and isinstance(directory, Path)
                and directory.is_absolute() and not directory.exists(), "fixture-process-input")
        require(type(deadline) in (int, float) and math.isfinite(deadline) and time.monotonic() < deadline <= time.monotonic() + 120,
                "fixture-original-deadline")
        # Validate the secret without returning, hashing or recording it.
        credential = private_read(credential_file, 256)
        require(re.fullmatch(rb"[A-Za-z0-9_-]{32,256}", credential), "fixture-credential-shape")
        del credential
        directory.mkdir(mode=0o700)
        self.directory, self.language, self.deadline = directory, language, deadline
        self.cancellation, self.owner = cancellation, OwnedProcess()
        self.contract, self.calls, self.closed = Contract(), {}, False
        self.stdout, self.stderr, self.total = bytearray(), bytearray(), 0
        try:
            with cancellation.defer():
                self.owner.spawn([*command, "--node-fixture", endpoint, tenant, str(credential_file), str(directory)],
                                 ROOT, environment, min(deadline, time.monotonic() + 10), stdin=subprocess.PIPE)
                os.set_blocking(self.owner.process.stdout.fileno(), False)
                os.set_blocking(self.owner.process.stderr.fileno(), False)
            require(self._line(min(deadline, time.monotonic() + 10)) == b"ready", "fixture-client-startup")
        except BaseException:
            self.close()
            raise

    def _drain(self):
        self.cancellation.check()
        for stream, destination in ((self.owner.process.stdout, self.stdout), (self.owner.process.stderr, self.stderr)):
            try:
                value = os.read(stream.fileno(), 4097)
            except BlockingIOError:
                continue
            self.total += len(value)
            require(self.total <= 16384, "fixture-process-output-bound")
            destination.extend(value)

    def _line(self, deadline):
        while time.monotonic() < deadline:
            self._drain()
            if b"\n" in self.stdout:
                line, _, remaining = self.stdout.partition(b"\n")
                self.stdout = bytearray(remaining)
                require(len(line) <= 192, "fixture-command-bound")
                return bytes(line)
            require(not self.owner.exited(), "fixture-client-exited")
            time.sleep(0.005)
        raise FixtureError("fixture-client-deadline")

    def call(self, operation, identity, request, *, timeout_millis=5000, cancel_millis=-1):
        require(not self.closed and operation in self.contract.operations and IDENTIFIER.fullmatch(identity)
                and identity not in self.calls and len(self.calls) < MAXIMUM_CALLS, "fixture-call-input")
        require(type(timeout_millis) is int and 1 <= timeout_millis <= 5000 and type(cancel_millis) is int and -1 <= cancel_millis <= 5000,
                "fixture-call-deadline")
        require(time.monotonic() < self.deadline, "fixture-original-deadline")
        shape = self.contract.operations[operation]
        original = self.contract.encode(shape["request"], request)
        private_write(self.directory / (identity + ".request.pb"), original)
        self.calls[identity] = {"operation": operation, "requestSha256": hashlib.sha256(original).hexdigest()}
        line = f"{operation} {identity} {timeout_millis} {cancel_millis}\n".encode("ascii")
        self.owner.process.stdin.write(line)
        self.owner.process.stdin.flush()
        require(self._line(min(self.deadline, time.monotonic() + 10)) == b"done " + identity.encode("ascii"), "fixture-response-identity")
        result_bytes = private_read(self.directory / (identity + ".result.json"), 4096)
        summary = json.loads(result_bytes)
        require(type(summary) is dict and summary.get("status") in ("response", "failure", "local-cancelled"), "fixture-response-status")
        allowed = {"status"} if summary["status"] != "failure" else {"status", "failureCategory", "grpcStatus", "dispatched"}
        require(set(summary) == allowed, "fixture-response-closed")
        if summary["status"] == "failure":
            require(type(summary["failureCategory"]) is int and 0 <= summary["failureCategory"] <= 7
                    and (summary["grpcStatus"] is None or type(summary["grpcStatus"]) is int and 0 <= summary["grpcStatus"] <= 16)
                    and type(summary["dispatched"]) is bool, "fixture-response-failure")
        response = None
        if summary["status"] == "response":
            encoded = private_read(self.directory / (identity + ".response.pb"), MAXIMUM)
            response = self.contract.decode(shape["response"], encoded)
            self.calls[identity]["responseSha256"] = hashlib.sha256(encoded).hexdigest()
        observed = {}
        for kind, name in OBSERVATIONS.items():
            path = self.directory / (identity + "." + kind + ".pb")
            if path.exists():
                encoded = private_read(path, MAXIMUM)
                observed[kind] = self.contract.decode(name, encoded)
                self.calls[identity][kind + "Sha256"] = hashlib.sha256(encoded).hexdigest()
        require(private_read(self.directory / (identity + ".request.pb"), MAXIMUM) == original, "fixture-original-request-mutated")
        self.calls[identity]["result"] = summary
        return {"result": summary, "response": response, "observed": observed}

    def finish(self):
        require(not self.closed, "fixture-owner-closed")
        self.owner.process.stdin.write(b"close\n")
        self.owner.process.stdin.close()
        deadline = min(self.deadline + 10, time.monotonic() + 10)
        while not self.owner.exited():
            self._drain()
            require(time.monotonic() < deadline, "fixture-client-cleanup-deadline")
            time.sleep(0.005)
        with self.cancellation.defer():
            self.owner.finish(deadline)
        self._drain()
        require(self.owner.process.returncode == 0, "fixture-client-exit")
        cleanup = json.loads(private_read(self.directory / "cleanup.json", 4096))
        require(type(cleanup) is dict and cleanup.get("schemaVersion") == "latent.sdk.transaction.node.cleanup.v1"
                and cleanup.get("clean") is True, "fixture-client-cleanup-unconfirmed")
        self.close()
        return {"language": self.language, "calls": copy.deepcopy(self.calls), "clientCleanup": cleanup,
                "processReaped": True, "evidenceKind": "actual-prepared-sdk-process",
                "standaloneCampaignComplete": False}

    def close(self):
        if self.closed:
            return
        completed = False
        try:
            with self.cancellation.defer():
                if self.owner.process is not None:
                    try:
                        if self.owner.process.stdin is not None:
                            self.owner.process.stdin.close()
                    finally:
                        self.owner.finish(time.monotonic() + 5)
                self.owner.close()
                completed = True
        finally:
            # Retain the original owner after unconfirmed physical cleanup.
            self.closed = completed


def lookup_request(original, authorization_publication):
    """Use the same original command key; current read publication is separate."""
    require(type(original) is dict and "command" in original and "profile" in original, "fixture-original-command")
    return {"profile": copy.deepcopy(original["profile"]), "command": copy.deepcopy(original["command"]),
            "authorization_publication": copy.deepcopy(authorization_publication)}


def explicit_retry_request(original, inspection, retry_request_id):
    """Copy an actual durable aborted inspection; the host still proves retirement."""
    require(type(inspection) is dict and inspection.get("outcome") == 4 and inspection.get("metadata_durable") is True
            and inspection.get("application_state_committed") is False and type(inspection.get("proven_abort")) is dict,
            "fixture-retry-needs-durable-abort")
    require(type(retry_request_id) is str and IDENTIFIER.fullmatch(retry_request_id), "fixture-retry-identity")
    fence = inspection["proven_abort"]
    require(fence.get("command_id") == inspection.get("command_id") and fence.get("attempt_id") == inspection.get("attempt_id")
            and type(fence.get("transaction_id")) is str and fence["transaction_id"]
            and type(fence.get("owner_fence")) is bytes and len(fence["owner_fence"]) == 32, "fixture-retry-original-fence")
    result = copy.deepcopy(original)
    require("retry_attempt" not in result, "fixture-retry-original-request")
    result["retry_attempt"] = {"expected_abort": copy.deepcopy(fence), "request_id": retry_request_id}
    return result
