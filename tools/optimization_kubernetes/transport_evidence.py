"""Offline replay of the closed main Kubernetes/owned-worker API journal.

Transport integrity does not qualify a workload. The outer replay must consume
every operation against its declared Pod, Service, file, and lifecycle schedule.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import urlencode

from tools.optimization_docker.engine import API_VERSION
from tools.optimization_evidence.common import (
    EvidenceError, decode, digest, fields, integer, require, sha256, text, uint, unique_object,
)
from .transport import cleanup_log_warning

MAX_BYTES = 256 * 1024**2
MAX_ROWS = 20_000
MAX_LINE_BYTES = 48 * 1024**2
MAX_RESPONSE = 8 * 1024**2
MAX_TRANSFER = 40 * 1024**2
HTTP_FIELDS = ("method path begin_nanos end_nanos status request_bytes request_sha256 response_bytes "
               "response_sha256 response_complete connection_closed failure")
SMOKE03_JOURNAL_SHA256 = "sha256:3e7bb1dca8517d7bba56bf444c65f108a75412574db8c8b633c48a842e96c36b"
SMOKE03_CLEANUP_OWNER = {"namespace": "lsf-112-8c22b65b1529-smoke-03", "pod_name": "p0-g5-native-27",
    "pod_uid": "ebd99f76-bb98-49b5-bc53-e201eddba370", "container_name": "native",
    "container_id": "a60882dd6e5b3de7de7b99c5a1faf1b9f1885b50fda5efb466e39606298405fb"}


def _wire(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def _id(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "kubernetes-journal-container-id")
    return value


def _blob(value, maximum=MAX_RESPONSE):
    fields(value, "bytes sha256 base64")
    size = uint(value["bytes"])
    require(size <= maximum, "kubernetes-journal-blob-bound")
    checksum = digest(value["sha256"])
    encoded = value["base64"]
    require(isinstance(encoded, str) and len(encoded) == 4 * ((size + 2) // 3), "kubernetes-journal-base64-bound")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise EvidenceError("kubernetes-journal-base64") from error
    require(len(data) == size and base64.b64encode(data).decode("ascii") == encoded and sha256(data) == checksum,
            "kubernetes-journal-blob-identity")
    return data


def _window(started, finished, lower, upper):
    start, end = uint(started), uint(finished)
    require(lower <= start <= end <= upper, "kubernetes-journal-clock")
    return start, end


def _http(value, *, method, path, status, request, response, lower, upper, download=False):
    fields(value, HTTP_FIELDS + (" destination file_closed archive_stat_header" if download else ""))
    start, end = _window(value["begin_nanos"], value["end_nanos"], lower, upper)
    require(value["method"] == method and value["path"] == path
            and integer(value["status"], 100, 599) == status and value["response_complete"] is True
            and value["connection_closed"] is True and value["failure"] is None,
            "kubernetes-journal-http")
    for name, expected in (("request", request), ("response", response)):
        count, checksum = uint(value[name + "_bytes"]), digest(value[name + "_sha256"])
        if isinstance(expected, bytes):
            require(count == len(expected) and checksum == sha256(expected), "kubernetes-journal-http-body")
        else:
            fields(expected, "bytes sha256")
            require(count == uint(expected["bytes"]) and checksum == digest(expected["sha256"]),
                    "kubernetes-journal-http-artifact")
    if download:
        require(value["file_closed"] is True, "kubernetes-journal-download-open")
        text(value["destination"], 4096)
    return start, end


def _multiplexed(data):
    stdout, stderr, offset = bytearray(), bytearray(), 0
    while offset < len(data):
        require(offset + 8 <= len(data), "kubernetes-journal-exec-header")
        header = data[offset:offset + 8]
        length = int.from_bytes(header[4:], "big")
        require(header[0] in (1, 2) and header[1:4] == b"\0\0\0"
                and length <= MAX_RESPONSE and offset + 8 + length <= len(data), "kubernetes-journal-exec-frame")
        (stdout if header[0] == 1 else stderr).extend(data[offset + 8:offset + 8 + length])
        offset += 8 + length
    return bytes(stdout), bytes(stderr)


def _owned_path(value, owner, *, root_allowed=False):
    value = text(value, 4096)
    path = PurePosixPath(value)
    root = PurePosixPath("/var/local/lsf112") / owner
    require(path.is_absolute() and path.as_posix() == value and ".." not in path.parts
            and "\\" not in value and path.is_relative_to(root) and (root_allowed or path != root),
            "kubernetes-journal-owned-path")
    return value


def _inventory(value):
    fields(value, "entries bytes")
    entries = value["entries"]
    require(isinstance(entries, list) and 1 <= len(entries) <= 512, "kubernetes-journal-inventory-bound")
    seen, total, previous = set(), 0, None
    for row in entries:
        fields(row, "path kind mode", "bytes sha256")
        name = text(row["path"], 4096)
        path = PurePosixPath(name)
        require(path.as_posix() == name and not path.is_absolute() and ".." not in path.parts
                and "\\" not in name and len(path.parts) <= 9 and name.casefold() not in seen
                and (previous is None or name > previous), "kubernetes-journal-inventory-path")
        require(isinstance(row["mode"], str) and re.fullmatch(r"[0-7]{4}", row["mode"]),
                "kubernetes-journal-inventory-mode")
        if row["kind"] == "directory":
            fields(row, "path kind mode")
        else:
            fields(row, "path kind mode bytes sha256")
            require(row["kind"] == "file" and name != ".", "kubernetes-journal-inventory-type")
            total += uint(row["bytes"])
            digest(row["sha256"])
        seen.add(name.casefold())
        previous = name
    require(entries[0]["path"] == "." and entries[0]["kind"] == "directory"
            and total == uint(value["bytes"]) <= MAX_TRANSFER, "kubernetes-journal-inventory-total")
    return value


def _kubernetes(row, lower, upper):
    fields(row, "ordinal provider method path request response status started_nanos finished_nanos response_complete "
                "connection_closed json_response failure timeout_seconds expected_statuses")
    start, end = _window(row["started_nanos"], row["finished_nanos"], lower, upper)
    method, path = row["method"], text(row["path"], 16384)
    require(method in ("GET", "POST", "DELETE") and path.startswith("/") and not path.startswith("//")
            and all(33 <= ord(char) <= 126 for char in path), "kubernetes-journal-api-path")
    status = integer(row["status"], 100, 599)
    integer(row["timeout_seconds"], 1, 60)
    expected = row["expected_statuses"]
    allowed = {"GET": (200, 404), "POST": (200, 201), "DELETE": (200, 202, 404)}[method]
    require(isinstance(expected, list) and 1 <= len(expected) <= len(allowed)
            and all(type(item) is int and item in allowed for item in expected) and len(set(expected)) == len(expected)
            and status in expected, "kubernetes-journal-api-declaration")
    require(status in allowed
            and row["response_complete"] is True and row["connection_closed"] is True
            and row["failure"] is None and type(row["json_response"]) is bool, "kubernetes-journal-api-outcome")
    request, response = _blob(row["request"]), _blob(row["response"])
    request_json = decode(request, MAX_RESPONSE) if request else None
    require((method != "GET" or not request) and (method != "POST" or isinstance(request_json, dict))
            and (not request or isinstance(request_json, dict) and _wire(request_json) == request),
            "kubernetes-journal-api-request")
    response_json = decode(response, MAX_RESPONSE) if response and row["json_response"] else None
    if not row["json_response"]:
        require(method == "GET" and path.split("?", 1)[0].endswith("/log") and status == 200,
                "kubernetes-journal-text-endpoint")
    else:
        require(isinstance(response_json, dict), "kubernetes-journal-json-response")
        if response_json.get("kind") == "Status" and response_json.get("status") == "Failure":
            require(status == 404 and response_json.get("reason") == "NotFound"
                    and type(response_json.get("code")) is int and response_json["code"] == 404,
                    "kubernetes-journal-hidden-api-failure")
        if status == 404:
            require(response_json.get("kind") == "Status" and response_json.get("status") == "Failure"
                    and response_json.get("reason") == "NotFound" and response_json.get("code") == 404,
                    "kubernetes-journal-absence-response")
    return {"request_bytes": request, "response_bytes": response, "request_json": request_json,
            "response_json": response_json}, start, end


def _identity(row, container, lower, upper):
    fields(row, "ordinal provider operation response receipt")
    response = _blob(row["response"])
    start, end = _http(row["receipt"], method="GET", path=f"/v{API_VERSION}/containers/{container}/json", status=200,
                       request=b"", response=response, lower=lower, upper=upper)
    actual = decode(response, MAX_RESPONSE)
    require(isinstance(actual, dict) and actual.get("Id") == container, "kubernetes-journal-worker-identity")
    name = text(actual.get("Name"), 128)
    match = re.fullmatch(r"/(lsf-112-[a-f0-9]{12})-worker", name)
    require(match is not None, "kubernetes-journal-worker-name")
    owner = match[1]
    require(isinstance(actual.get("Config"), dict) and isinstance(actual["Config"].get("Labels"), dict)
            and isinstance(actual.get("State"), dict), "kubernetes-journal-worker-shape")
    labels = actual["Config"]["Labels"]
    require(labels.get("io.x-k8s.kind.cluster") == owner and labels.get("io.x-k8s.kind.role") == "worker"
            and actual.get("State", {}).get("Running") is True, "kubernetes-journal-worker-ownership")
    return {"response_bytes": response, "response_json": actual, "owner": owner}, start, end


def _node_stats(row, nodes, lower, upper):
    fields(row, "ordinal provider operation role container_id response receipt")
    require(nodes is not None and isinstance(row["role"], str) and row["role"] in nodes
            and row["container_id"] == nodes[row["role"]],
            "kubernetes-journal-node-stats-owner")
    container = row["container_id"]
    response = _blob(row["response"])
    start, end = _http(row["receipt"], method="GET",
        path=f"/v{API_VERSION}/containers/{container}/stats?stream=false&one-shot=true", status=200,
        request=b"", response=response, lower=lower, upper=upper)
    value = decode(response, MAX_RESPONSE)
    require(isinstance(value, dict) and value.get("id") == container, "kubernetes-journal-node-stats-id")
    return {"response_bytes": response, "response_json": value}, start, end


def _exec(row, container, lower, upper, *, owner=None, recovered_smoke03=False):
    fields(row, "ordinal provider operation container_id argv timeout_seconds started_nanos finished_nanos records failure"
           + (" cleanup_log_owner" if "cleanup_log_owner" in row else ""))
    policy = row.get("cleanup_log_owner")
    if recovered_smoke03:
        require(row["ordinal"] == 2641 and row["failure"] == "EvidenceError" and "cleanup_log_owner" not in row
                and owner == "lsf-112-8c22b65b1529", "kubernetes-journal-historical-cleanup-record")
        policy = SMOKE03_CLEANUP_OWNER
    else:
        require(row["failure"] is None, "kubernetes-journal-exec-owner")
    require(row["container_id"] == container and ("cleanup_log_owner" not in row or policy is not None),
            "kubernetes-journal-exec-owner")
    start, end = _window(row["started_nanos"], row["finished_nanos"], lower, upper)
    timeout = integer(row["timeout_seconds"], 1, 60)
    argv = row["argv"]
    require(isinstance(argv, list) and 1 <= len(argv) <= 64, "kubernetes-journal-exec-argv")
    for arg in argv:
        text(arg, 65536, empty=True)
        require(len(arg) <= 16384, "kubernetes-journal-exec-arg-bound")
    request = {"AttachStdin": False, "AttachStdout": True, "AttachStderr": True, "Tty": False, "Privileged": False,
               "Cmd": ["timeout", "--signal=TERM", "--kill-after=5s", str(timeout) + "s", *argv]}
    records = row["records"]
    require(isinstance(records, list) and len(records) == 3, "kubernetes-journal-exec-record-count")
    first, second, third = records
    fields(first, "request receipt response")
    require(_wire(first["request"]) == _wire(request), "kubernetes-journal-exec-request")
    created = _blob(first["response"])
    _, ready = _http(first["receipt"], method="POST", path=f"/v{API_VERSION}/containers/{container}/exec", status=201,
                     request=_wire(request), response=created, lower=start, upper=end)
    identity = fields(decode(created, MAX_RESPONSE), "Id")
    exec_id = _id(identity["Id"])
    fields(second, "request receipt response")
    command, output = _blob(second["request"]), _blob(second["response"])
    require(command == b'{"Detach":false,"Tty":false}', "kubernetes-journal-exec-start")
    _, returned = _http(second["receipt"], method="POST", path=f"/v{API_VERSION}/exec/{exec_id}/start", status=200,
                        request=command, response=output, lower=ready, upper=end)
    fields(third, "receipt response")
    final_bytes = _blob(third["response"])
    _http(third["receipt"], method="GET", path=f"/v{API_VERSION}/exec/{exec_id}/json", status=200,
          request=b"", response=final_bytes, lower=returned, upper=end)
    final = decode(final_bytes, MAX_RESPONSE)
    require(isinstance(final, dict) and final.get("ID") == exec_id and final.get("ContainerID") == container
            and final.get("Running") is False and type(final.get("ExitCode")) is int and final["ExitCode"] == 0,
            "kubernetes-journal-exec-not-reaped")
    stdout, stderr = _multiplexed(output)
    warning = None
    if policy is None:
        require(not stderr, "kubernetes-journal-exec-stderr")
    else:
        require(owner is not None, "kubernetes-journal-cleanup-log-owner")
        warning = cleanup_log_warning(argv, stdout, stderr, policy, worker_owner=owner)
    if recovered_smoke03:
        require(warning is not None, "kubernetes-journal-historical-cleanup-warning-missing")
    return {"request_json": request, "request_bytes": _wire(request), "response_bytes": output,
            "stdout": stdout, "stderr": stderr, "exec_id": exec_id, "final_inspect": final,
            **({"cleanup_log_owner": dict(policy), "cleanup_log_warning": warning} if policy is not None else {}),
            **({"recovered_failure": row["failure"]} if recovered_smoke03 else {})}, start, end


def _upload(row, container, owner, lower, upper):
    fields(row, "ordinal provider operation container_id destination archive response receipt failure")
    require(row["container_id"] == container and row["failure"] is None, "kubernetes-journal-upload-owner")
    destination = _owned_path(row["destination"], owner, root_allowed=True)
    archive = fields(row["archive"], "bytes sha256")
    require(0 < uint(archive["bytes"]) <= MAX_TRANSFER, "kubernetes-journal-upload-bound")
    digest(archive["sha256"])
    response = _blob(row["response"])
    path = f"/v{API_VERSION}/containers/{container}/archive?" + urlencode({"path": destination, "noOverwriteDirNonDir": "1"})
    start, end = _http(row["receipt"], method="PUT", path=path, status=200, request=archive, response=response,
                       lower=lower, upper=upper)
    require(not response, "kubernetes-journal-upload-response")
    return {"response_bytes": response, "archive": archive}, start, end


def _download(row, container, owner, lower, upper):
    fields(row, "ordinal provider operation container_id source_path started_nanos finished_nanos receipt inventory "
                "archive_sha256 failure")
    require(row["container_id"] == container and row["failure"] is None, "kubernetes-journal-download-owner")
    start, end = _window(row["started_nanos"], row["finished_nanos"], lower, upper)
    source = _owned_path(row["source_path"], owner)
    receipt = fields(row["receipt"], HTTP_FIELDS + " destination file_closed archive_stat_header")
    archive = {"bytes": receipt["response_bytes"], "sha256": digest(row["archive_sha256"])}
    require(0 < uint(archive["bytes"]) <= MAX_TRANSFER, "kubernetes-journal-download-bound")
    path = f"/v{API_VERSION}/containers/{container}/archive?" + urlencode({"path": source})
    _http(receipt, method="GET", path=path, status=200, request=b"", response=archive,
          lower=start, upper=end, download=True)
    header = text(receipt["archive_stat_header"], 65536)
    try:
        header_bytes = base64.b64decode(header, validate=True)
    except (ValueError, binascii.Error) as error:
        raise EvidenceError("kubernetes-journal-archive-header") from error
    require(base64.b64encode(header_bytes).decode("ascii") == header, "kubernetes-journal-archive-header")
    entry = fields(decode(header_bytes, 65536), "name size mode mtime linkTarget")
    require(entry["name"] == PurePosixPath(source).name and integer(entry["mode"]) & 0x80000000
            and not integer(entry["mode"]) & 0x08000000 and entry["linkTarget"] == "",
            "kubernetes-journal-archive-root")
    integer(entry["size"], 0, 2**64 - 1)
    text(entry["mtime"], 128)
    return {"archive": archive, "archive_stat": entry, "inventory": _inventory(row["inventory"])}, start, end


def _line(data):
    # Base64 values can exceed the general JSON helper's text-field cap. The
    # enclosing line and each decoded blob have separate explicit finite bounds.
    try:
        value = json.loads(data, object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(EvidenceError("invalid-json-number")))
        pending, nodes = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            require(nodes <= 8192 and depth <= 32, "kubernetes-journal-json-structure")
            if isinstance(item, dict):
                require(len(item) <= 1024, "kubernetes-journal-json-object")
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                require(len(item) <= 1024, "kubernetes-journal-json-array")
                pending.extend((child, depth + 1) for child in item)
        require(isinstance(value, dict) and _wire(value) + b"\n" == data, "kubernetes-journal-original-framing")
        return value
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise EvidenceError("kubernetes-journal-json") from error


def validate(path: Path, *, worker_container_id: str, started_nanos: str, finished_nanos: str,
             node_container_ids: dict | None = None, recovered_smoke03_cleanup=False) -> dict:
    """Verify original bytes and successful transport; never execute their source."""
    container = _id(worker_container_id)
    require(type(recovered_smoke03_cleanup) is bool, "kubernetes-journal-recovered-cleanup-policy")
    if node_container_ids is not None:
        fields(node_container_ids, "control-plane worker")
        nodes = {role: _id(value) for role, value in node_container_ids.items()}
        require(nodes["worker"] == container and len(set(nodes.values())) == 2, "kubernetes-journal-node-map")
    else:
        nodes = None
    lower, upper = uint(started_nanos), uint(finished_nanos)
    require(lower <= upper, "kubernetes-journal-campaign-clock")
    rows, total, hasher, owner, previous = [], 0, hashlib.sha256(), None, lower
    try:
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and not path.is_symlink()
                and not getattr(before, "st_file_attributes", 0) & 0x400 and 0 < before.st_size <= MAX_BYTES,
                "kubernetes-journal-file-bound")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), "kubernetes-journal-file-crossed")
            while data := stream.readline(MAX_LINE_BYTES + 1):
                total += len(data)
                require(len(rows) < MAX_ROWS and len(data) <= MAX_LINE_BYTES and data.endswith(b"\n")
                        and total <= MAX_BYTES, "kubernetes-journal-framing-bound")
                hasher.update(data)
                row = _line(data)
                require(integer(row.get("ordinal")) == len(rows), "kubernetes-journal-ordinal")
                if row.get("provider") == "kubernetes":
                    derived, start, end = _kubernetes(row, previous, upper)
                else:
                    require(row.get("provider") == "docker", "kubernetes-journal-provider")
                    operation = row.get("operation")
                    if operation == "worker-identity":
                        require(owner is None, "kubernetes-journal-duplicate-worker")
                        derived, start, end = _identity(row, container, previous, upper)
                        owner = derived["owner"]
                    else:
                        require(owner is not None, "kubernetes-journal-worker-not-bound")
                        if operation == "worker-exec":
                            derived, start, end = _exec(row, container, previous, upper, owner=owner,
                                recovered_smoke03=recovered_smoke03_cleanup and row["ordinal"] == 2641)
                        elif operation == "worker-upload":
                            derived, start, end = _upload(row, container, owner, previous, upper)
                        elif operation == "node-stats":
                            derived, start, end = _node_stats(row, nodes, previous, upper)
                        else:
                            require(operation == "worker-download", "kubernetes-journal-operation")
                            derived, start, end = _download(row, container, owner, previous, upper)
                rows.append({"raw": row, "started_nanos": str(start), "finished_nanos": str(end), **derived})
                previous = end
            after = os.fstat(stream.fileno())
        closed = path.lstat()
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        require(identity(before) == identity(opened) == identity(after) == identity(closed)
                and total == before.st_size and owner is not None, "kubernetes-journal-file-changed")
    except OSError as error:
        raise EvidenceError("kubernetes-journal-file-unreadable") from error
    checksum = "sha256:" + hasher.hexdigest()
    recovered = {}
    if recovered_smoke03_cleanup:
        require(checksum == SMOKE03_JOURNAL_SHA256 and total == 32909467 and len(rows) == 2642
                and rows[-1].get("recovered_failure") == "EvidenceError",
                "kubernetes-journal-historical-cleanup-byte-identity")
        recovered = {"recovered_cleanup": {"ordinal": 2641, "original_failure": "EvidenceError",
            "warning": rows[-1]["cleanup_log_warning"], "requires_separate_final_absence_proof": True}}
    return {"bytes": str(total), "sha256": checksum, "rows": rows, **recovered}


def get(result, ordinal, *, provider, operation=None, method=None, path=None, argv=None,
        status=None, timeout_seconds=None, expected_statuses=None, role=None):
    """Select a verified original call and bind the outer replay's expectations."""
    rows = result["rows"]
    index = integer(ordinal, 0, len(rows) - 1)
    selected, raw = rows[index], rows[index]["raw"]
    require(raw["provider"] == provider, "kubernetes-journal-selected-provider")
    for name, expected in (("operation", operation), ("method", method), ("path", path), ("argv", argv),
                           ("status", status), ("timeout_seconds", timeout_seconds),
                           ("expected_statuses", expected_statuses), ("role", role)):
        if expected is not None:
            require(raw.get(name) == expected, "kubernetes-journal-selected-" + name)
    return selected
