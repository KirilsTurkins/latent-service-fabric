"""Bounded offline failure proofs; these fixtures make no workload claims."""
from copy import deepcopy
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from tools.optimization_evidence.common import EvidenceError, sha256
from tools.optimization_kubernetes import failure_evidence as evidence, model, transport_evidence
from tools.tests.test_optimization_kubernetes_transport_evidence import CONTAINER, OWNER, kube, protocol, wire


def suite():
    return {"owner": OWNER, "run_id": "smoke-01", "namespace": OWNER + "-smoke-01", "namespace_uid": "namespace-uid"}


def pod(name="client-p0", uid="pod-uid"):
    return {"kind": "Pod", "apiVersion": "v1", "metadata": {"name": name, "uid": uid,
        "namespace": suite()["namespace"], "labels": model.labels(OWNER, "smoke-01", name)}}


def derived(rows):
    return {"rows": [{"raw": {"ordinal": index, **row}, "started_nanos": str(10 + index * 2),
                     "finished_nanos": str(11 + index * 2), **row.pop("derived", {})}
                    for index, row in enumerate(deepcopy(rows))]}


def runtime_rows(*, uid="pod-uid", remaining=False):
    owned = {"id": "c" * 64, "state": "SANDBOX_NOTREADY", "labels": {
        "io.kubernetes.pod.namespace": suite()["namespace"], "io.kubernetes.pod.uid": uid,
        "io.kubernetes.pod.name": "client-p0"}}
    foreign = {"id": "d" * 64, "state": "SANDBOX_READY", "labels": {"io.kubernetes.pod.namespace": "kube-system"}}
    rows = []
    for argv, output in ((["crictl", "ps", "-a", "-o", "json"], {"containers": []}),
            (["crictl", "ps", "-a", "-o", "json"], {"containers": []}),
            (["crictl", "pods", "-o", "json"], {"items": [foreign, owned]}),
            (["crictl", "rmp", "c" * 64], None),
            (["crictl", "pods", "-o", "json"], {"items": [foreign, owned] if remaining else [foreign]})):
        rows.append({"provider": "docker", "operation": "worker-exec", "argv": argv, "timeout_seconds": 20,
                     "derived": {"stdout": b"" if output is None else wire(output)}})
    return rows


def downloads(root, *, attempts=b""):
    rows, receipts = [], []
    for index, suffix in enumerate(("clients/0", "owners/p0-g0-lsf-0")):
        files = {"attempts.jsonl": attempts, "events.jsonl": b"{}\n"} if index == 0 else {"events.ndjson": b"{}\n"}
        local = "failure-outputs/" + str(index + 2)
        output = root / "recovery" / local
        output.mkdir(parents=True)
        inventory = {"entries": [{"path": ".", "kind": "directory", "mode": "0700"}], "bytes": "0"}
        archive = root / "recovery/transfers" / f"download-{index:04d}.tar"
        archive.parent.mkdir(exist_ok=True)
        with tarfile.open(archive, "w", format=tarfile.USTAR_FORMAT) as stream:
            member = tarfile.TarInfo(suffix.split("/")[-1])
            member.type, member.mode = tarfile.DIRTYPE, 0o700
            stream.addfile(member)
            for name, data in sorted(files.items()):
                (output / name).write_bytes(data)
                inventory["entries"].append({"path": name, "kind": "file", "mode": "0644",
                                             "bytes": str(len(data)), "sha256": sha256(data)})
                member = tarfile.TarInfo(suffix.split("/")[-1] + "/" + name)
                member.size, member.mode = len(data), 0o644
                stream.addfile(member, io.BytesIO(data))
        inventory["bytes"] = str(sum(map(len, files.values())))
        blob = archive.read_bytes()
        ref = {"path": "transfers/" + archive.name, "bytes": str(len(blob)), "sha256": sha256(blob)}
        remote = model.host_path(OWNER, "smoke-01", suffix)
        receipts.append({"remote": remote, "local": local, "call": index, "archive": ref, "inventory": inventory})
        rows.append({"provider": "docker", "operation": "worker-download", "source_path": remote,
                     "derived": {"inventory": inventory, "archive": {key: ref[key] for key in ("bytes", "sha256")}}})
    return {"failure_diagnostics": receipts}, derived(rows)


