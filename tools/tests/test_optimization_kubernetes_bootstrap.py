"""Pure bounded bootstrap/teardown fixtures; never contact Docker or Kubernetes."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.artifact_identity_runner.files import reference, write_json
from tools.optimization_docker.engine import EngineError
from tools.optimization_kubernetes import bootstrap as module

OWNER = "lsf-112-123456abcdef"
NETWORK = "a" * 64
OTHER = "b" * 64


def original_value():
    nodes = [{"role": role, "name": OWNER + "-" + role, "container_id": str(index + 1) * 64,
              "image_id": "sha256:" + "f" * 64} for index, role in enumerate(("control-plane", "worker"))]
    return {"schema": "latent.optimization.kubernetes-setup.v1", "status": "incomplete", "owner": OWNER,
            "context": "kind-" + OWNER, "source_before": {"clean": True, "commit": "1" * 40},
            "failure": {"type": "ValueError", "message": "original-import-binding"}, "nodes": nodes,
            "original_images": {}, "image_archive": {"archive": {}, "images": {}},
            "private_kubeconfig_identity": {"path": "private/kubeconfig", **{key: value for key, value in
                module.blob(b"private synthetic kubeconfig").items() if key != "base64"}}, "networks_before": []}


def setup_pair(root):
    original = original_value()
    path = root / "original.json"
    write_json(path, original)
    resume = {**copy.deepcopy(original), "schema": "latent.optimization.kubernetes-setup-resume.v1",
              "status": "ready-for-campaign-preflight", "failure": None,
              "historical_failure": original["failure"], "verification_kind": "read-only-existing-import",
              "original_source_before": original["source_before"], "original_source_after": original["source_before"],
              "source_before": {"clean": True, "commit": "2" * 40},
              "source_after": {"clean": True, "commit": "2" * 40}, "original_setup": reference(path, root)}
    setup = root / "resume.json"
    write_json(setup, resume)
    return SimpleNamespace(setup=setup, original_setup=path), resume


class BootstrapBindings(unittest.TestCase):
    def test_resume_requires_actual_original_bytes_and_exact_owner_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, resume = setup_pair(root)
            actual, original = module._setup(args)
            self.assertEqual(actual, resume)
            self.assertEqual(original["owner"], OWNER)
            args.original_setup.write_bytes(args.original_setup.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "original-setup-hash"):
                module._setup(args)
            args.original_setup = None
            with self.assertRaisesRegex(ValueError, "original-setup-required"):
                module._setup(args)

    def test_engine_initialization_failure_retains_attempt_and_original_failure_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, _ = setup_pair(root)
            args.output = root / "bench" / OWNER
            args.kubeconfig = root / "credential"
            args.kubeconfig.write_bytes(b"private synthetic kubeconfig")
            error = EngineError("synthetic negotiation failure", receipt={"status": 500}, body=b"original failure")
            with patch.object(module, "BENCH_ROOT", root / "bench"), \
                    patch.object(module, "source", return_value={"clean": True}), \
                    patch.object(module, "Engine", side_effect=error):
                with self.assertRaises(EngineError):
                    module.execute(args, root)
            retained = json.loads((args.output / "bootstrap.json").read_bytes())
            self.assertEqual(retained["status"], "incomplete")
            self.assertLessEqual(int(retained["started_nanos"]), int(retained["finished_nanos"]))
            rows = [json.loads(line) for line in (args.output / "bootstrap.ndjson").read_bytes().splitlines()]
            self.assertEqual(rows[0]["operation"], "api-negotiation")
            self.assertEqual(rows[0]["response"], module.blob(b"original failure"))
            self.assertEqual((args.output / "setup.json").read_bytes(), args.setup.read_bytes())
            self.assertEqual((args.output / "original-setup.json").read_bytes(), args.original_setup.read_bytes())

    def test_wrong_kubeconfig_is_rejected_before_any_engine_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, _ = setup_pair(root)
            args.output = root / "bench" / OWNER
            args.kubeconfig = root / "credential"
            args.kubeconfig.write_bytes(b"crossed")
            with patch.object(module, "BENCH_ROOT", root / "bench"), \
                    patch.object(module, "source", return_value={"clean": True}), patch.object(module, "Engine") as engine:
                with self.assertRaisesRegex(ValueError, "kubeconfig-identity"):
                    module.execute(args, root)
                engine.assert_not_called()


class FakeEngine:
    api_version, server_version = "1.54", "29.7.2"
    version_receipt, version_body = {"status": 200}, b'{"Version":"29.7.2"}'

    def __init__(self, nodes, network):
        self.nodes = {row["container_id"]: {"Id": row["container_id"], "Name": "/" + row["name"],
                      "Image": row["image_id"], "Config": {"Labels": {"io.x-k8s.kind.cluster": OWNER,
                        "io.x-k8s.kind.role": row["role"]}}, "State": {"Running": True},
                      "NetworkSettings": {"Networks": {"kind": {"NetworkID": NETWORK}}}} for row in nodes}
        self.network, self.attached, self.alias, self.extra = network, True, OWNER + "-controller", set()
        self.calls, self.last_body, self.fail = [], b"", None

    def request(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body))
        if self.fail and self.fail in path:
            raise EngineError("injected failure", receipt={"status": 500}, body=b"original engine error")
        status, value = 200, {}
        if path == "/containers/" + module.CONTROLLER + "/json":
            connections = {"existing": {"NetworkID": OTHER}}
            if self.attached:
                connections["kind"] = {"NetworkID": NETWORK, "Aliases": [self.alias]}
            value = {"Id": module.CONTROLLER, "State": {"Running": True},
                     "Config": {"Labels": {"latent.benchmark.owner": "issue111-controller-01"}},
                     "NetworkSettings": {"Networks": connections}}
        elif path.startswith("/containers/"):
            identifier = path.split("/")[2].split("?")[0]
            if method == "GET":
                value, status = (copy.deepcopy(self.nodes[identifier]), 200) if identifier in self.nodes else ({}, 404)
            elif method == "POST" and path.endswith("/stop?t=30"):
                self.nodes[identifier]["State"]["Running"] = False
                status = 204
            elif method == "DELETE" and path.endswith("?force=false&v=false"):
                del self.nodes[identifier]
                status = 204
            else:
                raise AssertionError((method, path))
        elif path == "/networks/" + NETWORK + "/disconnect":
            assert method == "POST" and body == {"Container": module.CONTROLLER, "Force": False}
            self.attached = False
        elif path == "/networks/" + NETWORK:
            if method == "GET":
                if self.network is None:
                    status = 404
                else:
                    value = {**self.network, "Containers": {key: {} for key in set(self.nodes) | self.extra |
                                                            ({module.CONTROLLER} if self.attached else set())}}
            elif method == "DELETE":
                assert not self.nodes and not self.attached and not self.extra
                self.network, status = None, 204
            else:
                raise AssertionError((method, path))
        else:
            raise AssertionError((method, path))
        assert status in kwargs.get("expected", (200,)), (method, path, status)
        self.last_body = json.dumps(value).encode()
        return value, {"status": status, "connection_closed": True}


class ClusterCleanup(unittest.TestCase):
    def fixture(self, root, *, preexisting=False):
        base = root / OWNER
        base.mkdir()
        original = original_value()
        if preexisting:
            original["networks_before"] = [{"Name": "kind", "Id": NETWORK}]
        write_json(base / "original-setup.json", original)
        private = base / "private"
        (private / "tls").mkdir(parents=True)
        paths = [private / "kubeconfig", *(private / "tls" / name for name in ("ca.pem", "client.pem", "client.key"))]
        for path in paths:
            path.write_bytes(("synthetic " + path.name).encode())
        network = {"Name": "kind", "Id": NETWORK, "Created": "2026-09-11T00:00:00Z", "Driver": "bridge"}
        boot = {"schema": "latent.optimization.kubernetes-bootstrap.v1", "owner": OWNER,
                "output": str(base), "controller_id": module.CONTROLLER,
                "nodes": {row["role"]: row for row in original["nodes"]},
                "original_setup": reference(base / "original-setup.json", base),
                "network_id": NETWORK, "network_identity": module._network_identity(network),
                "network_created_by_setup": not preexisting, "controller_original_networks": {"existing": OTHER},
                "private_credentials": [reference(path, base) for path in paths]}
        write_json(base / "bootstrap.json", boot)
        return SimpleNamespace(bootstrap=base / "bootstrap.json", output=base / "cleanup-01"), FakeEngine(original["nodes"], network), paths

    def run_cleanup(self, root, args, engine):
        with patch.object(module, "BENCH_ROOT", root), patch.object(module, "Engine", return_value=engine), \
                patch.object(module, "source", return_value={"clean": True}), redirect_stdout(io.StringIO()):
            status = module.cleanup(args, root)
        return status, json.loads((args.output / "cleanup.json").read_bytes())

    def test_only_recorded_nodes_are_removed_then_hash_matched_credentials(self):
        for preexisting in (False, True):
            with self.subTest(preexisting=preexisting), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                args, engine, credentials = self.fixture(root, preexisting=preexisting)
                status, result = self.run_cleanup(root, args, engine)
                self.assertEqual(status, 0)
                self.assertEqual(len(result["nodes_removed"]), 2)
                self.assertEqual(result["network_removed"], not preexisting)
                self.assertTrue(all(not path.exists() for path in credentials))
                self.assertEqual(result["credentials_removed"][-1]["path"], "private/kubeconfig")
                self.assertTrue(args.bootstrap.exists() and (args.bootstrap.parent / "original-setup.json").exists())
                deletions = [path for method, path, _ in engine.calls if method == "DELETE"]
                self.assertTrue(all(path.startswith("/containers/") or path == "/networks/" + NETWORK for path in deletions))

    def test_foreign_member_wrong_alias_or_crossed_node_prevents_all_mutation(self):
        for change in ("member", "alias", "node", "credential"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                args, engine, credentials = self.fixture(root)
                if change == "member":
                    engine.extra.add("9" * 64)
                elif change == "alias":
                    engine.alias = "unrelated-alias"
                elif change == "node":
                    engine.nodes["2" * 64]["Config"]["Labels"]["io.x-k8s.kind.cluster"] = "unrelated"
                else:
                    credentials[1].write_bytes(b"changed credential")
                status, result = self.run_cleanup(root, args, engine)
                self.assertEqual(status, 1)
                self.assertIsNotNone(result["failure"])
                self.assertTrue(all(method == "GET" for method, _, _ in engine.calls))
                self.assertTrue(all(path.exists() for path in credentials))

    def test_failed_stop_retains_credentials_and_original_error_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args, engine, credentials = self.fixture(root)
            engine.fail = "/stop?t=30"
            status, result = self.run_cleanup(root, args, engine)
            self.assertEqual(status, 1)
            self.assertEqual(result["nodes_removed"], [])
            self.assertTrue(all(path.exists() for path in credentials))
            rows = [json.loads(line) for line in (args.output / "cleanup.ndjson").read_bytes().splitlines()]
            self.assertEqual(rows[-1]["response"], module.blob(b"original engine error"))
            self.assertEqual(rows[-1]["receipt"]["status"], 500)


if __name__ == "__main__":
    unittest.main()
