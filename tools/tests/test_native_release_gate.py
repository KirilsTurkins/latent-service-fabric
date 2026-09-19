"""Release identity and real-receipt gates; no publication or network calls."""

import copy
import unittest
from unittest.mock import patch

from tools.native_release_gate import require_remote_tag, reviewed_ci, select_predecessor
from tools.native_runtime.common import InstallError
from tools.native_runtime.verify import RELEASE_WORKFLOW, REPOSITORY


class ReleaseGateTests(unittest.TestCase):
    def test_remote_tag_must_resolve_boundedly_to_exact_commit(self):
        commit = "a" * 40
        tag = "b" * 40
        with patch("tools.native_release_gate.github", side_effect=[{"object": {"type": "tag", "sha": tag}},
                                                                  {"object": {"type": "commit", "sha": commit}}]):
            require_remote_tag("0.1.0-native-test.1", commit)
        for reference in ({"object": {"type": "commit", "sha": tag}}, {"object": {"type": "blob", "sha": commit}},
                          {"object": {"type": "tag", "sha": tag}}):
            with patch("tools.native_release_gate.github", return_value=reference), self.assertRaises(InstallError):
                require_remote_tag("0.1.0-native-test.1", commit)

    def test_only_successful_maintained_exact_head_ci_is_accepted(self):
        commit = "a" * 40
        run = {"head_sha": commit, "status": "completed", "conclusion": "success", "event": "push",
               "path": ".github/workflows/ci.yml", "head_repository": {"full_name": REPOSITORY}}
        reviewed_ci(run, commit)
        for field, value in (("head_sha", "b" * 40), ("status", "in_progress"), ("conclusion", "skipped"),
                             ("path", ".github/workflows/untrusted.yml"), ("event", "pull_request_target"),
                             ("head_repository", {"full_name": "attacker/fork"})):
            with self.subTest(field=field), self.assertRaises(InstallError):
                reviewed_ci({**run, field: value}, commit)

    def test_native_predecessor_must_be_committed_and_release_workflow_bound(self):
        previous = {"version": "0.1.0-native-test.1", "sourceCommit": "a" * 40, "archiveSha256": "b" * 64}
        compatibility = {"upgradeFrom": [previous]}
        run = {"path": RELEASE_WORKFLOW, "event": "workflow_dispatch", "head_sha": previous["sourceCommit"],
               "head_repository": {"full_name": REPOSITORY}}
        self.assertEqual(select_predecessor(run, compatibility), previous)
        for invalid in ({"upgradeFrom": []}, {"upgradeFrom": [previous, copy.deepcopy(previous)]}):
            with self.assertRaises(InstallError):
                select_predecessor(run, invalid)
        with self.assertRaises(InstallError):
            select_predecessor({**run, "path": ".github/workflows/native-runtime.yml"}, compatibility)


if __name__ == "__main__":
    unittest.main()