class FailureEvidenceTests(unittest.TestCase):
    def test_original_typemeta_omission_is_allowed_only_under_typed_list_and_same_uid(self):
        item = pod()
        item.pop("kind")
        item.pop("apiVersion")
        value = {"kind": "PodList", "apiVersion": "v1", "metadata": {}, "items": [item]}
        original = deepcopy(value)
        self.assertEqual(evidence._pod_list(value, suite(), {"client-p0": "pod-uid"}), [item])
        self.assertEqual(value, original)
        for alteration in (lambda row: row.update(kind="ServiceList"),
                           lambda row: row["items"][0]["metadata"].update(uid="foreign"),
                           lambda row: row["items"][0].update(kind="Service"),
                           lambda row: row["metadata"].update({"continue": "hidden-page"})):
            changed = deepcopy(value)
            alteration(changed)
            with self.assertRaises(EvidenceError):
                evidence._pod_list(changed, suite(), {"client-p0": "pod-uid"})

    def deletion(self, *, grace=40, uid="pod-uid", absent=True):
        path = "/api/v1/namespaces/" + suite()["namespace"] + "/pods/client-p0"
        body = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": uid},
                "gracePeriodSeconds": grace, "propagationPolicy": "Background"}
        rows = [protocol()[0], kube("DELETE", path, 200, body, wire(pod()), 12),
                kube("GET", path, 200, None, wire(pod()), 14)]
        if absent:
            rows.append(kube("GET", path, 404, None,
                wire({"kind": "Status", "status": "Failure", "reason": "NotFound", "code": 404}), 16))
        rows = [{**row, "ordinal": index} for index, row in enumerate(rows)]
        with tempfile.TemporaryDirectory() as temporary:
            original = b"".join(wire(row) + b"\n" for row in rows)
            file = Path(temporary) / "api.ndjson"
            file.write_bytes(original)
            journal = transport_evidence.validate(file, worker_container_id=CONTAINER, started_nanos="0", finished_nanos="100")
            calls = evidence._Calls(journal)
            calls.get(0, provider="docker", operation="worker-identity")
            self.assertEqual(evidence._delete(calls, 1, path, "pod-uid", suite(), "client-p0"), 3)
            calls.finish()
            self.assertEqual(file.read_bytes(), original)

    def test_real_transport_replay_preserves_forty_second_grace_uid_and_404(self):
        self.deletion()
        for kwargs in ({"grace": 0}, {"uid": "replaced"}, {"absent": False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(EvidenceError):
                self.deletion(**kwargs)

    def test_runtime_cleanup_requires_uid_stopped_state_and_final_absence(self):
        receipt = {"cri_calls": [0, 1, 2, 4], "cri_removed": [{"call": 3, "id": "c" * 64, "operation": "rmp"}]}
        calls = evidence._Calls(derived(runtime_rows()))
        self.assertEqual(evidence._runtime(calls, receipt, suite(), {"client-p0": "pod-uid"}, 0), 5)
        calls.finish()
        for rows in (runtime_rows(uid="replaced"), runtime_rows(remaining=True)):
            with self.assertRaises(EvidenceError):
                evidence._runtime(evidence._Calls(derived(rows)), receipt, suite(), {"client-p0": "pod-uid"}, 0)
        rows = runtime_rows()
        rows[1]["derived"]["stdout"] = b"{}"
        with self.assertRaisesRegex(EvidenceError, "runtime-list"):
            evidence._runtime(evidence._Calls(derived(rows)), receipt, suite(), {"client-p0": "pod-uid"}, 0)

    def test_download_tar_bytes_inventory_and_empty_attempts_are_jointly_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, journal = downloads(root)
            calls = evidence._Calls(journal)
            self.assertEqual(evidence._downloads(root, receipt, suite(), calls, 0), 2)
            calls.finish()
            archive = root / "recovery" / receipt["failure_diagnostics"][0]["archive"]["path"]
            original = archive.read_bytes()
            archive.write_bytes(original[:-1] + b"x")
            with self.assertRaises(EvidenceError):
                evidence._downloads(root, receipt, suite(), evidence._Calls(journal), 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, journal = downloads(root, attempts=b'{"invoke":"unexpected"}\n')
            # Every enclosing hash and tar now agrees, but zero-invocation proof must fail.
            with self.assertRaisesRegex(EvidenceError, "nonzero-invokes"):
                evidence._downloads(root, receipt, suite(), evidence._Calls(journal), 0)

    def test_download_cannot_be_relabelled_to_another_owned_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, journal = downloads(root)
            receipt["failure_diagnostics"][0]["remote"] = model.host_path(OWNER, "smoke-02", "clients/0")
            with self.assertRaisesRegex(EvidenceError, "download-path"):
                evidence._downloads(root, receipt, suite(), evidence._Calls(journal), 0)

    def test_duplicate_or_unconsumed_calls_cannot_disappear_from_failed_attempt(self):
        calls = evidence._Calls(derived(runtime_rows()))
        calls.command(0, ["crictl", "ps", "-a", "-o", "json"])
        with self.assertRaisesRegex(EvidenceError, "duplicate-call"):
            calls.command(0, ["crictl", "ps", "-a", "-o", "json"])
        with self.assertRaisesRegex(EvidenceError, "unused-call"):
            calls.finish()


if __name__ == "__main__":
    unittest.main()
