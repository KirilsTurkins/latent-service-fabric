from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "check_tool_versions.py"
SPEC = importlib.util.spec_from_file_location("check_tool_versions", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(versions)


class VersionParsingTests(unittest.TestCase):
    def test_extracts_versions(self) -> None:
        self.assertEqual(
            versions.extract(r"\bgo(\d+\.\d+\.\d+)\b", "go version go1.23.2 linux/amd64", "Go"),
            "1.23.2",
        )
        self.assertEqual(
            versions.extract(r"^Version\s+(\S+)$", "Version 5.8.3", "TypeScript"),
            "5.8.3",
        )
        self.assertEqual(
            versions.extract(
                r"^clang version (\d+\.\d+\.\d+)",
                "clang version 21.1.0 (Zig 0.16.0)",
                "Zig C frontend",
            ),
            "21.1.0",
        )

    def test_parses_temurin_runtime_version(self) -> None:
        output = """
            java.vendor = Eclipse Adoptium
            java.runtime.version = 21.0.11+10-LTS
        """
        self.assertEqual(versions.java_runtime_version(output), "21.0.11+10-LTS")
        self.assertEqual(versions.normalize_temurin_runtime("21.0.11+10-LTS"), "21.0.11+10")

    def test_exact_version_mismatch_fails(self) -> None:
        with self.assertRaises(versions.VersionError):
            versions.require_exact("Zig", "0.15.2", "0.16.0")


if __name__ == "__main__":
    unittest.main()
