"""Original bootstrap metadata and finite mutation cases; no infrastructure calls."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.artifact_identity_runner.files import reference, write_json
from tools.optimization_evidence.common import sha256
from tools.optimization_kubernetes import bootstrap_evidence as evidence
from tools.optimization_kubernetes.transport import blob

FIXTURE = Path(__file__).parent / "fixtures/kubernetes-bootstrap-01"


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def changed_response(row, value):
    raw = wire(value)
    row["response"] = blob(raw)
    if "receipt" in row:
        row["receipt"].update(response_bytes=str(len(raw)), response_sha256=sha256(raw))


class OriginalBootstrapJournal(unittest.TestCase):
    def fixtures(self):
        boot = json.loads((FIXTURE / "bootstrap.json").read_bytes())
        rows = [json.loads(line) for line in (FIXTURE / "bootstrap.ndjson").read_bytes().splitlines()]
        return boot, rows

    def replay(self, boot, rows):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = b"".join(wire(row) + b"\n" for row in rows)
            (root / "bootstrap.ndjson").write_bytes(data)
            derived = evidence._journal(root, boot)
            evidence._bindings(boot, {"networks_before": []}, derived)
            self.assertEqual((root / "bootstrap.ndjson").read_bytes(), data)
            return derived

    def test_original_fourteen_operations_replay_without_keys_binaries_or_api(self):
        boot, rows = self.fixtures()
        with patch.object(evidence.bootstrap, "Engine", side_effect=AssertionError("offline only")), \
                patch.object(evidence.bootstrap, "source", side_effect=AssertionError("no Git/source execution")):
            observed = self.replay(boot, rows)
        self.assertEqual(len(observed), 14)
        self.assertEqual(observed[10]["stdout"].decode().strip().split(),
                         [boot["kubectl"]["file"]["sha256"][7:], "/usr/bin/kubectl"])
        self.assertFalse((FIXTURE / "private").exists())

    def test_rehashed_crossed_node_uid_alias_and_path_are_rejected(self):
        for change in ("node", "uid", "alias", "path", "extra"):
            with self.subTest(change=change):
                boot, rows = self.fixtures()
                if change == "node":
                    value = json.loads(evidence.transport._blob(rows[1]["response"]))
                    value["Id"] = "9" * 64
                    changed_response(rows[1], value)
                elif change == "uid":
                    value = json.loads(evidence.transport._blob(rows[11]["response"]))
                    value["items"][0]["metadata"]["uid"] = "wrong-same-node-name"
                    changed_response(rows[11], value)
                elif change == "alias":
                    rows[5]["request"]["EndpointConfig"]["Aliases"] = ["unrelated"]
                    encoded = wire(rows[5]["request"])
                    rows[5]["receipt"].update(request_bytes=str(len(encoded)), request_sha256=sha256(encoded))
                elif change == "path":
                    rows[1]["path"] = "/containers/" + "9" * 64 + "/json"
                    rows[1]["receipt"]["path"] = "/v1.54" + rows[1]["path"]
                else:
                    rows.append({**copy.deepcopy(rows[-1]), "ordinal": 14})
                with self.assertRaises(ValueError):
                    self.replay(boot, rows)

    def test_incomplete_transport_clock_or_worker_result_cannot_qualify(self):
        for change in ("response", "clock", "drop"):
            with self.subTest(change=change):
                boot, rows = self.fixtures()
                if change == "response":
                    rows[4]["receipt"]["response_complete"] = False
                elif change == "clock":
                    rows[4]["receipt"]["begin_nanos"] = "0"
                else:
                    final = rows[10]["records"][-1]
                    value = json.loads(evidence.transport._blob(final["response"]))
                    value["Running"] = True
                    changed_response(final, value)
                with self.assertRaises(ValueError):
                    self.replay(boot, rows)


class KubectlArchive(unittest.TestCase):
    def fixture(self, root, *, extra=False):
        payload = b"small synthetic executable fixture\n"
        (root / "tools").mkdir()
        (root / "tools/kubectl").write_bytes(payload)
        with tarfile.open(root / "kubectl.tar", "w") as stream:
            member = tarfile.TarInfo("kubectl")
            member.size, member.mode = len(payload), 0o755
            stream.addfile(member, io.BytesIO(payload))
            if extra:
                stream.addfile(tarfile.TarInfo("extra"))
        header = wire({"name": "kubectl", "size": len(payload), "mode": 0o755, "mtime": "original", "linkTarget": ""})
        rows = [None] * 11
        rows[9] = {"archive": reference(root / "kubectl.tar", root), "raw": {"receipt": {
            "archive_stat_header": evidence.base64.b64encode(header).decode()}}}
        rows[10] = {"stdout": (hashlib.sha256(payload).hexdigest() + "  /usr/bin/kubectl\n").encode()}
        return {"kubectl": {"file": reference(root / "tools/kubectl", root)}}, rows

    def test_exact_member_hash_and_worker_hash_all_bind(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            boot, rows = self.fixture(root)
            evidence._kubectl(root, boot, rows)
            rows[10]["stdout"] = b"0" * 64 + b" /usr/bin/kubectl\n"
            with self.assertRaisesRegex(ValueError, "worker-hash"):
                evidence._kubectl(root, boot, rows)

    def test_rehashed_extra_member_or_crossed_stat_header_rejected(self):
        for extra in (False, True):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                boot, rows = self.fixture(root, extra=extra)
                if not extra:
                    header = {"name": "kubectl", "size": 1, "mode": 0o755, "mtime": "original", "linkTarget": ""}
                    rows[9]["raw"]["receipt"]["archive_stat_header"] = evidence.base64.b64encode(wire(header)).decode()
                with self.assertRaises(ValueError):
                    evidence._kubectl(root, boot, rows)


class WindowsSetupCommands(unittest.TestCase):
    def fixture(self, root):
        directory = root / "commands/00-observed"
        directory.mkdir(parents=True)
        for name, data in (("stdout", b"original output"), ("stderr", b"")):
            (directory / (name + ".bin")).write_bytes(data)
        row = {"argv": [r"C:\tools\docker.exe", "version"], "cleanup_timeout_seconds": 10,
               "creation_time_100ns": "123", "cwd": r"C:\owned", "disk_free_before": str(3 * 1024**3),
               "minimum_disk_free": str(3 * 1024**3), "executable": {"path": r"C:\tools\docker.exe", "bytes": "1",
               "sha256": sha256(b"x")}, "exit_code": 0, "failure": None, "finished_nanos": "11",
               "job": {"active": 0, "terminated": 0, "total": 1}, "job_empty": True, "output_closed": True,
               "process_id": 123, "reaped": True, "started_nanos": "10", "timeout_seconds": 60,
               "stdout": reference(directory / "stdout.bin", root), "stderr": reference(directory / "stderr.bin", root)}
        write_json(directory / "receipt.json", row)
        return {"started_nanos": "0", "finished_nanos": "20", "commands": [reference(directory / "receipt.json", root)]}, row

    def test_original_outputs_and_rehashed_active_job_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document, row = self.fixture(root)
            self.assertEqual(evidence._windows(root, document)["observed"]["stdout"], b"original output")
            row["job"]["active"] = 1
            path = root / document["commands"][0]["path"]
            write_json(path, row)
            document["commands"][0] = reference(path, root)
            with self.assertRaisesRegex(ValueError, "job-active"):
                evidence._windows(root, document)


if __name__ == "__main__":
    unittest.main()
