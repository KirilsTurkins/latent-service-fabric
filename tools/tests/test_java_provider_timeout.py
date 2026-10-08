"""Fixture contracts and real peer ownership, separate from node qualification."""
from pathlib import Path
import hashlib
import json
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools.java_capsule_project import create, validate
from tools.java_http_composition import build as composition_build, provider_timeout as campaign
from tools.phase2_operator_process import WorkflowError
from tools.phase3_management_scenario import PROVIDER_CREDENTIAL, http_provider
from tools.rust_capsule_project import ROOT, digest, read_json, snapshot
from tools import sdk_provider_http_fixture as peer


class JavaProviderTimeoutTests(unittest.TestCase):
    def http_observation(self, directory, status, body, discovered):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(3)
        errors, requests = [], []

        def serve():
            try:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(3)
                    received = b""
                    while b"\r\n\r\n" not in received:
                        chunk = connection.recv(4096)
                        self.assertTrue(chunk)
                        received += chunk
                        self.assertLessEqual(len(received), 65536)
                    headers, request_body = received.split(b"\r\n\r\n", 1)
                    content_length = [line.split(b":", 1)[1].strip()
                                      for line in headers.split(b"\r\n")[1:]
                                      if line.split(b":", 1)[0].lower() == b"content-length"]
                    self.assertEqual(len(content_length), 1)
                    required_bytes = int(content_length[0])
                    self.assertGreaterEqual(required_bytes, 0)
                    self.assertLessEqual(len(headers) + 4 + required_bytes, 65536)
                    while len(request_body) < required_bytes:
                        chunk = connection.recv(min(4096, required_bytes - len(request_body)))
                        self.assertTrue(chunk)
                        request_body += chunk
                    self.assertEqual(len(request_body), required_bytes)
                    requests.append(received.split(b"\r\n", 1)[0])
                    connection.sendall(f"HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=serve)
        worker.start()
        before, calls = [], []
        observed_tree = {"historyAvailable": True, "nextPageToken": None, "nodes": discovered}

        def call(*arguments):
            calls.append(arguments)
            if arguments[:2] == ("activation", "roots"):
                rows = before if len(calls) == 1 else discovered[:1]
                return {"data": {"schemaVersion": 1, "retainedHistoryOnly": True, "nodes": rows, "nextPageToken": None}}
            self.assertEqual(arguments[:3], ("activation", "tree", discovered[0]["activationId"]))
            return {"data": observed_tree}

        client = SimpleNamespace(evidence=directory, deadline=time.monotonic() + 5,
            cancellation=SimpleNamespace(check=lambda: None), call=call)
        try:
            with self.assertRaisesRegex(WorkflowError, "java-provider-composed-response"):
                campaign._observe(client, f"fixture.invalid:{server.getsockname()[1]}", 12345)
        finally:
            worker.join(3)
            server.close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(requests, [b"POST /api/text HTTP/1.1"])
        return json.loads((directory / "java-provider-http-observation-00.json").read_bytes()), calls

    def test_failed_http_response_retains_bounded_digest_and_authorized_closed_child_before_assertion(self):
        with tempfile.TemporaryDirectory() as temporary:
            body = b"private-source-secret-token"
            nodes = [{"activationId": "authorized-root", "parentActivationId": None},
                     {"activationId": "authorized-child", "parentActivationId": "authorized-root",
                      "diagnosticIsTerminal": True, "diagnostic": {"stage": 1, "reason": 9}}]
            observed, calls = self.http_observation(Path(temporary), 503, body, nodes)
            self.assertEqual((observed["httpStatus"], observed["responseBytes"]), (503, len(body)))
            self.assertEqual(observed["responseDigest"], "sha256:" + hashlib.sha256(body).hexdigest())
            self.assertEqual(observed["tree"]["nodes"], nodes)
            self.assertEqual(observed["externalMutationDisposition"], "unknown")
            self.assertNotIn(body.decode(), json.dumps(observed))
            self.assertEqual(len(calls), 3)

    def test_oversized_http_response_retains_existing_read_bound_without_inventing_a_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            body = b"x" * 32769
            observed, calls = self.http_observation(Path(temporary), 200, body, [])
            self.assertEqual((observed["httpStatus"], observed["responseBytes"]), (200, 32769))
            self.assertEqual(observed["responseDigest"], "sha256:" + hashlib.sha256(body).hexdigest())
            self.assertIsNone(observed["tree"])
            self.assertEqual(observed["authorizedRootsAfter"], [])
            self.assertEqual(observed["externalMutationDisposition"], "unknown")
            self.assertEqual(len(calls), 2)

    def domain(self, directory):
        project = create(directory, "greeting", "java-http-domain")
        for target, source in (("src/dev/latent/app/Capsule.java", "Capsule.java"), ("wit/world.wit", "world.wit")):
            (project / target).write_bytes((ROOT / "examples/java-http-composition/domain" / source).read_bytes())
        return project

    def test_adaptation_uses_actual_http_template_and_preserves_vendor_exports_and_ordinary_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = self.domain(Path(temporary) / "domain")
            before = snapshot(project)
            observation = campaign.adapt_domain(project)
            after = snapshot(project)
            self.assertEqual({k: v for k, v in before.items() if k.startswith("vendor/")},
                             {k: v for k, v in after.items() if k.startswith("vendor/")})
            source = after["src/dev/latent/app/Capsule.java"].decode()
            self.assertIn('if (!value.startsWith("provider-fixture:")) return value;', source)
            self.assertIn("Bindings.LatentHttpClient.send(request)", source)
            self.assertIn("Option.some(new Unsigned64(250))", source)
            self.assertEqual(source.count("private Result<Integer"), 1)
            wit = after["wit/world.wit"].decode()
            self.assertEqual(wit.count("import latent:http/client@0.2.0;"), 1)
            self.assertEqual(wit.split("interface api {", 1)[1].split("world typed-domain", 1)[0],
                             before["wit/world.wit"].decode().replace("text: func(value: string) -> string;",
                                 "text: async func(value: string) -> string;").split("interface api {", 1)[1].split("world typed-domain", 1)[0])
            descriptor, lock, _ = validate(after)
            self.assertEqual(descriptor["limits"]["outboundRequests"], 1)
            self.assertEqual(lock["template"]["sourceDigest"], digest(after["src/dev/latent/app/Capsule.java"]))
            self.assertEqual(observation["templateDigest"], digest((ROOT / "sdk/java-guest/templates/http-status.java").read_bytes()))
            with self.assertRaises(WorkflowError):
                campaign.adapt_domain(project)

    def test_missing_synchronous_text_export_rejects_before_any_project_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = self.domain(Path(temporary) / "domain")
            path = project / "wit/world.wit"
            path.write_bytes(path.read_bytes().replace(b"text: func", b"text: async func"))
            before = snapshot(project)
            with self.assertRaisesRegex(WorkflowError, "java-provider-domain-adaptation-shape"):
                campaign.adapt_domain(project)
            self.assertEqual(snapshot(project), before)

    def test_diagnostic_build_observes_async_text_before_generation_and_keeps_ordinary_build_sync(self):
        with tempfile.TemporaryDirectory() as temporary:
            for diagnostics in (False, True):
                output = Path(temporary) / str(diagnostics)
                output.mkdir()
                expected = "text: " + ("async " if diagnostics else "") + "func(value: string) -> string;"
                events, built = [], {}

                def generated(domain, selection, destination):
                    self.assertIn(expected, (domain / "wit/world.wit").read_text())
                    self.assertEqual(read_json(domain / "capsule-project.json")["limits"]["outboundRequests"], int(diagnostics))
                    events.append("generate")
                    project = create(destination, "greeting", "java-http-adapter")
                    (project / "src/dev/latent/app/Capsule.java").write_text('class Capsule { String marker = "route-not-selected"; }')
                    descriptor = read_json(project / "capsule-project.json")
                    descriptor["limits"]["cpuFuel"] = composition_build.SPIN_CPU_FUEL
                    (project / "capsule-project.json").write_text(json.dumps(descriptor))
                    return project

                def checked(domain, selection, adapter):
                    self.assertIn(expected, (domain / "wit/world.wit").read_text())
                    events.append("check")

                def qualified(domain, selection, adapter, evidence):
                    self.assertEqual(events, ["generate", "check"])
                    self.assertIn(expected, (domain / "wit/world.wit").read_text())
                    events.append("probes")

                def compiled(project, destination, *arguments):
                    self.assertEqual(events, ["generate", "check", "probes"])
                    built[project.name] = snapshot(project)
                    return destination

                with patch.object(composition_build, "generate", autospec=True, side_effect=generated), \
                     patch.object(composition_build, "check", autospec=True, side_effect=checked), \
                     patch.object(composition_build, "qualify_generation", autospec=True, side_effect=qualified), \
                     patch.object(composition_build, "build", autospec=True, side_effect=compiled):
                    composition_build.compile_pair(output, Path("wasi-sdk"), {"examples/capsule_contracts": Path("contracts")},
                                                   diagnostics=diagnostics)
                self.assertEqual(set(built), {"domain", "context-required", "adapter", "adapter-next"})
                self.assertEqual(built["adapter"]["wit/world.wit"], built["adapter-next"]["wit/world.wit"])
                for name in ("adapter", "adapter-next"):
                    self.assertEqual(json.loads(built[name]["capsule-project.json"])["limits"]["outboundRequests"], 2 if diagnostics else 0)
                self.assertEqual((output / "diagnostic-adaptations.json").exists(), diagnostics)
                if diagnostics:
                    observations = read_json(output / "diagnostic-adaptations.json")
                    self.assertEqual(observations["domain"]["witDigest"], digest(built["domain"]["wit/world.wit"]))

    def test_adapter_changes_only_declared_outbound_allowance_before_compiler_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / "adapter", "greeting", "java-http-adapter")
            before = snapshot(project)
            result = campaign.adapt_adapter(project)
            after = snapshot(project)
            changed = {name for name in before if before[name] != after[name]}
            self.assertEqual(changed, {"capsule-project.json"})
            descriptor = read_json(project / "capsule-project.json")
            self.assertEqual(descriptor["limits"]["outboundRequests"], 2)
            self.assertEqual(result["descriptorDigest"], digest(after["capsule-project.json"]))
            with self.assertRaises(WorkflowError):
                campaign.adapt_adapter(project)

    def test_common_provider_configuration_is_same_bounded_owner_and_never_replaces_existing_http(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "common").mkdir()
            common = http_provider(root / "common", "examples", 12345)
            (root / "java").mkdir()
            settings = {"budgetProfile": {"mode": "phase3", "maximumOutboundRequests": 0},
                        "providers": {"formatVersion": 1, "bindings": []}}
            adapted = campaign.configure(root / "java", settings, 12345)
            self.assertEqual(adapted["providers"]["http"], common)
            self.assertEqual(settings["budgetProfile"]["maximumOutboundRequests"], 0)
            self.assertNotIn("http", settings["providers"])
            self.assertEqual(adapted["budgetProfile"]["maximumOutboundRequests"], 2)
            self.assertEqual(adapted["providers"]["bindings"][0]["consumerService"], campaign.DOMAIN)
            with self.assertRaises(WorkflowError):
                campaign.configure(root / "java", adapted, 12345)

    def test_actual_received_get_and_physical_socket_close_publish_distinct_complete_markers(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sending, receiving = socket.socketpair()
            deadline, errors = time.monotonic() + 2, []

            def serve():
                try:
                    method, authorized, allowed = peer.request(receiving, deadline)
                    if not authorized or not allowed:
                        raise ValueError("unexpected actual peer request")
                    peer.observe_held_get(method, directory, campaign.MODE)
                    peer.hold(receiving, directory, campaign.MODE, deadline)
                except BaseException as error:
                    errors.append(error)

            worker = threading.Thread(target=serve)
            worker.start()
            try:
                self.assertFalse((directory / ("get-" + campaign.MODE)).exists())
                sending.sendall(b"GET /allowed HTTP/1.1\r\nAuthorization: " + PROVIDER_CREDENTIAL + b"\r\n\r\n")
                started = directory / ("started-" + campaign.MODE)
                while not started.exists():
                    self.assertLess(time.monotonic(), deadline)
                    self.assertFalse(errors)
                    time.sleep(.001)
                self.assertEqual(started.read_bytes(), b"observed\n")
                self.assertEqual((directory / ("get-" + campaign.MODE)).read_bytes(), b"observed\n")
                self.assertFalse((directory / ("closed-" + campaign.MODE)).exists())
                sending.close()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual((directory / ("closed-" + campaign.MODE)).read_bytes(), b"observed\n")
            finally:
                sending.close()
                receiving.close()
                worker.join(3)

    def test_actual_non_get_cannot_publish_a_get_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            sending, receiving = socket.socketpair()
            try:
                sending.sendall(b"POST /allowed HTTP/1.1\r\nAuthorization: " + PROVIDER_CREDENTIAL + b"\r\n\r\n")
                method, authorized, allowed = peer.request(receiving, time.monotonic() + 2)
                self.assertTrue(authorized and allowed)
                with self.assertRaises(ValueError):
                    peer.observe_held_get(method, directory, campaign.MODE)
                self.assertEqual(list(directory.iterdir()), [])
            finally:
                sending.close()
                receiving.close()

    def test_only_finite_nonterminal_provider_timeout_counts_and_absence_remains_unavailable(self):
        self.assertEqual(campaign.timeout_observation({"diagnostic": None}), "unavailable")
        for stage, reason, terminal in ((6, 13, False), (2, 14, False), (6, 13, True), ("6", 13, False),
                                       (6, "13", False), (6, True, False), (999, 13, False)):
            expected = "observed" if (stage, reason, terminal) == (6, 13, False) else "unexpected"
            self.assertEqual(campaign.timeout_observation({"diagnostic": {"stage": stage, "reason": reason},
                                                          "diagnosticIsTerminal": terminal}), expected)

    def test_shutdown_requires_original_reaped_report_and_every_known_pool_counter(self):
        counters = ("controlOwners", "connections", "pendingRequests", "runningRequests", "workers", "cleanupJobs",
            "failedCleanup", "sessions", "handles", "calls", "results", "ioCalls", "ioRetainedBytes",
            "blobStages", "blobHandles", "blobWork")
        report = {"clean": True, **dict.fromkeys(counters, 0)}
        shutdown = {"reaped": True, "record": {"clean": True, "report": {"providers": report}}}
        self.assertTrue(campaign.verify_shutdown(shutdown)["clean"])
        managed = {"state": "stopped", "reaped": True, "cleanShutdown": True, "providerShutdown": report}
        self.assertEqual(campaign.verify_managed_shutdown(managed), campaign.verify_shutdown(shutdown))
        for field in counters:
            report[field] = 1
            with self.assertRaises(WorkflowError):
                campaign.verify_shutdown(shutdown)
            with self.assertRaises(WorkflowError):
                campaign.verify_managed_shutdown(managed)
            report[field] = 0
        shutdown["reaped"] = False
        with self.assertRaises(WorkflowError):
            campaign.verify_shutdown(shutdown)
        managed["cleanShutdown"] = False
        with self.assertRaises(WorkflowError):
            campaign.verify_managed_shutdown(managed)


if __name__ == "__main__":
    unittest.main()
