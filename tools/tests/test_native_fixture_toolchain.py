"""Compiler-free wiring check; real Rust execution stays in its owning test."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools.tests import test_local_tests as owner


class NativeFixtureToolchainTests(unittest.TestCase):
    def test_independent_additions_fixture_pins_toolchain_before_first_cargo_command(self):
        class BeforeCompilation(Exception):
            pass

        observed = []

        def command(args, **kwargs):
            if args[0] == "cargo":
                root = Path(kwargs["cwd"])
                observed.append((root / "rust-toolchain.toml").read_bytes())
                self.assertNotEqual(root, owner.ROOT)
                self.assertEqual(args, ("cargo", "generate-lockfile", "--offline"))
                raise BeforeCompilation
            self.assertEqual(args[0], "git")
            return ""

        fixture = owner.NativeEntrypointTests(
            "test_real_rust_independent_additions_merge_and_run_through_local_owner")
        with patch.object(subprocess, "check_output", side_effect=command), \
                patch.object(subprocess, "run", side_effect=AssertionError("unexpected compiler execution")), \
                self.assertRaises(BeforeCompilation):
            fixture.test_real_rust_independent_additions_merge_and_run_through_local_owner()
        self.assertEqual(observed, [(owner.ROOT / "rust-toolchain.toml").read_bytes()])


if __name__ == "__main__":
    unittest.main()
