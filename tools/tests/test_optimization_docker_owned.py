"""Resource sums, lost-create recovery, and exact destructive ownership checks."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from tools.optimization_docker import model, owned
from tools.optimization_evidence.common import EvidenceError


class Engine:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.last_body = b""
        self.calls = []

    def request(self, method, path, body=None, **options):
        self.calls.append((method, path, body))
        status, value = next(self.responses)
        if isinstance(value, BaseException):
            raise value
        self.last_body = json.dumps(value).encode() if value is not None else b""
        if status not in options.get("expected", (200,)):
            raise ValueError("unexpected status")
        return value, {"status": status, "connection_closed": True}


class Tests(unittest.TestCase):
    def test_every_density_has_one_shared_aggregate_budget(self):
        for density in model.DENSITIES:
            native, lsf = model.resources("native", density), model.resources("lsf", density)
            for key in ("cpu_quota", "memory", "pids_limit"):
                self.assertEqual(native[key] * density, lsf[key])
            self.assertEqual(native["memory"], native["memory_swap"])
        self.assertEqual(model.resources("native", 32)["cpu_quota"], 12500)
        with self.assertRaises(EvidenceError):
            model.resources("native", True)

    def test_population_and_rotated_position_alternate_without_extra_offers(self):
        for profile, total in (("smoke", 300), ("full", 9926)):
            plan = model.plan(profile)
            self.assertEqual(int(plan["logical_offers"]), total)
            self.assertEqual(sum(p["offers"] for groups in plan["groups"] for g in groups for p in g["phases"]), total)
            self.assertEqual([g["density"] for g in plan["groups"][0]], [1, 1, 8, 8, 32, 32])
        self.assertEqual([g["density"] for g in model.groups("full", 1)], [8, 8, 32, 32, 1, 1])
        self.assertEqual([g["arm"] for g in model.groups("full", 1)], ["native", "lsf", "lsf", "native", "native", "lsf"])

    def test_config_uses_exact_private_network_and_volume_subpaths(self):
        config = owned.configuration("sha256:" + "a" * 64, ["--app", "native"], arm="native", density=32,
                                     network="b" * 64, mounts=[owned.mount("owned", "run/output", "/output")],
                                     owner="run", role="app")
        self.assertNotIn("PortBindings", config["HostConfig"])
        self.assertTrue(config["HostConfig"]["ReadonlyRootfs"])
        self.assertEqual(config["HostConfig"]["MemorySwap"], 64 * 1024**2)
        # Docker cannot start a local logger with compression and only one file.
        self.assertEqual(config["HostConfig"]["LogConfig"]["Config"], {
            "max-size": "8m", "max-file": "1", "compress": "false"})
        with self.assertRaises(EvidenceError):
            owned.mount("owned", "../foreign", "/output")

    def test_only_seed_containers_can_share_controller_loopback(self):
        arguments = dict(arm="lsf", density=8, network="b" * 64, mounts=[], owner="run",
                         role="seed-d8", network_namespace="c" * 64)
        config = owned.configuration("sha256:" + "a" * 64, [], **arguments)
        self.assertEqual(config["HostConfig"]["NetworkMode"], "container:" + "c" * 64)
        self.assertEqual(config["NetworkingConfig"], {"EndpointsConfig": {}})
        self.assertEqual(config["Hostname"], "")
        for role in ("p0-g0-lsf-0", "client-p0", "seed-d32"):
            with self.assertRaises(EvidenceError):
                owned.configuration("sha256:" + "a" * 64, [], **{**arguments, "role": role})

    def test_cleanup_reconciles_pending_container_after_two_lost_responses(self):
        identifier = "a" * 64
        config = {"Labels": {owned.LABEL: "run", owned.ROLE: "app"}, "Image": "sha256:" + "b" * 64}
        inspect = {"Id": identifier, "Name": "/run-app", "Config": {"Labels": config["Labels"]},
                   "Image": config["Image"], "State": {"Running": False, "ExitCode": 0, "OOMKilled": False}}
        engine = Engine([(404, {}), (500, TimeoutError("lost-create")), (500, TimeoutError("lost-reconcile")),
                         (200, inspect), (200, inspect), (200, {"StatusCode": 0}), (200, inspect),
                         (200, inspect), (204, None), (404, {})])
        with tempfile.TemporaryDirectory() as temporary:
            fleet = owned.Fleet(engine, Path(temporary), "run", time.monotonic_ns() + 10**9)
            with self.assertRaises(TimeoutError):
                fleet.create(config, "app")
            cleanup = fleet.close()
            self.assertEqual(cleanup["errors"], [])
            self.assertEqual(cleanup["pending_names"], [])
            self.assertEqual(cleanup["containers"][0]["container_id"], identifier)
            self.assertEqual(sum(method == "DELETE" for method, _, _ in engine.calls), 1)

    def test_pending_foreign_labels_never_authorize_deletion(self):
        engine = Engine([(200, {"Id": "a" * 64, "Name": "/run-app", "Config": {"Labels": {}}})])
        with tempfile.TemporaryDirectory() as temporary:
            fleet = owned.Fleet(engine, Path(temporary), "run", time.monotonic_ns() + 10**9)
            fleet.pending_names["app"] = {"name": "run-app", "config": {"Labels": {owned.LABEL: "run"}}}
            result = fleet.close()
            self.assertTrue(result["errors"])
            self.assertFalse(any(method == "DELETE" for method, _, _ in engine.calls))


if __name__ == "__main__":
    unittest.main()
