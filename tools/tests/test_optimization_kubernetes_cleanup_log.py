"""Exact missing-log cleanup policy fixtures; no CRI calls or workload results."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.optimization_evidence.common import EvidenceError, sha256
from tools.optimization_kubernetes import model, replay, transport, transport_evidence
from tools.tests.test_optimization_kubernetes_transport_evidence import (
    CONTAINER, OWNER, blob, framed, protocol, response, wire,
)

CID = "c" * 64
POLICY = {"namespace": OWNER + "-run", "pod_name": "p0-g0-native-0",
          "pod_uid": "12345678-1234-1234-1234-123456789abc", "container_name": "native", "container_id": CID}


def warning(policy=POLICY):
    path = transport.cleanup_log_path(["crictl", "rm", policy["container_id"]], policy)
    message = (f'removing log file {path} for container "{policy["container_id"]}" failed: '
               f'remove {path}: no such file or directory')
    return ('time="2026-09-11T14:13:27Z" level=error msg=' + json.dumps(message) + "\n").encode()


def fixture(*, annotate=True, stderr=None, stdout=None):
    rows = protocol()
    row = rows[2]
    row["argv"] = ["crictl", "rm", CID]
    if annotate:
        row["cleanup_log_owner"] = deepcopy(POLICY)
    first = row["records"][0]
    first["request"]["Cmd"] = ["timeout", "--signal=TERM", "--kill-after=5s", "20s", *row["argv"]]
    request = wire(first["request"])
    first["receipt"].update(request_bytes=str(len(request)), request_sha256=sha256(request))
    output = framed((CID + "\n").encode() if stdout is None else stdout)
    stderr = warning() if stderr is None else stderr
    if stderr:
        output += framed(stderr, 2)
    response(row["records"][1], output)
    return rows


class CleanupLogTests(unittest.TestCase):
    def replay(self, rows, **kwargs):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "api.ndjson"
            original = b"".join(wire(row) + b"\n" for row in rows)
            path.write_bytes(original)
            result = transport_evidence.validate(path, worker_container_id=CONTAINER,
                started_nanos="0", finished_nanos="100", **kwargs)
            self.assertEqual(path.read_bytes(), original)
            return result

    def test_exact_owned_missing_log_is_retained_with_successful_reap(self):
        row = self.replay(fixture())["rows"][2]
        self.assertEqual(row["stderr"], warning())
        self.assertEqual(row["stdout"], (CID + "\n").encode())
        self.assertEqual(row["cleanup_log_owner"], POLICY)
        self.assertEqual(row["cleanup_log_warning"]["kind"], "owned-container-log-already-absent")
        self.assertEqual(row["final_inspect"]["ExitCode"], 0)
        self.assertIsNone(row["raw"]["failure"])

    def test_default_stderr_and_any_other_failure_stay_rejected(self):
        with self.assertRaises(EvidenceError):
            self.replay(fixture(annotate=False))
        rows = fixture()
        rows[2]["failure"] = "EvidenceError"
        with self.assertRaises(EvidenceError):
            self.replay(rows)
        rows = fixture()
        final = json.loads(transport_evidence._blob(rows[2]["records"][2]["response"]))
        final["ExitCode"] = 1
        response(rows[2]["records"][2], wire(final))
        with self.assertRaises(EvidenceError):
            self.replay(rows)

    def test_wrong_path_container_message_or_extra_line_never_matches(self):
        for value in (warning().replace(b"no such file or directory", b"permission denied"),
                      warning().replace(b"/native/0.log", b"/native/1.log"),
                      warning().replace(POLICY["pod_uid"].encode(), b"different-pod-uid"),
                      warning().replace(CID.encode(), ("d" * 64).encode()),
                      warning() + warning(), warning() + b"another warning\n"):
            with self.subTest(stderr=value), self.assertRaises(EvidenceError):
                self.replay(fixture(stderr=value))
        with self.assertRaises(EvidenceError):
            self.replay(fixture(stdout=b"different container\n"))

    def test_policy_cannot_authorize_rmp_foreign_namespace_or_changed_uid(self):
        for change in ("operation", "namespace", "uid"):
            rows = fixture()
            if change == "operation":
                rows[2]["argv"][1] = "rmp"
            elif change == "namespace":
                rows[2]["cleanup_log_owner"]["namespace"] = "lsf-112-aaaaaaaaaaaa-run"
            else:
                rows[2]["cleanup_log_owner"]["pod_uid"] = "87654321-1234-1234-1234-123456789abc"
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                self.replay(rows)
        with self.assertRaises(EvidenceError):
            transport.cleanup_log_path(["crictl", "rmp", CID], POLICY)

    def test_quiet_rm_with_owned_policy_remains_quiet(self):
        row = self.replay(fixture(stderr=b""))["rows"][2]
        self.assertIsNone(row["cleanup_log_warning"])
        self.assertEqual(row["stderr"], b"")

    def test_original_smoke03_exception_requires_exact_journal_bytes(self):
        with self.assertRaisesRegex(EvidenceError, "historical-cleanup-byte-identity"):
            self.replay(protocol(), recovered_smoke03_cleanup=True)
        with self.assertRaises(EvidenceError):
            self.replay(protocol(), recovered_smoke03_cleanup=1)

    def test_cri_policy_binds_no_restart_and_original_container_name(self):
        item = {"id": CID, "state": "CONTAINER_EXITED", "metadata": {"name": "native", "attempt": 0},
            "labels": {"io.kubernetes.pod.namespace": POLICY["namespace"],
                       "io.kubernetes.pod.name": POLICY["pod_name"], "io.kubernetes.pod.uid": POLICY["pod_uid"],
                       "io.kubernetes.container.name": "native"}}
        self.assertEqual(transport.cleanup_owner(item), POLICY)
        for change in ({"name": "client", "attempt": 0}, {"name": "native", "attempt": 1}):
            with self.assertRaises(EvidenceError):
                transport.cleanup_owner({**item, "metadata": change})

    def test_worker_policy_retains_original_warning_and_defaults_still_fail(self):
        for policy in (POLICY, None):
            rows = fixture()
            retained = rows[2]["records"]
            worker = object.__new__(transport.Worker)
            worker.owner, worker.container_id, worker.engine = OWNER, CONTAINER, Mock()
            calls = iter((retained[0], retained[2]))

            def request(*_args, **_kwargs):
                record = next(calls)
                worker.engine.last_body = transport_evidence._blob(record["response"])
                return json.loads(worker.engine.last_body), record["receipt"]

            def exchange(*_args, **_kwargs):
                worker.engine.last_body = transport_evidence._blob(retained[1]["response"])
                return worker.engine.last_body, retained[1]["receipt"]

            worker.engine.request.side_effect, worker.engine._exchange.side_effect = request, exchange
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "api.ndjson"
                worker.journal = transport.Journal(path)
                if policy is None:
                    with self.assertRaisesRegex(EvidenceError, "worker-exec-stderr"):
                        worker.command(["crictl", "rm", CID])
                else:
                    output, ordinal = worker.command(["crictl", "rm", CID], cleanup_log_owner=policy)
                    self.assertEqual((output, ordinal), ((CID + "\n").encode(), 0))
                row = json.loads(path.read_bytes())
                self.assertEqual(transport_evidence._multiplexed(transport_evidence._blob(row["records"][1]["response"]))[1], warning())
                self.assertEqual(row["failure"], "EvidenceError" if policy is None else None)
                self.assertEqual("cleanup_log_owner" in row, policy is not None)


class CleanupAbsenceTests(unittest.TestCase):
    def fixture(self):
        policy = deepcopy(POLICY)
        namespace, pod, uid = (policy[key] for key in ("namespace", "pod_name", "pod_uid"))
        item = {"id": CID, "state": "CONTAINER_EXITED", "metadata": {"name": "native", "attempt": 0},
            "labels": {"io.kubernetes.pod.namespace": namespace, "io.kubernetes.pod.name": pod,
                       "io.kubernetes.pod.uid": uid, "io.kubernetes.container.name": "native"}}
        app = {"create": {"pod": {"metadata": {"uid": uid, "name": pod}}},
               "pod_ready": {"status": {"containerStatuses": [{"name": "native", "containerID": "containerd://" + CID}]}}}
        cleanup = {"schema": model.PREFIX + "cleanup.v1", "errors": [], "namespace": namespace,
            "namespace_uid": "namespace-uid", "namespace_absent": True, "remote_removed": True,
            "remaining_pods": {}, "private_tls_removed": True,
            "pods": [{"name": pod, "uid": uid, "call": 0, "absence_call": 1}],
            "namespace_calls": [2, 3], "cri_calls": [4, 6, 7, 8],
            "cri_removed": [{"id": CID, "operation": "rm", "call": 5}], "remote_remove_call": 9}
        base = "/api/v1/namespaces/" + namespace
        script = ('set -eu; p="$1"; [ "$(readlink -f -- "$p")" = "$p" ]; '
                  '[ ! -L "$p" ]; if [ -d "$p" ]; then '
                  'rm -rf --one-file-system -- "$p"; fi; [ ! -e "$p" ]')
        rows = [{"request_json": {"preconditions": {"uid": uid}}}, {},
            {"raw": {"path": base, "method": "DELETE"}, "request_json": {"preconditions": {"uid": "namespace-uid"}}},
            {"raw": {"path": base, "method": "GET", "status": 404}},
            {"stdout": wire({"containers": [item]})}, {"cleanup_log_owner": policy},
            {"stdout": wire({"containers": []})}, {"stdout": wire({"items": []})},
            {"stdout": wire({"items": []})},
            {"raw": {"argv": ["sh", "-c", script, "owned-cleanup", model.host_path(OWNER, "run")]}}]
        suite = {"owner": OWNER, "namespace": namespace, "namespace_uid": "namespace-uid", "run_id": "run",
                 "clients": [], "groups": [{"owners": [app]}], "cleanup": cleanup}
        return suite, {"rows": rows}, item

    def check(self, suite, journal):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cleanup.json").write_bytes(wire(suite["cleanup"]))
            with patch.object(replay.transport_evidence, "get", side_effect=lambda value, ordinal, **_: value["rows"][ordinal]):
                replay._cleanup(suite, root, journal, set())

    def test_warning_requires_later_empty_cri_inventory_and_exact_original_pod(self):
        suite, journal, _ = self.fixture()
        self.check(suite, journal)
        for change in ("absence", "owner", "original-container"):
            suite, journal, item = self.fixture()
            if change == "absence":
                journal["rows"][6]["stdout"] = wire({"containers": [item]})
            elif change == "owner":
                journal["rows"][5]["cleanup_log_owner"]["pod_uid"] = "87654321-1234-1234-1234-123456789abc"
            else:
                suite["groups"][0]["owners"][0]["pod_ready"]["status"]["containerStatuses"][0]["containerID"] = "containerd://" + "d" * 64
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                self.check(suite, journal)
