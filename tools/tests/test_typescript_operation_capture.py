"""Compiler operation capture source; no native/component qualification."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptOperationCaptureTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_exact_id_retirement_identity_and_order_survive_realms_and_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("operation_capture.mjs", "fetch_bindings.mjs", "async_waiters.mjs"):
                (root / name).write_bytes((ROOT / "tools/typescript_guest" / name).read_bytes())
            (root / "test.mjs").write_bytes(
                (ROOT / "tools/tests/fixtures/typescript_fetch/operation-capture.mjs").read_bytes())
            result = subprocess.run([shutil.which("node"), str(root / "test.mjs")],
                                    capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
