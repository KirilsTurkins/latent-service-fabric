"""Retained command receipts are diagnostics, never successful build claims."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.build_process import BuildProcessError
from tools.java_capsule_build import retain_logs
from tools.java_guest.compiler import Compiler


class Diagnostics(unittest.TestCase):
    def test_failed_initialization_commands_keep_exit_and_cleanup_receipts(self):
        for outcome in (subprocess.CompletedProcess(["java"], 7, b"", b"compiler failure"),
                        BuildProcessError("command-deadline")):
            with self.subTest(outcome=type(outcome).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                compiler = Compiler.__new__(Compiler)
                compiler.directory = root / "compiler"
                compiler.directory.mkdir()
                compiler.deadline = time.monotonic() + 30
                compiler.paths, compiler.environment = {}, {}
                compiler.records, compiler.retained_bytes = [], 0
                mocked = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch("tools.java_guest.compiler.run_bounded_result", **mocked):
                    with self.assertRaises((ValueError, BuildProcessError)):
                        compiler.run("java-version", "java", "-version")
                output = root / "output"
                output.mkdir()
                retain_logs(compiler.directory, output)
                record = json.loads((output / "compiler-logs/0-java-version.command.json").read_bytes())
                self.assertEqual(record["command"], ["java", "-version"])
                self.assertEqual(record["exitCode"], None if isinstance(outcome, Exception) else 7)
                if isinstance(outcome, Exception):
                    self.assertEqual(record["processFailure"], "command-deadline")
                else:
                    self.assertIn(b"compiler failure", (output / "compiler-logs/0-java-version.log").read_bytes())


if __name__ == "__main__": unittest.main()
