"""Packaged declarations and response policy retain their exact finite contracts."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import build_dev_frontend as frontend
from tools.dev_workflow.common import DevError, digest


class FrontendPreflightPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-preflight-package-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def archive(self, name="helper.pyz"):
        selected = self.root / name
        frontend.helper(selected)
        return selected

    def test_helper_preserves_all_four_canonical_resources_and_deterministic_identity(self):
        first, second = self.archive("first.pyz"), self.archive("second.pyz")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            resources = [name for name in archive.namelist() if name.startswith("tools/dev_workflow/data/")]
            self.assertEqual(set(resources), {"tools/dev_workflow/data/" + name for name in frontend.PREFLIGHT_RESOURCES})
            self.assertIn("tools/browser_response_ownership.py", archive.namelist())
            for name, raw in frontend.preflight_resources():
                installed = "tools/dev_workflow/data/" + name
                self.assertEqual(archive.read(installed), raw)
                self.assertEqual(digest(archive.read(installed)), digest((frontend.ROOT / name).read_bytes()))
                self.assertEqual(archive.getinfo(installed).external_attr >> 16, 0o100644)
            self.assertNotIn("tools/native_runtime/windows.py", archive.namelist())

    def test_isolated_zip_declarations_reject_context_and_headers_without_state(self):
        archive = self.archive()
        code = ("import json,pathlib,sys; sys.path.insert(0,sys.argv[1]); "
            "from tools.dev_workflow import composition_contract as contract; "
            "from tools import browser_response_ownership as response; "
            "assert not pathlib.Path(contract.__file__).is_file(); "
            "assert contract.input_schema()['$id'].endswith('/dev-composition-input.schema.json'); "
            "assert contract.support_matrix()['executionAuthorized'] is False; "
            "assert contract._document(contract.CAPTURE_SCHEMA_PATH)['properties']['nodeCapacity']['const']=='not-observed'; "
            "assert response.table()['schemaVersion']=='latent.browser.response-ownership.v1'; "
            "from tools.dev_workflow import preflight; print(json.dumps(preflight.run(json.loads(sys.argv[2]))))")
        for name, value, expected, reason in frontend.preflight_smoke_cases():
            with self.subTest(case=name):
                completed = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(archive), json.dumps(value)],
                    cwd=self.root, env={**os.environ, "PYTHONPATH": str(frontend.ROOT)},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=True)
                self.assertEqual(completed.stderr, b"")
                result = json.loads(completed.stdout)
                self.assertEqual(result["passed"], expected == 0)
                for flag in ("fullyChecked", "executionAuthorized", "grantCreated", "reservationCreated", "trafficEnabled"):
                    self.assertFalse(result[flag])
                if reason:
                    self.assertTrue(any(row["code"] == reason and row["state"] in {"unsupported", "failed"}
                        for row in result["checks"]))
        self.assertEqual(set(self.root.iterdir()), {archive})

    def test_missing_zip_policy_fails_finitely_without_checkout_fallback(self):
        original, altered = self.archive(), self.root / "missing-policy.pyz"
        missing = "tools/dev_workflow/data/contracts/http/browser-response-ownership-v1.json"
        with zipfile.ZipFile(original) as source, zipfile.ZipFile(altered, "w") as target:
            for name in source.namelist():
                if name != missing:
                    target.writestr(name, source.read(name))
        code = ("import sys; sys.path.insert(0,sys.argv[1]); from tools import browser_response_ownership as response; "
            "\ntry: response.table()\nexcept ValueError as error: print(str(error))\nelse: raise AssertionError('missing policy accepted')")
        completed = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(altered)],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(frontend.ROOT)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=True)
        self.assertEqual(completed.stdout.strip(), b"response-ownership-contract-not-packaged")
        self.assertEqual(completed.stderr, b"")

    def test_snapshot_rejects_missing_empty_or_oversized_canonical_contract_before_packaging(self):
        with patch.object(frontend, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "^frontend-preflight-contract-required$"):
                frontend.preflight_resources()
            first = self.root / frontend.PREFLIGHT_RESOURCES[0]
            first.parent.mkdir(parents=True)
            for raw in (b"", b"x" * 65537):
                first.write_bytes(raw)
                with self.assertRaisesRegex(DevError, "^frontend-preflight-contract-bound$"):
                    frontend.preflight_resources()
        self.assertFalse((self.root / "helper.pyz").exists())

    def test_packaged_smoke_never_accepts_authority_claim_as_structural_evidence(self):
        false = {name: False for name in ("fullyChecked", "executionAuthorized", "grantCreated",
            "reservationCreated", "trafficEnabled")}
        for claimed in false:
            result = {"schemaVersion": "latent.dev.result.v1", "code": "success", "result": {
                "schemaVersion": "latent.composition.preflight.v1", "passed": True, "checks": [],
                **false, claimed: True}}
            code = "import sys; sys.stdout.write(" + repr(json.dumps(result)) + ")"
            with self.subTest(claimed=claimed), self.assertRaisesRegex(DevError, "^packaged-frontend-preflight-authority-failed$"):
                frontend.preflight_smoke([sys.executable, "-I", "-B", "-c", code])


if __name__ == "__main__":
    unittest.main()
