"""Focused closed-input tests; real node/browser receipts are separate evidence."""
import unittest
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace

from tools.phase3_management_scenario import PROVIDER_CREDENTIAL
from tools.phase3_reference_peer import BODY, decode_request
from tools.build_angular_reference import ROOT, stage_variant
from tools.phase2_operator_process import WorkflowError, write_json
from tools.phase3_reference_config import ROUTES, fixtures
from tools.phase3_reference_scenario import invocation_arguments, manifest
from tools.phase3_reference_lifecycle import require_static_cell_bypass


class ReferencePeerTests(unittest.TestCase):
    def test_only_complete_authorized_bounded_get_profile_is_accepted(self):
        request = b"GET /message HTTP/1.1\r\nAuthorization: " + PROVIDER_CREDENTIAL + b"\r\n\r\n"
        self.assertEqual(decode_request(request), (b"/message", True))
        self.assertIsNone(decode_request(request[:-1]))
        self.assertEqual(decode_request(b"GET /slow HTTP/1.1\r\n\r\n"), (b"/slow", False))
        self.assertIn(b"lsf-private-reference-upstream", BODY)

    def test_unbounded_ambiguous_or_body_bearing_requests_are_rejected(self):
        for request in (
            b"x" * 8193,
            b"POST /message HTTP/1.1\r\n\r\n",
            b"GET /unknown HTTP/1.1\r\n\r\n",
            b"GET /message HTTP/1.1\r\nContent-Length: 1\r\n\r\nx",
            b"GET /message HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
            b"GET /message HTTP/1.1\r\nHost: a\r\nhost: b\r\n\r\n",
            b"GET /message HTTP/1.1\r\n" + b"x: y\r\n" * 25 + b"\r\n",
        ):
            with self.subTest(size=len(request)), self.assertRaises(ValueError):
                decode_request(request)


class ReferenceCellBypassTests(unittest.TestCase):
    def test_lease_age_can_advance_without_admitting_a_render(self):
        before = [{"active": 1, "available": 0, "granted": "5", "queueDepth": 0,
                   "oldestLeaseAgeMicros": "100"}]
        after = [{**before[0], "oldestLeaseAgeMicros": "200"}]
        require_static_cell_bypass(before, after)
        for key, value in (("active", 0), ("granted", "6"), ("queueDepth", 1), ("available", 1)):
            with self.subTest(key=key), self.assertRaisesRegex(WorkflowError, "entered-render-cells"):
                require_static_cell_bypass(before, [{**after[0], key: value}])


class ReferenceBuildTests(unittest.TestCase):
    def test_releases_capture_different_maintained_version_sources(self):
        source = ROOT / "examples/angular-reference-application"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            versions = [stage_variant(source, root / name, name) for name in ("green", "blue")]
            self.assertNotEqual(*versions)
            self.assertEqual((root / "green/shared/app.ts").read_bytes(), (root / "blue/shared/app.ts").read_bytes())
            self.assertIn(b"reference-green", (root / "green/shared/version.ts").read_bytes())
            self.assertIn(b"reference-blue", (root / "blue/shared/version.ts").read_bytes())
            self.assertFalse((root / "blue/variants").exists())
            with self.assertRaises(WorkflowError):
                stage_variant(source, root / "invalid", "wrapper")

    def test_reference_fixture_rejects_wrapper_only_releases(self):
        digest_fields = ("packageDigest", "componentDigest", "assetsDigest", "manifestDigest", "sourceSnapshotDigest", "buildObservationDigest")
        records = [{"name": name, "version": "reference-" + name, "service": "angular-reference",
                    "routes": [{"path": route} for route in ROUTES],
                    **{field: "sha256:" + symbol * 64 for field in digest_fields}}
                   for name, symbol in (("green", "a"), ("blue", "b"))]
        document = {"schemaVersion": "latent.angular.reference.fixture.v1", "tenant": "tests",
                    "actualAngularBuilds": True, "reproducibility": "not-checked",
                    "dependencyCompleteness": "declared-inputs-incomplete", "fixtures": records}
        for changed in (None, "componentDigest", "assetsDigest", "sourceSnapshotDigest", "packageDigest"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                value = copy.deepcopy(document)
                if changed:
                    value["fixtures"][1][changed] = value["fixtures"][0][changed]
                write_json(root / "fixture.json", value)
                if changed:
                    with self.assertRaisesRegex(WorkflowError, "wrapper-only"):
                        fixtures(root)
                else:
                    self.assertEqual(set(fixtures(root)[1]), {"green", "blue"})

    def test_reference_inputs_request_one_capability_but_never_claim_principal_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = SimpleNamespace(directory=root, host="reference.test:12345")
            arguments = invocation_arguments(client, "held", "/slow", route=None)
            self.assertNotIn("--route", arguments)
            self.assertEqual(arguments[arguments.index("--budget-profile") + 1], "phase3")
            data = (root / "held-input.json").read_text()
            self.assertNotIn("principal", data)
            self.assertNotIn("tenant", data)
            deployment = manifest({"componentDigest": "sha256:" + "a" * 64, "service": "angular-reference"},
                                  "publication:sha256:" + "b" * 64, "blue", 5000)
            self.assertEqual(deployment["spec"]["resources"]["outboundRequests"], 1)
            self.assertEqual(deployment["spec"]["grants"], [{"capability": "latent:http/client@0.2.0", "policy": "reference-http"}])


if __name__ == "__main__":
    unittest.main()
