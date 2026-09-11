"""Offline final cleanup fixtures, using only an in-memory Docker substitute."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.artifact_identity_runner.files import reference, write_json
from tools.optimization_evidence.common import sha256
from tools.optimization_kubernetes import bootstrap, cluster_cleanup_evidence as evidence
from tools.optimization_kubernetes.transport import blob
from tools.tests import test_optimization_kubernetes_bootstrap as fixtures


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def http(method, path, status, request, response, start):
    return {"method": method, "path": path, "begin_nanos": str(start), "end_nanos": str(time.monotonic_ns()),
            "status": status, "request_bytes": str(len(request)), "request_sha256": sha256(request),
            "response_bytes": str(len(response)), "response_sha256": sha256(response),
            "response_complete": True, "connection_closed": True, "failure": None}


class RecordedEngine(fixtures.FakeEngine):
    def __init__(self, nodes, network):
        started = time.monotonic_ns()
        super().__init__(nodes, network)
        self.version_body = wire({"Version": "29.7.2", "ApiVersion": "1.54", "MinAPIVersion": "1.44"})
        self.version_receipt = http("GET", "/version", 200, b"", self.version_body, started)

    def request(self, method, path, body=None, **kwargs):
        start = time.monotonic_ns()
        value, receipt = super().request(method, path, body, **kwargs)
        if receipt["status"] in (204, 304):
            self.last_body, value = b"", None
        request = b"" if body is None else wire(body)
        return value, http(method, "/v1.54" + path, receipt["status"], request, self.last_body, start)


class ClusterCleanupEvidence(unittest.TestCase):
    def fixture(self, root, *, preexisting=False):
        args, engine, credentials = fixtures.ClusterCleanup().fixture(root, preexisting=preexisting)
        base = args.bootstrap.parent
        boot = json.loads(args.bootstrap.read_bytes())
        original = json.loads((base / "original-setup.json").read_bytes())
        original["root"] = r"C:\owned\issue112-setup-01"
        original["private_kubeconfig"] = "private/kubeconfig"
        original["kubeconfig_publishable"] = False
        original["private_kubeconfig_identity"] = copy.deepcopy(boot["private_credentials"][0])
        write_json(base / "original-setup.json", original)
        boot["original_setup"] = reference(base / "original-setup.json", base)
        boot["finished_nanos"] = "0"
        write_json(args.bootstrap, boot)
        source = {"clean": True, "commit": "a" * 40, "tree": "b" * 40, "cargo_lock_sha256": sha256(b"lock")}
        with patch.object(bootstrap, "BENCH_ROOT", root), \
                patch.object(bootstrap, "Engine", side_effect=lambda: RecordedEngine(original["nodes"], engine.network)), \
                patch.object(bootstrap, "source", return_value=source), redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.cleanup(args, root), 0)
        self.assertTrue(all(not path.exists() for path in credentials))
        # The mocked producer ran on this test host. Give the synthetic fixture
        # its original Linux path spelling before archive-style replay.
        boot["output"] = "/bench/kubernetes/" + boot["owner"]
        write_json(args.bootstrap, boot)
        cleanup = json.loads((args.output / "cleanup.json").read_bytes())
        cleanup["bootstrap"] = {"path": boot["output"] + "/bootstrap.json",
                                 "sha256": reference(args.bootstrap, base)["sha256"]}
        write_json(args.output / "cleanup.json", cleanup)
        helper = args.output / "windows-credential-cleanup.py"
        helper.write_bytes(b"# Synthetic retained helper fixture. Never executed.\n")
        sidecar = {"schema": "latent.optimization.kubernetes-windows-credential-cleanup.v1", "owner": boot["owner"],
                   "original_setup_sha256": boot["original_setup"]["sha256"],
                   "credential": copy.deepcopy(original["private_kubeconfig_identity"]),
                   "verified_before": True, "removed": True, "absent": True,
                   "started_nanos": "1", "finished_nanos": "2", "helper": reference(helper, args.output),
                   "cluster_cleanup": reference(args.output / "cleanup.json", args.output), "failure": None}
        write_json(args.output / "windows-credential-cleanup.json", sidecar)
        return args.output, base, boot

    def validate(self, root, base, boot):
        # The separate bootstrap suite already tests its full original byte graph.
        with patch.object(evidence.bootstrap_evidence, "validate", return_value=boot), \
                patch.object(bootstrap, "Engine", side_effect=AssertionError("offline replay must not contact Docker")), \
                patch.object(bootstrap, "source", side_effect=AssertionError("offline replay must not execute Git")):
            return evidence.validate(root, base)

    def mutate_row(self, root, operation, change):
        path = root / "cleanup.ndjson"
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        row = next(row for row in rows if row["operation"] == operation)
        change(row)
        path.write_bytes(b"".join(wire(row) + b"\n" for row in rows))

    def test_original_emitted_cleanup_replays_after_all_private_copies_are_gone(self):
        for preexisting in (False, True):
            with self.subTest(preexisting=preexisting), tempfile.TemporaryDirectory() as temporary:
                root, base, boot = self.fixture(Path(temporary), preexisting=preexisting)
                result = self.validate(root, base, boot)
                self.assertEqual(result, json.loads((root / "cleanup.json").read_bytes()))
                self.assertEqual(len(result["nodes_removed"]), 2)
                self.assertEqual(result["network_removed"], not preexisting)
                self.assertEqual(result["credentials_removed"][-1]["path"], "private/kubeconfig")
                sidecar = json.loads((root / "windows-credential-cleanup.json").read_bytes())
                self.assertEqual(sidecar["credential"]["path"], "private/kubeconfig")

    def test_rehashed_foreign_network_or_crossed_node_is_rejected(self):
        for operation in ("network-before", "node-recheck-worker"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root, base, boot = self.fixture(Path(temporary))

                def change(row):
                    value = json.loads(evidence.transport._blob(row["response"]))
                    if operation == "network-before":
                        value["Containers"]["9" * 64] = {}
                    else:
                        value["Id"] = "9" * 64
                    data = wire(value)
                    row["response"] = blob(data)
                    row["receipt"].update(response_bytes=str(len(data)), response_sha256=sha256(data))

                self.mutate_row(root, operation, change)
                with self.assertRaises(ValueError):
                    self.validate(root, base, boot)

    def test_volume_deletion_or_missing_absence_cannot_be_relabelled_as_valid(self):
        for operation in ("node-delete-worker", "node-absent-worker"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root, base, boot = self.fixture(Path(temporary))

                def change(row):
                    if operation == "node-delete-worker":
                        row["path"] = row["path"].replace("v=false", "v=true")
                        row["receipt"]["path"] = "/v1.54" + row["path"]
                    else:
                        row["receipt"]["status"] = 200

                self.mutate_row(root, operation, change)
                with self.assertRaises(ValueError):
                    self.validate(root, base, boot)

    def test_linux_credential_absence_is_required_even_with_rehashed_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, base, boot = self.fixture(Path(temporary))
            value = json.loads((root / "cleanup.json").read_bytes())
            value["credentials_removed"][0]["absent"] = False
            write_json(root / "cleanup.json", value)
            sidecar = json.loads((root / "windows-credential-cleanup.json").read_bytes())
            sidecar["cluster_cleanup"] = reference(root / "cleanup.json", root)
            write_json(root / "windows-credential-cleanup.json", sidecar)
            with self.assertRaisesRegex(ValueError, "credential-absence"):
                self.validate(root, base, boot)

    def test_original_windows_credential_and_retained_helper_are_mandatory(self):
        for change in ("absent", "path", "relative-traversal", "digest", "bytes", "original", "helper"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root, base, boot = self.fixture(Path(temporary))
                path = root / "windows-credential-cleanup.json"
                value = json.loads(path.read_bytes())
                if change == "absent":
                    value["absent"] = False
                elif change == "path":
                    value["credential"]["path"] = r"C:\unrelated\private\kubeconfig"
                elif change == "relative-traversal":
                    value["credential"]["path"] = "private/../kubeconfig"
                elif change == "digest":
                    value["credential"]["sha256"] = sha256(b"crossed credential")
                elif change == "bytes":
                    value["credential"]["bytes"] = "1"
                elif change == "original":
                    value["original_setup_sha256"] = sha256(b"crossed setup")
                else:
                    value["helper"]["path"] = "../unrelated.py"
                write_json(path, value)
                with self.assertRaises(ValueError):
                    self.validate(root, base, boot)

    def test_windows_relative_identity_still_requires_safe_bounded_original_scope(self):
        changes = (
            lambda original: original.update(root="relative/setup"),
            lambda original: original.update(root=r"C:\owned\..\unrelated"),
            lambda original: original.update(root=r"\\server\share\setup"),
            lambda original: original.update(root="C:\\owned\\" + "x" * 32768),
            lambda original: original.update(kubeconfig_publishable=True),
            lambda original: original["private_kubeconfig_identity"].update(path="../kubeconfig"),
            lambda original: original["private_kubeconfig_identity"].update(bytes="32769"),
        )
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root, base, boot = self.fixture(Path(temporary))
                original = json.loads((base / "original-setup.json").read_bytes())
                change(original)
                write_json(base / "original-setup.json", original)
                boot["original_setup"] = reference(base / "original-setup.json", base)
                value = json.loads((root / "windows-credential-cleanup.json").read_bytes())
                value["original_setup_sha256"] = boot["original_setup"]["sha256"]
                value["credential"] = copy.deepcopy(original["private_kubeconfig_identity"])
                write_json(root / "windows-credential-cleanup.json", value)
                with self.assertRaisesRegex(ValueError, "windows-(root|credential-bound)"):
                    self.validate(root, base, boot)

    def test_changed_original_setup_bytes_do_not_rebind_the_relative_credential(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, base, boot = self.fixture(Path(temporary))
            original = json.loads((base / "original-setup.json").read_bytes())
            original["root"] = r"C:\other\setup"
            write_json(base / "original-setup.json", original)
            with self.assertRaises(ValueError):
                self.validate(root, base, boot)


if __name__ == "__main__":
    unittest.main()
