"""SDK operation ownership controls; callback descriptors are not native receipts."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptFetchOperationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_typed_mapping_backpressure_abort_and_failed_retirement_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("http-body.mjs", "http-headers.mjs", "http-objects.mjs", "http-fetch.mjs"):
                (root / name).write_bytes((ROOT / "sdk/typescript-guest/runtime" / name).read_bytes())
            (root / "test.mjs").write_bytes(
                (ROOT / "tools/tests/fixtures/typescript_fetch/fetch-operations.mjs").read_bytes())
            result = subprocess.run([shutil.which("node"), str(root / "test.mjs")],
                                    capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
