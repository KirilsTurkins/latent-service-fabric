"""Closed shared provider fixtures; not a replacement for real-node acceptance."""
import base64
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tools.phase2_operator_process import WorkflowError, startup_diagnostic, write_json
from tools.phase3_http_fixture import request
from tools.phase3_management_scenario import (
    MEDIA_TYPE, PROVIDER_CREDENTIAL, configure_provider_node, installed_descriptors,
    invocation_budget, invoke_guest,
)
from tools.run_phase3_management_workflow import inspection


def descriptors():
    return [{"id": name, "tenant": "tests", "service": f"{name}-host", "capability": capability,
             "profile": profile, "configurationDigest": "sha256:" + "a" * 64, "configurationEpoch": "1"}
            for name, capability, profile in (
                ("http", "latent:http/client@0.2.0", "bounded-http-v1"),
                ("blob", "latent:blob/blob@0.2.0", "linux-immutable-blobs-v1"))]


class MemoryConnection:
    def __init__(self, data):
        self.data = data
        self.output = bytearray()

    def settimeout(self, value):
        self.timeout = value

    def recv(self, maximum):
        result, self.data = self.data[:maximum], self.data[maximum:]
        return result

    def sendall(self, data):
        self.output.extend(data)


class ProviderWorkflowTests(unittest.TestCase):
    def test_startup_failure_keeps_only_closed_node_stage_and_code(self):
        self.assertEqual(startup_diagnostic(b"latentd: startup: unavailable\n"), "startup-unavailable")
        self.assertEqual(startup_diagnostic(b"latentd: configuration: invalid-argument\r\n"),
                         "configuration-invalid-argument")
        for value in (b"", b"x" * 161, b"latentd: private-value: unavailable\n",
                      b"latentd: startup: private-value\n", b"latentd: startup: unavailable\nprivate\n"):
            self.assertEqual(startup_diagnostic(value), "unavailable")

    def test_node_configuration_keeps_credentials_out_of_public_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, node = root / "fixture", root / "node"
            fixture.mkdir()
            node.mkdir()
            write_json(fixture / "policy.json", {"formatVersion": 1})
            path = configure_provider_node(node, fixture, 32123)
            encoded = path.read_bytes()
            config = json.loads(encoded)
            self.assertNotIn(PROVIDER_CREDENTIAL, encoded)
            self.assertEqual((node / "provider-credentials/authorization").read_bytes(), PROVIDER_CREDENTIAL)
            self.assertEqual(config["supplyChain"]["mode"], "enforced")
            self.assertEqual(config["budgetProfile"]["mode"], "phase3")
            self.assertEqual(config["providers"]["http"]["configuration"]["destinations"][0]["resolution"],
                             {"kind": "static", "addresses": ["127.0.0.1"]})
            self.assertEqual(config["providers"]["blob"]["namespace"], "workflow")
            self.assertEqual(len(config["providers"]["bindings"]), 2)
            self.assertFalse((node / "data").exists())
            with self.assertRaises(FileExistsError):
                configure_provider_node(node, fixture, 32123)

    def test_only_actual_installed_profiles_and_canonical_identity_are_accepted(self):
        valid = descriptors()
        self.assertEqual(set(installed_descriptors(SimpleNamespace(startup_record={"providers": valid}))),
                         {"http", "blob"})
        for field, value in (("tenant", "foreign"), ("profile", "streaming-http-v1"),
                             ("service", "other"), ("configurationEpoch", 1),
                             ("configurationDigest", "sha256:" + "A" * 64),
                             ("configurationDigest", "sha256:" + "a" * 64 + "\n"),
                             ("capability", "latent:http/client@0.3.0"), ("credential", "PRIVATE")):
            invalid = copy.deepcopy(valid)
            invalid[0][field] = value
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                installed_descriptors(SimpleNamespace(startup_record={"providers": invalid}))
        with self.assertRaises(WorkflowError):
            installed_descriptors(SimpleNamespace(startup_record={"providers": [valid[0], valid[0]]}))

    def test_explicit_invocation_budgets_fit_the_http_and_blob_capsules(self):
        http, blob = invocation_budget("http"), invocation_budget("blob")
        self.assertEqual(http["cpuFuel"], 10000000000)
        self.assertEqual(http["outboundRequests"], 8)
        self.assertEqual(http["blobReadBytes"], 0)
        self.assertEqual(http["blobWriteBytes"], 0)
        self.assertEqual(blob["blobReadBytes"], 65536)
        self.assertEqual(blob["blobWriteBytes"], 65536)

    def test_invocation_is_one_call_with_lossless_u64_inputs_and_closed_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(directory=Path(temporary), calls=0, call=Mock())
            target = {"service": "generic", "route": "guest-blob", "contract": "tests:local-blobs/api@1.0.0",
                      "function": "run", "budget": invocation_budget("blob")}
            payload = {"encoding": "base64", "mediaType": MEDIA_TYPE,
                       "data": base64.b64encode(b'["18446744073709551615"]').decode("ascii")}
            client.call.return_value = {"category": "success", "data": {"payload": payload}}
            self.assertEqual(invoke_guest(client, target, 4, handle=18446744073709551615)[1],
                             18446744073709551615)
            client.call.assert_called_once()
            self.assertEqual(client.call.call_args.args[:3], ("--rpc-timeout-ms", "5000", "invoke"))
            self.assertIn("phase3", client.call.call_args.args)
            self.assertEqual(json.loads((client.directory / "invoke-0.json").read_bytes()),
                             [4, "", "18446744073709551615"])
            for ordinal, output in enumerate(("18446744073709551616", "01", "-1", "1\n", "\u0661"), 1):
                client.calls = ordinal
                payload["data"] = base64.b64encode(json.dumps([output]).encode()).decode("ascii")
                with self.subTest(output=output), self.assertRaisesRegex(WorkflowError, "provider-output-value"):
                    invoke_guest(client, target, 0)

    def test_http_fixture_checks_credential_and_counts_denied_requests_without_echo(self):
        for method in (b"GET", b"HEAD", b"POST"):
            connection = MemoryConnection(method + b" /allowed HTTP/1.1\r\nHost: localhost\r\nAuthorization: "
                                          + PROVIDER_CREDENTIAL + b"\r\nContent-Length: 1\r\n\r\n\x07")
            self.assertEqual(request(connection), (True, True))
            self.assertEqual(connection.timeout, 2)
            self.assertTrue(connection.output.startswith(b"HTTP/1.1 201 Created"))
            self.assertNotIn(PROVIDER_CREDENTIAL, connection.output)
            self.assertEqual(connection.output.split(b"\r\n\r\n", 1)[1], b"" if method == b"HEAD" else b"ok")
        connection = MemoryConnection(b"GET /denied HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertEqual(request(connection), (False, False))
        self.assertTrue(connection.output.startswith(b"HTTP/1.1 403 Forbidden"))

    def test_inspection_can_repeat_after_restart_without_replacing_client_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(directory=Path(temporary), calls=0, call=Mock())
            targets = {name: {"route": f"guest-{name}"} for name in ("http", "blob")}
            page = {"data": {"executionPermission": False, "capabilities": [{}], "revision": {"revisionId": "same"}}}
            allowed = {"data": {"allowed": True, "executionPermission": False}}
            denied = {"data": {"allowed": False, "executionPermission": False}}

            def call(*arguments):
                client.calls += 1
                return (page, page, allowed, denied)[(client.calls - 1) % 4]

            client.call.side_effect = call
            self.assertEqual(inspection(client, targets, 32123), inspection(client, targets, 32123))
            self.assertEqual(client.calls, 8)
            self.assertEqual(len(list(client.directory.glob("resource-*.json"))), 4)

    def test_http_fixture_rejects_oversize_duplicate_and_incomplete_input(self):
        for data in (b"x" * 8193, b"GET / HTTP/1.1\r\nHost: one\r\nHost: two\r\n\r\n",
                     b"POST / HTTP/1.1\r\nContent-Length: 4097\r\n\r\n",
                     b"POST / HTTP/1.1\r\nContent-Length: 1\r\n\r\n"):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                request(MemoryConnection(data))


if __name__ == "__main__":
    unittest.main()
