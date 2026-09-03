from __future__ import annotations

import unittest

from tools.tests.phase0_test_environment import (
    is_phase0_rejected_build_override,
    sanitized_phase0_environment,
)


class Phase0TestEnvironmentTests(unittest.TestCase):
    def test_sanitizes_fixed_and_patterned_build_overrides(self) -> None:
        environment = sanitized_phase0_environment(
            {
                "PATH": "/test/bin",
                "CARGO_HOME": "/test/cargo",
                "CARGO_INCREMENTAL": "0",
                "CARGO_PROFILE_RELEASE_LTO": "thin",
                "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER": "clang",
                "X86_64_UNKNOWN_LINUX_GNU_CC": "clang",
            }
        )

        self.assertEqual(
            environment,
            {"PATH": "/test/bin", "CARGO_HOME": "/test/cargo"},
        )

    def test_explicit_rejection_tests_can_add_an_override_after_sanitizing(self) -> None:
        environment = sanitized_phase0_environment({"PATH": "/test/bin"})
        environment["CARGO_INCREMENTAL"] = "1"

        self.assertTrue(is_phase0_rejected_build_override("CARGO_INCREMENTAL"))
        self.assertEqual(environment["CARGO_INCREMENTAL"], "1")


if __name__ == "__main__":
    unittest.main()
