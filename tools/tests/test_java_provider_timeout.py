"""Fixture contracts and real peer ownership, separate from node qualification."""
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from tools.java_capsule_project import create, validate
from tools.java_http_composition import provider_timeout as campaign
from tools.phase2_operator_process import WorkflowError
from tools.phase3_management_scenario import PROVIDER_CREDENTIAL, http_provider
from tools.rust_capsule_project import ROOT, digest, read_json, snapshot
from tools import sdk_provider_http_fixture as peer


class JavaProviderTimeoutTests(unittest.TestCase):
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
                             before["wit/world.wit"].decode().split("interface api {", 1)[1].split("world typed-domain", 1)[0])
            descriptor, lock, _ = validate(after)
            self.assertEqual(descriptor["limits"]["outboundRequests"], 1)
            self.assertEqual(lock["template"]["sourceDigest"], digest(after["src/dev/latent/app/Capsule.java"]))
            self.assertEqual(observation["templateDigest"], digest((ROOT / "sdk/java-guest/templates/http-status.java").read_bytes()))
            with self.assertRaises(WorkflowError):
                campaign.adapt_domain(project)

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
