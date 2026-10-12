"""Body source and callback ownership controls; no installed fetch qualification."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptFetchBodyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_finite_body_consumption_matches_native_reference(self):
        self.run_node("body-reference.mjs")

    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_native_body_seam_waits_for_retirement_before_resource_drop(self):
        self.run_node("body-ownership.mjs")

    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_request_response_objects_match_reference_and_keep_owned_bodies(self):
        self.run_node("objects-reference.mjs")

    def run_node(self, fixture):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("http-body.mjs", "http-headers.mjs", "http-objects.mjs"):
                (root / name).write_bytes((ROOT / "sdk/typescript-guest/runtime" / name).read_bytes())
            (root / "test.mjs").write_bytes(
                (ROOT / "tools/tests/fixtures/typescript_fetch" / fixture).read_bytes()
            )
            result = subprocess.run([shutil.which("node"), str(root / "test.mjs")],
                                    capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
