"""Canonical host tools retain strict captured-input path and namespace controls."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import captured_compiler_isolation as compiler
from tools.application_dependency_store import DependencyError
from tools.build_observation import file_identity
from tools.build_process import run_bounded_result


@unittest.skipUnless(sys.platform == "linux", "Actual compiler host namespace tools require Linux")
class CanonicalCompilerHostTools(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="compiler-host-alias-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "selected"
        self.workspace.mkdir()
        self.sandbox = Path(shutil.which("bwrap")).resolve(strict=True)
        self.loader = Path(shutil.which("ldd")).resolve(strict=True)
        self.cat = Path(shutil.which("cat")).resolve(strict=True)

    def test_host_directory_aliases_bind_canonical_tool_bytes_before_namespace_execution(self):
        aliases = {"bwrap": self.root / "host-bin", "ldd": self.root / "host-observer"}
        aliases["bwrap"].symlink_to(self.sandbox.parent, target_is_directory=True)
        aliases["ldd"].symlink_to(self.loader.parent, target_is_directory=True)
        selected = {"bwrap": str(aliases["bwrap"] / self.sandbox.name),
                    "ldd": str(aliases["ldd"] / self.loader.name)}
        with patch.object(compiler.shutil, "which", side_effect=selected.get):
            boundary = compiler.Isolation(self.workspace, {"cat": self.cat}, {})
        self.assertEqual(boundary.sandbox, self.sandbox)
        self.assertEqual(boundary.receipt["sandbox"], file_identity(self.sandbox, "build-sandbox"))
        self.assertEqual(boundary.receipt["loaderObserver"], file_identity(self.loader, "loader-dependency-observer"))
        for alias in aliases.values():
            alias.unlink()
            alias.symlink_to(self.root / "unused-host-directory", target_is_directory=True)
        source = self.workspace / "selected.bin"
        source.write_bytes(b"canonical selected bytes")
        environment = {"PATH": os.defpath}
        command = boundary.wrap(self.cat, [str(source)], self.workspace, environment)
        self.assertEqual(command[0], str(self.sandbox))
        self.assertFalse(any(str(alias) in argument for alias in aliases.values() for argument in command))
        result = run_bounded_result(command, self.workspace, environment, 5, 16384)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"canonical selected bytes")
        boundary.check_unchanged()

    def test_explicit_captured_workspace_executable_and_distribution_links_remain_denied(self):
        distribution = self.root / "distribution"
        distribution.mkdir()
        (distribution / "selected.bin").write_bytes(b"selected compiler input")
        workspace_link, tool_link, distribution_link = (self.root / name for name in
                                                        ("workspace-link", "tool-link", "distribution-link"))
        workspace_link.symlink_to(self.workspace, target_is_directory=True)
        tool_link.symlink_to(self.cat)
        distribution_link.symlink_to(distribution, target_is_directory=True)
        selected = {"bwrap": str(self.sandbox), "ldd": str(self.loader)}
        for workspace, tools, distributions in ((workspace_link, {"cat": self.cat}, {}),
                                                (self.workspace, {"cat": tool_link}, {}),
                                                (self.workspace, {"cat": self.cat}, {"sdk": distribution_link})):
            with self.subTest(workspace=workspace, tools=tools, distributions=distributions), \
                    patch.object(compiler.shutil, "which", side_effect=selected.get), \
                    self.assertRaisesRegex(DependencyError, "dependency-link-denied"):
                compiler.Isolation(workspace, tools, distributions)


if __name__ == "__main__":
    unittest.main()
