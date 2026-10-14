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
    def test_repeatable_fixture_recipe_keeps_original_baseline_and_exact_two_gate_revisions(self):
        from tools.java_capsule_project import ROOT
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for invalid in (True, 0, 65536):
                selected = root / ("invalid-" + str(invalid))
                with self.assertRaises(ValueError):
                    project.create_fixtures(selected, invalid)
                self.assertFalse(selected.exists())
            fixtures = project.create_fixtures(root / "sources", 32195)
            files = {label: snapshot(path) for label, path in fixtures.items()}
            baseline = files["baseline"]
            self.assertEqual(baseline["src/dev/latent/app/Server.java"],
                             (ROOT / "sdk/java-guest/tests/server/Server.java").read_bytes())
            self.assertEqual(baseline["src/outside/developer/routes/Router.java"],
                             (ROOT / "sdk/java-guest/tests/server/Router.java").read_bytes())
            self.assertNotIn("src/outside/developer/routes/LifecycleRoutes.java", baseline)
            declarations = {label: validate(source)[0] for label, source in files.items()}
            self.assertEqual(declarations["baseline"]["limits"]["outboundRequests"], 0)
            for label in ("first", "second"):
                self.assertEqual(declarations[label]["limits"],
                                 {**declarations["baseline"]["limits"], "outboundRequests": 1})
                self.assertEqual(declarations[label]["service"], "examples/lifecycle-server")
                self.assertEqual({name: value for name, value in files[label].items() if name.startswith("vendor/")},
                                 {name: value for name, value in baseline.items() if name.startswith("vendor/")})
            self.assertEqual(len({value["name"] for value in declarations.values()}), 3)
            self.assertEqual(files["second"]["src/outside/developer/routes/LifecycleRoutes.java"],
                files["first"]["src/outside/developer/routes/LifecycleRoutes.java"].replace(b'"Hey!"', b'"Revision-two"'))

    def test_native_capture_rejects_development_graph_and_changed_executable_bytes(self):
        import json
        import shutil
        from unittest.mock import patch
        from tools.qualify_java_server_lifecycle_suite import PRODUCTS, native
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = []
            for name, (target, kind) in PRODUCTS.items():
                binary = root / name
                binary.write_bytes(b"source-test executable fixture, not runtime proof")
                rows.append({"reason": "compiler-artifact", "target": {"name": target, "kind": [kind]},
                             "features": [], "executable": str(binary)})
            rows.append({"reason": "build-finished", "success": True})
            class Commands:
                environment = {}
                def run(self, stage, *arguments):
                    if stage in {"source-head", "source-tree"}:
                        return b"1" * 40
                    if stage == "default-native-build":
                        self.command = arguments
                        return "\n".join(map(json.dumps, rows)).encode()
                    return b""
            commands = Commands()
            with patch("tools.qualify_java_server_lifecycle_suite.source_identity", return_value={"test": "source-only"}), \
                    patch("tools.qualify_java_server_lifecycle_suite.resolve_tools", return_value=({"cargo": "cargo", "rustc": "rustc"}, [])):
                passed = root / "passed"
                passed.mkdir()
                directory, receipt = native(commands, passed, {})
                self.assertNotIn("--features", commands.command)
                value = json.loads(receipt.read_text())
                self.assertEqual(set(value["binaries"]), set(PRODUCTS))
                for name in PRODUCTS:
                    self.assertEqual((directory / name).read_bytes(), (root / name).read_bytes())
                rows[1]["features"] = ["development-test-node"]
                denied = root / "denied"
                denied.mkdir()
                with self.assertRaisesRegex(ValueError, "native-default-product"):
                    native(commands, denied, {})
                self.assertFalse((denied / "native/native-tuple.json").exists())
                rows[1]["features"] = []
                changed = root / "changed"
                changed.mkdir()
                copy = shutil.copyfile
                def change_after_copy(source, destination):
                    result = copy(source, destination)
                    source.write_bytes(b"different shared-target build")
                    return result
                with patch("tools.qualify_java_server_lifecycle_suite.shutil.copyfile", side_effect=change_after_copy):
                    with self.assertRaisesRegex(ValueError, "native-capture-changed"):
                        native(commands, changed, {})
                self.assertFalse((changed / "native/native-tuple.json").exists())

    def test_gate_request_is_a_separate_exact_declaration_and_preserves_all_original_other_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = snapshot(project.create(root / "zero", name="lifecycle-server", revision="Hey!", peer_port=32195))
            gate = snapshot(project.create(root / "gate", name="lifecycle-server", revision="Hey!", peer_port=32195,
                                           service="examples/lifecycle-server", outbound_requests=1))
            selected, _lock, _pins = validate(gate)
            baseline, _lock, _pins = validate(original)
            self.assertEqual(baseline["limits"]["outboundRequests"], 0)
            self.assertEqual(selected["limits"], {**baseline["limits"], "outboundRequests": 1})
            self.assertEqual({name: value for name, value in original.items() if name != "capsule-project.json"},
                             {name: value for name, value in gate.items() if name != "capsule-project.json"})
            for invalid in (True, -1, 2):
                destination = root / ("invalid-" + str(invalid))
                with self.assertRaises(ValueError):
                    project.create(destination, name="lifecycle-server", revision="Hey!", peer_port=32195,
                                   outbound_requests=invalid)
                self.assertFalse(destination.exists())

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
                          actual["src/outside/developer/routes/LifecycleRoutes.java"])
            self.assertNotIn(b"dev.latent.guest", actual["src/dev/latent/app/Server.java"])

    def test_original_helper_routes_and_every_body_case_are_retained_with_exact_revision_delta(self):
        from tools.java_capsule_project import ROOT
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = snapshot(project.create(root / "first", name="lifecycle-server", revision="Hey!", peer_port=32123))
            second = snapshot(project.create(root / "second", name="lifecycle-server", revision="Revision-two", peer_port=32123))
            original_server = (ROOT / "sdk/java-guest/tests/server/Server.java").read_bytes()
            extended = first["src/dev/latent/app/Server.java"]
            self.assertEqual(extended.replace(b"        outside.developer.routes.LifecycleRoutes.install(server);\n", b""),
                             original_server)
            original_router = (ROOT / "sdk/java-guest/tests/server/Router.java").read_bytes()
            name = "src/outside/developer/routes/Router.java"
            self.assertEqual(first[name], original_router)
            self.assertEqual(second[name], original_router.replace(b'"Hey!".getBytes(StandardCharsets.UTF_8)',
                                                                  b'"Revision-two".getBytes(StandardCharsets.UTF_8)'))
            self.assertEqual(first["sdk-lock.json"], second["sdk-lock.json"])
            self.assertEqual(first["capsule-project.json"], second["capsule-project.json"])
            self.assertEqual(first["wit/world.wit"], second["wit/world.wit"])
            self.assertEqual(second["src/outside/developer/routes/LifecycleRoutes.java"],
                first["src/outside/developer/routes/LifecycleRoutes.java"].replace(b'"Hey!"', b'"Revision-two"'))

    def test_journal_pin_uses_actual_catalog_generation_independently_of_deployment_stamp(self):
        from copy import deepcopy
        from tools.java_server_lifecycle import execution_pin, status
        from tools.tests.test_server_source import fixture
        selected = fixture()[-1]
        self.assertEqual(selected["deploymentGeneration"], "17")
        class Catalog:
            generation = "42"
            observed_generation = "42"
            def call(inner, *args):
                if args == ("route", "get"):
                    data = {"snapshot": {"tenant": selected["tenant"], "generation": inner.generation,
                        "snapshotDigest": "sha256:" + "9" * 64, "services": [{"tenant": selected["tenant"],
                        "routeId": selected["route"], "service": selected["service"], "revisions": [{
                            "revisionId": selected["revision"], "releaseDigest": selected["componentDigest"], "weight": 10000}]}]}}
                else:
                    data = {"activationId": "actual-http-root", "metadata": {"revision": selected["revision"],
                        "release": selected["componentDigest"], "route-generation": inner.observed_generation},
                        "terminalState": "completed", "finalConsumption": {"cpuFuel": "100"}}
                return {"category": "success", "outcomeKnown": True, "data": deepcopy(data)}
        catalog = Catalog()
        expected = execution_pin(catalog, selected)
        self.assertEqual(expected["catalogGeneration"], "42")
        self.assertEqual(expected["selected"]["deploymentGeneration"], "17")
        catalog.generation = "61"  # Later catalog writes must not replace the accepted pin.
        self.assertEqual(status(catalog, "actual-http-root", expected, terminal="completed")["metadata"]["route-generation"], "42")
        for bad in ("17", "61"):
            catalog.observed_generation = bad
            with self.assertRaisesRegex(ValueError, "original-resolved-pin-changed"):
                status(catalog, "actual-http-root", expected, terminal="completed")

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
        self.assertEqual(http["limits"]["maximumChunkBytes"], 4096)
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
                "wasmtimeVersion": "48.0.6", "binaries": {"latentd": {
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

    def test_explicit_http_binding_precedes_first_publication_and_policy_refresh_has_its_own_cas(self):
        import json
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            class Client:
                directory = Path(temporary)
                def call(self, *arguments):
                    path = Path(arguments[arguments.index("--file") + 1])
                    calls.append((arguments, json.loads(path.read_text())))
                    return {"category": "success", "outcomeKnown": True, "data": {"policy": {
                        "id": "server-gate-http-allow", "tenant": "examples", "revoked": False,
                        "generation": "9" if len(calls) == 2 else "17"}}}
            node = SimpleNamespace(startup_record={"providers": [{"id": "server-gate-http",
                "capability": "latent:http/streaming@0.3.0", "profile": "bounded-streaming-http-identity-v1",
                "tenant": "examples", "configurationDigest": "sha256:" + "1" * 64}]})
            observer = RevisionControls(Path("signed-two"), Path("build-two"),
                                        second_body=b"Revision-two", peer_port=32195)
            client = Client()
            observer.grant_initial_http(client, node, "examples/lifecycle-server", "publication:first")
            self.assertEqual(len(calls), 2)
            self.assertIn("install-server-gate-http", calls[0][0])
            self.assertEqual(calls[1][1]["rules"][0]["publications"], ["publication:first"])
            self.assertEqual(calls[1][1]["rules"][0]["resources"]["methods"], ["GET"])
            self.assertEqual(calls[1][1]["rules"][0]["resources"]["paths"], ["/gate"])
            observer.grant_http(client, node, "examples/lifecycle-server", ["publication:first", "publication:second"])
            self.assertEqual(len(calls), 3, "the installed provider binding is not submitted again")
            arguments = calls[2][0]
            self.assertEqual(arguments[arguments.index("--expected-generation") + 1], "9")
            self.assertIn("refresh-server-gate-http", arguments)
            self.assertEqual(calls[2][1]["rules"][0]["publications"], ["publication:first", "publication:second"])
            with self.assertRaisesRegex(ValueError, "initialization-once"):
                observer.grant_initial_http(client, node, "examples/lifecycle-server", "publication:first")
            self.assertEqual(len(calls), 3)

    def test_qualifier_requires_all_original_cases_before_a_distinct_fresh_lifecycle_node(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        from tools.qualify_java_server_lifecycle import main
        from tools.rust_capsule_project import inventory
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_server(root / "source", "baseline")
            build = root / "baseline-build"
            build.mkdir()
            (build / "source-inputs.json").write_bytes(inventory(snapshot(source)))
            for label in ("first", "second"):
                selected = root / (label + "-build")
                selected.mkdir()
                (selected / "http-client-profile.json").write_text(json.dumps({
                    "profile": "lsf.java.httpurlconnection.streaming.v1", "limits": {"chunkBytes": 4096}}))
            arguments = []
            for name in ("binary", "node", "tls-tool", "native-tuple", "baseline-fixture",
                         "first-fixture", "second-fixture"):
                arguments.extend(["--" + name, str(root / name)])
            arguments += ["--baseline-source", str(source), "--baseline-build", str(build),
                "--first-build", str(root / "first-build"), "--second-build", str(root / "second-build"),
                "--peer-port", "32195"]
            baseline = {"status": "passed", "http": [None] * 52}
            lifecycle = {"status": "passed", "http": [], "lifecycle": {"cases": []}}
            with patch("tools.qualify_java_server_lifecycle.ordinary_tuple", return_value={"test": "source-only"}), \
                    patch("tools.qualify_java_server_lifecycle.run", side_effect=[baseline, lifecycle]) as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([*arguments, "--output", str(root / "passed")]), 0)
            self.assertEqual(len(run.call_args_list), 2)
            first, second = run.call_args_list
            self.assertEqual(first.args[-1], root / "passed/baseline")
            self.assertEqual(second.args[-1], root / "passed/lifecycle")
            self.assertNotIn("lifecycle", first.kwargs)
            self.assertIsInstance(second.kwargs["lifecycle"], RevisionControls)
            receipt = json.loads((root / "passed/lifecycle-qualified.json").read_text())
            self.assertEqual(len(receipt["baseline"]["http"]), 52)
            for status, count in (("failed", 52), ("passed", 51), ("passed", 53)):
                output = root / (status + str(count))
                with patch("tools.qualify_java_server_lifecycle.ordinary_tuple", return_value={"test": "source-only"}), \
                        patch("tools.qualify_java_server_lifecycle.run", return_value={"status": status, "http": [None] * count}) as run:
                    with self.assertRaisesRegex(ValueError, "complete-original-ingress"):
                        main([*arguments, "--output", str(output)])
                self.assertEqual(run.call_count, 1)
                self.assertFalse((output / "lifecycle-qualified.json").exists())


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
