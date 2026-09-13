"""Keep shared exception/owner identity despite older tools-path import setup."""
from pathlib import Path
import os
import sys
import tempfile
import unittest

from tools.build_process import run_bounded


ROOT = Path(__file__).resolve().parents[2]


class BuildImportTests(unittest.TestCase):
    def test_tools_path_and_legacy_spec_loader_cannot_split_shared_module_identity(self):
        program = """
from pathlib import Path
import importlib
import importlib.util
import sys
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "tools"))
sys.path.append(str(root))
legacy_snapshot = importlib.import_module("build_snapshot")
from tools import build_snapshot, build_observation, build_provenance, build_echo_capsule, build_process
from tools import reset_validation_echo
assert legacy_snapshot is not build_snapshot
assert build_observation.SnapshotError is build_snapshot.SnapshotError
assert build_provenance.SnapshotError is build_snapshot.SnapshotError
assert reset_validation_echo.SnapshotError is build_snapshot.SnapshotError
assert build_provenance.echo is build_echo_capsule
assert build_snapshot.run_bounded is build_process.run_bounded
spec = importlib.util.spec_from_file_location("build_echo_capsule", root / "tools/build_echo_capsule.py")
legacy_echo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy_echo)
assert legacy_echo.BuildProcessError is build_process.BuildProcessError
assert legacy_echo.owned_child is build_snapshot.owned_child
print("canonical imports passed")
"""
        with tempfile.TemporaryDirectory() as temporary:
            result = run_bounded([sys.executable, "-c", program, str(ROOT)],
                Path(temporary), dict(os.environ), 30, 4096)
        self.assertEqual(result.stdout, b"canonical imports passed\r\n" if os.name == "nt"
                         else b"canonical imports passed\n")

    def test_direct_cli_entrypoints_work_outside_repository_current_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("build_provenance.py", "build_echo_capsule.py", "reset_validation_echo.py"):
                with self.subTest(script=name):
                    result = run_bounded([sys.executable, str(ROOT / "tools" / name), "--help"],
                        Path(temporary), dict(os.environ), 30, 8192)
                    self.assertIn(b"usage:", result.stdout)


if __name__ == "__main__":
    unittest.main()
