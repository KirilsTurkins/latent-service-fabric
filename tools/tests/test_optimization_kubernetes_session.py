"""Synthetic transport checks only; these are not client or workload evidence."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.optimization_docker.owned import encoded
from tools.optimization_evidence.common import EvidenceError, decode, sha256
from tools.optimization_kubernetes import model
from tools.optimization_kubernetes.session import Session


class FakeAttach:
    def __init__(self, argv, directory):
        self.argv, self.directory = argv, directory
        self.child, self.start_ticks = SimpleNamespace(pid=123), "456"
        self.closed = False
        self.pending, self.sent, self.stdout = [], [], []
        self.digest = sha256((directory / "plan.json").read_bytes())
        self.offset = 1  # The one synthetic ready event was acknowledged from Pod logs.

    def send_line(self, line):
        self.sent.append(line)
        value = decode(line)
        kind = value["command"]
        names = ["first-response"] if kind == "phase" and value["phase"] == 0 else []
        names.append({"begin-group": "group-ready", "inventory": "inventory", "phase": "phase-complete",
                      "finish-group": "group-finished", "finish": "complete"}[kind])
        for name in names:
            row = ack(self.digest, name, value["ordinal"], self.offset)
            if name != "complete":
                self.offset += 1
            raw = encoded(row)
            self.pending.append(raw)
            self.stdout.append(raw)

    def next_line(self, timeout=120):
        if self.pending:
            return self.pending.pop(0)
        raise EOFError("synthetic-transport-eof")

    def close(self, *, force=False):
        if not self.closed:
            self.closed = True
            (self.directory / "attach-stdout.ndjson").write_bytes(b"".join(self.stdout))
            self.receipt = {"exit_code": 0, "reaped": True, "output_closed": True,
                "forced_kill": force, "process_group_gone": True, "failure": None,
                "subreaper": {"restored": True}}
        return self.receipt


def ack(digest, event="ready", ordinal=None, offset=0):
    row = {"schema": model.CLIENT_PREFIX + "ack.v1", "event": event, "command_ordinal": ordinal,
           "process_id": 1, "plan_sha256": digest}
    if event == "complete":
        row["summary"] = {"path": "summary.json", "bytes": "3", "sha256": sha256(b"{}\n")}
    else:
        row["event_record"] = {"path": "events.jsonl", "offset": str(offset), "bytes": "1",
                               "sha256": sha256(b"\n")}
        row["attempts"] = {"path": "attempts.jsonl", "bytes": "0", "sha256": sha256(b"")}
    return row


class Campaign:
    def __init__(self, root):
        self.root, self.owner, self.run_id, self.profile = root, "lsf-112-abcdef012345", "smoke-01", "smoke"
        self.namespace = model.namespace_name(self.owner, self.run_id)
        self.remote_root = model.host_path(self.owner, self.run_id)
        self.remote_fixtures = self.remote_root + "/fixtures"
        self.images = {"client": "lsf111-images-fc45a33903fb46eea767:client"}
        self.kubectl, self.kubeconfig = Path("kubectl"), Path("private-kubeconfig")
        self.worker_name = self.owner + "-worker"
        self.api = self
        self.log_calls, self.events, self.deleted = 0, [], []
        self.changed_plan = False

    def prepare_directory(self, relative, source):
        self.upload_names = sorted(path.name for path in source.iterdir())
        self.original = (source / "plan.json").read_bytes()
        return self.remote_root + "/" + relative

    def create_pod(self, manifest):
        self.pod = copy.deepcopy(manifest)
        self.pod["metadata"]["uid"] = "11111111-1111-4111-8111-111111111111"
        self.pod["spec"]["nodeName"] = self.worker_name
        self.pod["status"] = {"phase": "Running", "containerStatuses": [{"name": "client",
            "restartCount": 0, "lastState": {}, "containerID": "containerd://" + "a" * 64,
            "imageID": "sha256:" + "b" * 64, "state": {"running": {}}}]}
        return {"pod": copy.deepcopy(self.pod), "call": 0}

    def wait_pod(self, name, condition):
        pod = copy.deepcopy(self.pod)
        if condition == "succeeded":
            pod["status"]["phase"] = "Succeeded"
            pod["status"]["containerStatuses"][0]["state"] = {"terminated": {"exitCode": 0}}
        return pod, 1

    def call(self, method, path, *, json_response):
        self.log_calls += 1
        if self.log_calls == 1:
            return b"", self.log_calls
        ready = encoded(ack(sha256(self.original)))
        attachment = self.root / "clients/0/attach-stdout.ndjson"
        return ready + (attachment.read_bytes() if attachment.exists() else b""), self.log_calls

    def observe_client(self, pod, stage):
        return {"synthetic_stage": stage}

    def progress(self, kind, value):
        self.events.append(kind)

    def download_directory(self, remote, local):
        local.mkdir()
        (local / "plan.json").write_bytes(self.original + (b" " if self.changed_plan else b""))
        (local / "summary.json").write_bytes(b"{}\n")
        return {"synthetic_download": True}

    def delete_pod(self, pod):
        self.deleted.append(pod["metadata"]["uid"])
        return {"uid": self.deleted[-1]}


def all_groups(session):
    for group in session.groups:
        index = group["ordinal"]
        targets = [{"service": model.SERVICES[i], "endpoint": f"http://10.96.0.{i + 1}:7070",
                    "owner_ref": f"owner-{i}", "app_process_id": 2} for i in range(group["density"])]
        session.command("begin-group", index, targets=targets)
        session.command("inventory", index, barrier="ready")
        session.observe(f"group-{index}-ready")
        for phase in group["phases"]:
            session.command("phase", index, phase=phase["ordinal"])
            if phase["ordinal"] == 0:
                session.command("inventory", index, barrier="served")
                session.observe(f"group-{index}-served")
        session.command("inventory", index, barrier="final")
        session.observe(f"group-{index}-final")
        session.command("finish-group", index)


class KubernetesSessionTests(unittest.TestCase):
    def session(self, path):
        return Session(Campaign(path), 0)

    @patch("tools.optimization_kubernetes.session.Attach", FakeAttach)
    @patch("tools.optimization_kubernetes.session.time.sleep")
    def test_complete_transport_keeps_ready_and_raw_files_separate(self, _sleep):
        with TemporaryDirectory() as directory:
            session = self.session(Path(directory))
            self.assertEqual(session.campaign.upload_names, ["plan.json"])
            self.assertEqual(session.record["initial_log"]["calls"], [1, 2])
            self.assertEqual(len(session.acknowledgements), 1)
            self.assertIn("kind-" + session.campaign.owner, session.attach.argv)
            all_groups(session)
            value = session.finish()
            self.assertEqual(len(value["commands"]), 61)
            self.assertEqual(len(value["acknowledgements"]), 68)
            self.assertEqual(sum(row["ack"]["event"] == "first-response"
                                 for row in value["acknowledgements"]), 6)
            self.assertTrue(all(line.endswith(b"\n") and b"\n" not in line[:-1] for line in session.attach.sent))
            self.assertEqual(value["directory"], "clients/0/raw")
            self.assertEqual(value["parent_directory"], "clients/0")
            self.assertTrue(value["downloaded_plan"]["byte_identical"])
            self.assertFalse(value["attach"]["forced_kill"])
            self.assertEqual(len(session.campaign.deleted), 1)
            self.assertEqual(len((session.root / "parent-acks.ndjson").read_bytes().splitlines()), 68)

    @patch("tools.optimization_kubernetes.session.Attach", FakeAttach)
    @patch("tools.optimization_kubernetes.session.time.sleep")
    def test_out_of_order_command_retains_failure_and_forces_attach_cleanup(self, _sleep):
        with TemporaryDirectory() as directory:
            session = self.session(Path(directory))
            with self.assertRaisesRegex(EvidenceError, "command-order"):
                session.command("inventory", 0, barrier="ready")
            self.assertTrue(session.attach.receipt["forced_kill"])
            self.assertTrue((session.root / "failure.json").is_file())
            self.assertEqual(session.attach.sent, [])

    @patch("tools.optimization_kubernetes.session.Attach", FakeAttach)
    @patch("tools.optimization_kubernetes.session.time.sleep")
    def test_changed_downloaded_plan_is_retained_and_never_claims_complete(self, _sleep):
        with TemporaryDirectory() as directory:
            session = self.session(Path(directory))
            all_groups(session)
            session.campaign.changed_plan = True
            with self.assertRaisesRegex(EvidenceError, "downloaded-plan-changed"):
                session.finish()
            self.assertTrue((session.root / "raw/plan.json").exists())
            self.assertTrue((session.root / "failure.json").exists())
            self.assertFalse((session.root / "parent.json").exists())
            self.assertEqual(session.campaign.deleted, [])

    @patch("tools.optimization_kubernetes.session.Attach", FakeAttach)
    @patch("tools.optimization_kubernetes.session.time.sleep")
    def test_ack_rejects_crossed_identity_duplicate_offset_and_extra_lines(self, _sleep):
        for kind in ("pid", "boolean-pid", "digest", "ordinal", "offset", "extra-line"):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                session = self.session(Path(directory))
                row = ack(session.digest, "group-ready", 0, 1)
                if kind == "pid":
                    row["process_id"] = 2
                elif kind == "boolean-pid":
                    row["process_id"] = True
                elif kind == "digest":
                    row["plan_sha256"] = "sha256:" + "c" * 64
                elif kind == "ordinal":
                    row["command_ordinal"] = True
                elif kind == "offset":
                    row["event_record"]["offset"] = "0"
                raw = encoded(row) * (2 if kind == "extra-line" else 1)
                with self.assertRaises(EvidenceError):
                    session._ack(raw, "group-ready", 0)
                session.close()


if __name__ == "__main__":
    unittest.main()
