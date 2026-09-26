from pathlib import Path
import unittest
from unittest.mock import patch

from tools.security_common import SecurityError, changed_paths


class SecurityChangedPathTests(unittest.TestCase):
    def test_present_base_uses_exact_local_diff_without_network(self):
        with patch("tools.security_common.run", side_effect=[
                (0, b""), (0, b"docs/changed.md\0website/example.mdx\0")]) as command:
            self.assertEqual(changed_paths(Path("source"), "a" * 40, "b" * 40),
                             ["docs/changed.md", "website/example.mdx"])
        self.assertEqual([call.args[0][3] for call in command.call_args_list], ["cat-file", "diff"])
        self.assertIn("a" * 40 + "^{commit}", command.call_args_list[0].args[0])
        self.assertEqual(command.call_args_list[-1].args[0][-3:], ["a" * 40, "b" * 40, "--"])

    def test_missing_base_is_fetched_before_exact_diff(self):
        with patch("tools.security_common.run", side_effect=[(128, b""), (0, b""), (0, b"file\0")]) as command:
            self.assertEqual(changed_paths(Path("source"), "a" * 40, "b" * 40), ["file"])
        self.assertEqual([call.args[0][3] for call in command.call_args_list], ["cat-file", "fetch", "diff"])
        self.assertEqual(command.call_args_list[1].args[0][-2:], ["origin", "a" * 40])

    def test_failed_fetch_still_fails_closed_and_invalid_revisions_never_execute(self):
        with patch("tools.security_common.run", side_effect=[(128, b""), SecurityError("process-timeout")]):
            with self.assertRaisesRegex(SecurityError, "process-timeout"):
                changed_paths(Path("source"), "a" * 40, "b" * 40)
        with patch("tools.security_common.run") as command:
            with self.assertRaisesRegex(SecurityError, "invalid-change-revision"):
                changed_paths(Path("source"), "--untrusted", "b" * 40)
        command.assert_not_called()
