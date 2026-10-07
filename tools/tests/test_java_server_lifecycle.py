"""Actual local peer/source controls, distinct from signed-node acceptance."""
from pathlib import Path
import socket
import tempfile
import time
import unittest

from tools import java_server_lifecycle_project as project
from tools.java_capsule_project import validate
from tools.java_server_lifecycle_peer import GatePeer
from tools.java_server_lifecycle import RevisionControls
from tools.java_server_project import create_server
from tools.rust_capsule_project import snapshot


class ServerLifecycleInputs(unittest.TestCase):
    def test_outside_source_declares_http_explicitly_without_sdk_or_budget_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = snapshot(create_server(root / "baseline", "lifecycle-server"))
            actual = snapshot(project.create(root / "actual", name="lifecycle-server",
                                              revision="Hey!", peer_port=32123))
            selected, lock, _pins = validate(actual)
            original, original_lock, _pins = validate(baseline)
            self.assertEqual(lock, original_lock)
            self.assertEqual(selected["limits"], original["limits"])
            self.assertEqual(selected["limits"]["cpuFuel"], 1_000_000_000)
            self.assertEqual(selected["limits"]["memoryBytes"], 67_108_864)
            self.assertEqual(selected["limits"]["wallTimeLimitMillis"], 120000)
            self.assertEqual({k: v for k, v in actual.items() if k.startswith("vendor/")},
                             {k: v for k, v in baseline.items() if k.startswith("vendor/")})
            self.assertIn(b"import latent:http/streaming@0.3.0", actual["wit/world.wit"])
            self.assertIn(b"new URL(\"http://127.0.0.1:32123/gate\")",
                          actual["src/dev/latent/app/Server.java"])
            self.assertNotIn(b"dev.latent.guest", actual["src/dev/latent/app/Server.java"])

    def test_unreviewed_revision_and_peer_are_rejected_before_project_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "outside"
            for revision, port in (("arbitrary source", 32123), ("Hey!", 0), ("Hey!", True), ("Hey!", 65536)):
                with self.subTest(revision=revision, port=port), self.assertRaises(ValueError):
                    project.create(destination, name="lifecycle-server", revision=revision, peer_port=port)
                self.assertFalse(destination.exists())

    def test_node_configuration_keeps_existing_limits_and_requires_exact_http_owner(self):
        from tools.java_server_node import runtime_config
        from tools.tests.test_node_providers_schema import VALIDATOR
        settings = {"cells": [{"capacity": 1, "maximumMemoryBytes": 67108864}],
            "execution": {"maximumWallTimeMillis": 120000},
            "httpIngress": {"authentication": {"origins": []}}}
        runtime_config(settings, "examples/lifecycle-server")
        observer = RevisionControls(Path("signed-two"), Path("build-two"),
                                    second_body=b"Revision-two", peer_port=32123)
        observer.configure(settings, "examples/lifecycle-server")
        observer.configure_ingress(settings)
        VALIDATOR.validate(settings["providers"])
        self.assertEqual(settings["cells"], [{"capacity": 1, "maximumMemoryBytes": 67108864}])
        self.assertEqual(settings["execution"], {"maximumWallTimeMillis": 120000})
        http = settings["providers"]["httpStreaming"]
        self.assertEqual(http["configuration"]["destinations"][0]["origin"],
                         {"scheme": "http", "host": "127.0.0.1", "port": 32123})
        self.assertEqual(http["configuration"]["destinations"][0]["redirectDestinations"], [])
        self.assertEqual(settings["providers"]["bindings"][-1]["contract"], "latent:http/streaming@0.3.0")
        self.assertEqual(settings["httpIngress"]["authentication"]["origins"],
                         [{"authority": "competing.server.test", "subject": "server-caller", "tenant": "examples"}])

    def test_qualifier_rejects_development_tuple_and_changed_native_product_before_node(self):
        import hashlib
        import json
        from tools.qualify_java_server_lifecycle import ordinary_tuple
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "owned-binary"
            executable.write_bytes(b"actual source-test bytes, not a native qualification")
            identity = hashlib.sha256(executable.read_bytes()).hexdigest()
            tuple_path = root / "tuple.json"
            value = {"status": "passed", "features": [], "tupleRole": "ordinary-defaults",
                "head": "1" * 40, "tree": "2" * 40, "hostAbiProfile": "lsf-host-abi-phase3-v5",
                "wasmtimeVersion": "48.0.4", "binaries": {"latentd": {
                    "actualExecutableSha256": identity, "bytes": executable.stat().st_size, "actualFeatures": []}}}
            tuple_path.write_text(json.dumps(value), encoding="utf-8")
            actual = ordinary_tuple(tuple_path, {"latentd": executable})
            self.assertEqual(actual["tupleRole"], "ordinary-defaults")
            value["features"] = ["latentd/development-test-node"]
            tuple_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "genuine-default-tuple"):
                ordinary_tuple(tuple_path, {"latentd": executable})
            value["features"] = []
            value["binaries"]["latentd"]["actualFeatures"] = ["development-test-node"]
            tuple_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "development-product-not-default"):
                ordinary_tuple(tuple_path, {"latentd": executable})
            value["binaries"]["latentd"]["actualFeatures"] = []
            tuple_path.write_text(json.dumps(value), encoding="utf-8")
            executable.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "native-product-mismatch"):
                ordinary_tuple(tuple_path, {"latentd": executable})


class ServerLifecyclePeer(unittest.TestCase):
    def connect(self, peer):
        connection = socket.create_connection(("127.0.0.1", peer.port), timeout=2)
        self.addCleanup(connection.close)
        connection.sendall(f"GET /gate HTTP/1.1\r\nHost: 127.0.0.1:{peer.port}\r\n\r\n".encode())
        peer.wait(peer.started)
        return connection

    def test_explicit_release_sends_one_reply_without_claiming_receipt(self):
        with GatePeer(time.monotonic() + 5) as peer:
            connection = self.connect(peer)
            connection.settimeout(.05)
            with self.assertRaises(TimeoutError):
                connection.recv(1)
            peer.release.set()
            connection.settimeout(2)
            actual = bytearray()
            while part := connection.recv(1024):
                actual.extend(part)
            self.assertEqual(bytes(actual), b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\nConnection: close\r\n\r\nG")
            self.assertEqual(peer.snapshot(), {"acceptedRequests": 1, "sentReplies": 1,
                "remoteReceiptConfirmed": False, "physicalPeerCloseObserved": False})
        self.assertFalse(peer.thread.is_alive())

    def test_remote_disconnect_retires_original_peer_without_reply_or_retry(self):
        with GatePeer(time.monotonic() + 5) as peer:
            connection = self.connect(peer)
            connection.shutdown(socket.SHUT_RDWR)
            connection.close()
            peer.wait(peer.closed)
            self.assertEqual(peer.snapshot(), {"acceptedRequests": 1, "sentReplies": 0,
                "remoteReceiptConfirmed": False, "physicalPeerCloseObserved": True})
        self.assertFalse(peer.thread.is_alive())

    def test_owned_stop_reaps_pending_listener_without_accepted_work(self):
        peer = GatePeer(time.monotonic() + 5)
        peer.close()
        self.assertEqual(peer.accepted, 0)
        self.assertFalse(peer.thread.is_alive())
        self.assertEqual(peer.listener.fileno(), -1)


if __name__ == "__main__":
    unittest.main()
