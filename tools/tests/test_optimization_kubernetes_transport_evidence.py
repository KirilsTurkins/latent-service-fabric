"""Synthetic journal protocol fixtures, never Kubernetes or measurement claims."""
from copy import deepcopy
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.optimization_evidence.common import EvidenceError, sha256
from tools.optimization_kubernetes import transport_evidence as evidence

CONTAINER = "a" * 64
EXEC = "b" * 64
OWNER = "lsf-112-123456abcdef"


def wire(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def blob(value):
    return {"bytes": str(len(value)), "sha256": sha256(value), "base64": base64.b64encode(value).decode()}


def http(method, path, status, request, response, start):
    return {"method": method, "path": path, "begin_nanos": str(start), "end_nanos": str(start + 1),
            "status": status, "request_bytes": str(len(request)), "request_sha256": sha256(request),
            "response_bytes": str(len(response)), "response_sha256": sha256(response),
            "response_complete": True, "connection_closed": True, "failure": None}


def framed(value, channel=1):
    return bytes([channel, 0, 0, 0]) + len(value).to_bytes(4, "big") + value


def kube(method, path, status, request, response, start, json_response=True):
    return {"provider": "kubernetes", "method": method, "path": path, "status": status,
            "request": blob(b"" if request is None else wire(request)), "response": blob(response),
            "started_nanos": str(start), "finished_nanos": str(start + 1), "response_complete": True,
            "connection_closed": True, "json_response": json_response, "failure": None,
            "timeout_seconds": 15, "expected_statuses": [status]}


def protocol():
    identity = {"Id": CONTAINER, "Name": "/" + OWNER + "-worker", "Config": {"Labels": {
        "io.x-k8s.kind.cluster": OWNER, "io.x-k8s.kind.role": "worker"}}, "State": {"Running": True}}
    identity_body = wire(identity)
    rows = [{"provider": "docker", "operation": "worker-identity", "response": blob(identity_body),
             "receipt": http("GET", f"/v1.54/containers/{CONTAINER}/json", 200, b"", identity_body, 10)}]
    rows.append(kube("POST", "/api/v1/namespaces", 201, {"kind": "Namespace", "metadata": {"name": "unit"}},
                     b'{ "kind": "Namespace", "metadata": {"uid":"unit-uid"} }\n', 12))
    argv = ["cat", "/proc/500/stat"]
    request = {"AttachStdin": False, "AttachStdout": True, "AttachStderr": True, "Tty": False, "Privileged": False,
               "Cmd": ["timeout", "--signal=TERM", "--kill-after=5s", "20s", *argv]}
    created = wire({"Id": EXEC})
    started = b'{"Detach":false,"Tty":false}'
    result = framed(b"original ") + framed(b"stdout\n")
    final = wire({"ID": EXEC, "ContainerID": CONTAINER, "Running": False, "ExitCode": 0, "Pid": 0})
    rows.append({"provider": "docker", "operation": "worker-exec", "container_id": CONTAINER, "argv": argv,
        "timeout_seconds": 20, "started_nanos": "14", "finished_nanos": "21", "failure": None,
        "records": [{"request": request, "response": blob(created),
                     "receipt": http("POST", f"/v1.54/containers/{CONTAINER}/exec", 201, wire(request), created, 15)},
                    {"request": blob(started), "response": blob(result),
                     "receipt": http("POST", f"/v1.54/exec/{EXEC}/start", 200, started, result, 17)},
                    {"response": blob(final), "receipt": http("GET", f"/v1.54/exec/{EXEC}/json", 200, b"", final, 19)}]})
    remote = "/var/local/lsf112/" + OWNER + "/run/output"
    archive = b"unit opaque archive bound by the outer retained-file closure"
    upload_path = f"/v1.54/containers/{CONTAINER}/archive?" + evidence.urlencode({"path": remote, "noOverwriteDirNonDir": "1"})
    rows.append({"provider": "docker", "operation": "worker-upload", "container_id": CONTAINER,
                 "destination": remote, "archive": {"bytes": str(len(archive)), "sha256": sha256(archive)},
                 "response": blob(b""), "receipt": http("PUT", upload_path, 200, archive, b"", 22), "failure": None})
    download_path = f"/v1.54/containers/{CONTAINER}/archive?" + evidence.urlencode({"path": remote})
    receipt = http("GET", download_path, 200, b"", archive, 25)
    receipt.update(destination="/bench/unit/download.tar", file_closed=True,
        archive_stat_header=base64.b64encode(wire({"name": "output", "size": 4096, "mode": 0x800001ED,
            "mtime": "2026-09-11T00:00:00Z", "linkTarget": ""})).decode())
    rows.append({"provider": "docker", "operation": "worker-download", "container_id": CONTAINER,
        "source_path": remote, "started_nanos": "24", "finished_nanos": "27", "receipt": receipt,
        "inventory": {"entries": [{"path": ".", "kind": "directory", "mode": "0755"},
                                  {"path": "value", "kind": "file", "mode": "0644", "bytes": "1", "sha256": sha256(b"x")}],
                      "bytes": "1"}, "archive_sha256": sha256(archive), "failure": None})
    rows.append(kube("GET", "/api/v1/namespaces/unit/pods/gone", 404, None,
        wire({"kind": "Status", "status": "Failure", "reason": "NotFound", "code": 404}), 28))
    rows.append(kube("GET", "/api/v1/namespaces/unit/pods/client/log", 200, None,
                     b'{"event":"ready"}\n', 30, json_response=False))
    return [{"ordinal": index, **row} for index, row in enumerate(rows)]


def response(record, value):
    record["response"] = blob(value)
    record["receipt"].update(response_bytes=str(len(value)), response_sha256=sha256(value))


class TransportEvidenceTests(unittest.TestCase):
    def validate(self, rows, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api.ndjson"
            data = b"".join(wire(row) + b"\n" for row in rows)
            path.write_bytes(data)
            result = evidence.validate(path, worker_container_id=CONTAINER, started_nanos="0", finished_nanos="100", **kwargs)
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual((result["bytes"], result["sha256"]), (str(len(data)), sha256(data)))
            return result

    def test_original_api_exec_and_transfer_bytes_are_available_to_outer_replay(self):
        result = self.validate(protocol())
        self.assertEqual(len(result["rows"]), 7)
        row = evidence.get(result, 2, provider="docker", operation="worker-exec", argv=["cat", "/proc/500/stat"])
        self.assertEqual(row["stdout"], b"original stdout\n")
        self.assertEqual(row["stderr"], b"")
        self.assertEqual(row["exec_id"], EXEC)
        self.assertFalse(row["final_inspect"]["Running"])
        pod = evidence.get(result, 1, provider="kubernetes", method="POST", path="/api/v1/namespaces")
        self.assertEqual(pod["response_json"]["metadata"]["uid"], "unit-uid")
        self.assertTrue(pod["response_bytes"].startswith(b'{ "kind"'))
        self.assertEqual(result["rows"][5]["response_json"]["code"], 404)
        self.assertIsNone(result["rows"][6]["response_json"])
        self.assertEqual(result["rows"][6]["response_bytes"], b'{"event":"ready"}\n')

    def test_blob_digest_length_and_noncanonical_base64_reject(self):
        self.reject((lambda rows: rows[1]["response"].update(sha256="sha256:" + "f" * 64),
                     lambda rows: rows[1]["response"].update(bytes="1"),
                     lambda rows: rows[1]["response"].update(base64=rows[1]["response"]["base64"] + "\n"),
                     lambda rows: rows[2]["records"][1]["receipt"].update(response_sha256="sha256:" + "f" * 64)))

    def test_main_journal_cannot_hide_failed_or_unclosed_operations(self):
        self.reject((lambda rows: rows[1].update(failure="TimeoutError"),
                     lambda rows: rows[1].update(response_complete=False),
                     lambda rows: rows[1].update(connection_closed=False),
                     lambda rows: rows[2]["records"][1]["receipt"].update(status=500),
                     lambda rows: rows[3].update(failure="OSError"),
                     lambda rows: rows[4].update(failure="ValueError")))

    def test_worker_exec_must_retain_exact_owned_three_step_protocol(self):
        self.reject((lambda rows: rows[2].update(container_id="c" * 64),
                     lambda rows: rows[2]["records"].pop(),
                     lambda rows: rows[2]["records"][0]["request"]["Cmd"].__setitem__(0, "sh"),
                     lambda rows: rows[2].update(timeout_seconds=61),
                     lambda rows: rows[2]["records"][1]["receipt"].update(path=f"/v1.54/exec/{'c' * 64}/start"),
                     lambda rows: rows[2]["records"][2]["receipt"].update(path=f"/v1.53/exec/{EXEC}/json")))

    def test_rehashed_exec_error_running_or_foreign_owner_still_rejects(self):
        for alteration in ({"ExitCode": 1}, {"ExitCode": True}, {"Running": True}, {"ContainerID": "c" * 64}):
            rows = protocol()
            record = rows[2]["records"][2]
            actual = json.loads(base64.b64decode(record["response"]["base64"]))
            response(record, wire({**actual, **alteration}))
            with self.subTest(alteration=alteration), self.assertRaises(EvidenceError):
                self.validate(rows)
        for value in (framed(b"warning", 2), b"\x01", b"\x01\0\0\0\0\0\0\x03no", framed(b"x", 3)):
            rows = protocol()
            response(rows[2]["records"][1], value)
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                self.validate(rows)

    def test_404_is_explicit_absence_not_permission_to_hide_other_api_errors(self):
        self.reject((lambda rows: rows[5].update(status=403),
                     lambda rows: rows[5].update(response=blob(wire({"kind": "Status", "status": "Failure", "reason": "Forbidden", "code": 404}))),
                     lambda rows: rows[5].update(status=200),
                     lambda rows: rows[6].update(path="/api/v1/nodes")))

    def test_api_timeout_and_expected_status_declarations_are_required_and_bounded(self):
        self.reject((lambda rows: rows[1].pop("timeout_seconds"),
                     lambda rows: rows[1].update(timeout_seconds=61),
                     lambda rows: rows[1].update(timeout_seconds=True),
                     lambda rows: rows[5].update(expected_statuses=[200]),
                     lambda rows: rows[5].update(expected_statuses=[200, 404, 500]),
                     lambda rows: rows[5].update(expected_statuses=[404, 404])))

    def test_node_stats_need_the_explicit_two_node_map_and_exact_role_id(self):
        rows = protocol()
        nodes = {"control-plane": "c" * 64, "worker": CONTAINER}
        for index, (role, container) in enumerate(nodes.items()):
            body = wire({"id": container, "read": "2026-09-11T00:00:00Z", "cpu_stats": {}})
            rows.append({"ordinal": len(rows), "provider": "docker", "operation": "node-stats", "role": role,
                "container_id": container, "response": blob(body), "receipt": http("GET",
                    f"/v1.54/containers/{container}/stats?stream=false&one-shot=true", 200, b"", body, 32 + index * 2)})
        result = self.validate(rows, node_container_ids=nodes)
        self.assertEqual(evidence.get(result, 7, provider="docker", operation="node-stats", role="control-plane")
                         ["response_json"]["id"], nodes["control-plane"])
        with self.assertRaises(EvidenceError):
            self.validate(rows)
        for selected in ({"worker": CONTAINER}, {"control-plane": CONTAINER, "worker": CONTAINER},
                         {"control-plane": "c" * 64, "worker": "d" * 64}):
            with self.subTest(selected=selected), self.assertRaises(EvidenceError):
                self.validate(rows, node_container_ids=selected)
        changed = deepcopy(rows)
        changed[7]["role"] = "worker"
        with self.assertRaises(EvidenceError):
            self.validate(changed, node_container_ids=nodes)

    def test_clock_ordinal_and_identity_reuse_reject(self):
        self.reject((lambda rows: rows[2].update(ordinal=1),
                     lambda rows: rows[2].update(started_nanos="1"),
                     lambda rows: rows[2]["records"][2]["receipt"].update(begin_nanos="15"),
                     lambda rows: rows[6].update(finished_nanos="101"),
                     lambda rows: rows.__setitem__(1, {**deepcopy(rows[0]), "ordinal": 1}),
                     lambda rows: rows[0].update(provider="unowned")))

    def test_transfer_path_header_and_artifact_binding_reject(self):
        self.reject((lambda rows: rows[3].update(destination="/var/local/lsf112/foreign/run/output"),
                     lambda rows: rows[3]["archive"].update(bytes="1"),
                     lambda rows: rows[4].update(archive_sha256="sha256:" + "f" * 64),
                     lambda rows: rows[4]["receipt"].update(file_closed=False),
                     lambda rows: rows[4]["receipt"].update(archive_stat_header=base64.b64encode(wire({
                         "name": "foreign", "size": 0, "mode": 0x800001ED, "mtime": "now", "linkTarget": ""})).decode()),
                     lambda rows: rows[4]["inventory"].update(bytes="2")))

    def test_selected_call_cannot_borrow_another_operation_or_command(self):
        result = self.validate(protocol())
        for kwargs in ({"provider": "kubernetes"}, {"provider": "docker", "operation": "worker-upload"},
                       {"provider": "docker", "argv": ["cat", "/proc/999/stat"]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(EvidenceError):
                evidence.get(result, 2, **kwargs)

    def test_strict_line_file_population_and_original_json_framing(self):
        rows = protocol()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal"
            data = b"".join(wire(row) + b"\n" for row in rows)
            for altered in (data[:-1], data + b"\n", data.replace(b'"ordinal":0', b'"ordinal":0,"ordinal":0', 1),
                            data.replace(b'"ordinal":0', b'"ordinal" :0', 1)):
                path.write_bytes(altered)
                with self.assertRaises(EvidenceError):
                    evidence.validate(path, worker_container_id=CONTAINER, started_nanos="0", finished_nanos="100")
            for constant, value in (("MAX_BYTES", len(data) - 1), ("MAX_ROWS", 6),
                                    ("MAX_LINE_BYTES", max(len(line) + 1 for line in data.splitlines()) - 1)):
                path.write_bytes(data)
                with patch.object(evidence, constant, value), self.assertRaises(EvidenceError):
                    evidence.validate(path, worker_container_id=CONTAINER, started_nanos="0", finished_nanos="100")

    def test_bounded_blob_can_exceed_generic_json_text_limit(self):
        rows = protocol()
        payload = b"x" * (1024**2 + 1)
        response(rows[2]["records"][1], framed(payload))
        self.assertEqual(self.validate(rows)["rows"][2]["stdout"], payload)

    def reject(self, changes):
        for change in changes:
            with self.subTest(change=change):
                rows = protocol()
                change(rows)
                with self.assertRaises(EvidenceError):
                    self.validate(rows)


if __name__ == "__main__":
    unittest.main()
