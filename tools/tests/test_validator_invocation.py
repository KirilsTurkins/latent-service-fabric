"""Keep validator entry points usable without an inherited tools import path."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOCUSED_TEST = (
    "tools.tests.test_validate_repository."
    "SourceTraversalTests.test_authoritative_source_remains_validated"
)


class ValidatorInvocationTests(unittest.TestCase):
    def run_python(self, *arguments: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
        # A subprocess also avoids sys.path/sys.modules mutations by other tests.
        environment = {
            key: value for key, value in os.environ.items()
            if key.upper() != "PYTHONPATH"
        }
        return subprocess.run(
            [sys.executable, *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    def assert_succeeded(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_focused_repository_unittest_without_pythonpath(self) -> None:
        # Select one existing test, not this module, to avoid recursive execution.
        result = self.run_python("-m", "unittest", FOCUSED_TEST)
        self.assert_succeeded(result)
        self.assertIn("Ran 1 test", result.stderr)
        self.assertIn("OK", result.stderr)

    def test_foundation_script_and_module_without_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            invocations = (
                (("tools/validate_foundation.py",), ROOT),
                (("-m", "tools.validate_foundation"), ROOT),
                ((str(ROOT / "tools/validate_foundation.py"),), Path(temporary)),
            )
            for arguments, cwd in invocations:
                with self.subTest(arguments=arguments, cwd=cwd):
                    result = self.run_python(*arguments, cwd=cwd)
                    self.assert_succeeded(result)
                    self.assertIn("validated build foundation:", result.stdout)
                    self.assertEqual(result.stderr, "")

    def test_package_import_keeps_real_native_loader_without_running_main(self) -> None:
        result = self.run_python(
            "-c",
            "from tools import native_loader_boundary, validate_foundation; "
            "assert validate_foundation.validate_native_loader "
            "is native_loader_boundary.validate; "
            "assert validate_foundation.ERRORS == []",
        )
        self.assert_succeeded(result)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_missing_transitive_dependency_is_not_retried_as_an_import_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copyfile(ROOT / "tools/validate_foundation.py", root / "validate_foundation.py")
            (root / "native_loader_boundary.py").write_text(
                "raise ModuleNotFoundError('missing validator dependency', "
                "name='lsf_validator_dependency_missing')\n",
                encoding="utf-8",
            )
            result = self.run_python("validate_foundation.py", cwd=root)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("ModuleNotFoundError: missing validator dependency", result.stderr)
            self.assertNotIn("During handling of the above exception", result.stderr)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
