"""Release identity and real-receipt gates; no publication or network calls."""

import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.native_release_gate import authenticate_developer_selection, receipts, require_remote_tag, reviewed_ci, select_predecessor
from tools.native_runtime.common import InstallError, encode
from tools.native_runtime.verify import RELEASE_WORKFLOW, REPOSITORY
from tools.select_native_vm_artifact import candidate_source
from tools.tests.test_native_runtime import fixture, policy_fixture


class ReleaseGateTests(unittest.TestCase):
    def test_developer_selection_requires_reviewed_bytes_version_and_release_attestation(self):
        arguments = SimpleNamespace(release_directory=Path("synthetic-release"), version="0.1.0-alpha.4")
        publisher = SimpleNamespace(verifier=Path("independent-gh"), roots=Path("independent-roots"))
        policy = {"workflow": RELEASE_WORKFLOW, "sourceRef": "refs/tags/0.1.0-alpha.4", "sourceCommit": "a" * 40}
        selected = {"schemaVersion": "latent.developer-release-selection.v1", "version": arguments.version,
                    "purpose": "controlled-development-toolkit"}
        with patch("tools.native_release_gate.files.read", return_value=encode(selected)), \
                patch("tools.native_release_gate.execute", return_value=(0, b"{}")) as verification:
            authenticate_developer_selection(arguments, publisher, policy)
            self.assertIn("refs/tags/0.1.0-alpha.4", verification.call_args.args[0])
            self.assertIn("a" * 40, verification.call_args.args[0])
            verification.return_value = (1, b"rejected")
            with self.assertRaisesRegex(InstallError, "attestation-identity-mismatch"):
                authenticate_developer_selection(arguments, publisher, policy)
        with patch("tools.native_release_gate.files.read", side_effect=[encode(selected), b"changed"]), \
                self.assertRaisesRegex(InstallError, "reviewed-developer-selection-changed"):
            authenticate_developer_selection(arguments, publisher, policy)
        for change in ({"version": "0.1.0-alpha.3"}, {"purpose": "server-runtime"}):
            with self.subTest(change=change), \
                    patch("tools.native_release_gate.files.read", return_value=encode({**selected, **change})), \
                    self.assertRaisesRegex(InstallError, "version-and-purpose"):
                authenticate_developer_selection(arguments, publisher, policy)

    def test_receipt_gate_rejects_partial_wrong_artifact_or_diagnostic_only_runs(self):
        manifest, _archive = fixture()
        previous = {"version": "0.1.0-test.0", "sourceCommit": "b" * 40, "archiveSha256": "c" * 64}
        manifest["compatibility"]["upgradeFrom"] = [previous]
        reports = {}
        for profile in ("local-experimental-v1", "external-capsule-v1"):
            phases = ["initial", "retained", "upgrade"] + (["rootless"] if profile == "local-experimental-v1" else [])
            results = [{"phase": phase, "passed": True, "sourceCommit": manifest["sourceCommit"], "kernel": "6.8.0-test"}
                       for phase in phases]
            results[2]["details"] = {"upgrade": {"fromVersion": previous["version"], "fromCommit": previous["sourceCommit"],
                                                "toVersion": manifest["version"], "toCommit": manifest["sourceCommit"],
                                                "unsupportedDowngradeRejected": True}}
            reports[profile] = {"schemaVersion": "latent.native-vm-result.v1", "profile": profile, "purpose": "release",
                                "passed": True, "acceptanceComplete": True, "gaps": [], "sourceCommit": manifest["sourceCommit"],
                                "harnessSourceCommit": manifest["sourceCommit"], "version": manifest["version"],
                                "archiveSha256": manifest["archive"]["sha256"], "initialBootId": "00000000-0000-0000-0000-000000000001",
                                "rebootedBootId": "00000000-0000-0000-0000-000000000002", "guestResults": results,
                                "predecessor": previous, "authentication": {"policy": policy_fixture(manifest)},
                                "image": {"imageSha256": "d" * 64},
                                "guestPrerequisites": {"noGuestPackageInstallation": True, "ghTrustedBeforeBundle": True,
                                                       "sshHostKeyPinnedBeforeBoot": True}}
        selected = "local-experimental-v1"
        with patch("tools.native_release_gate.files.read", side_effect=lambda path, maximum: encode(reports[path.stem])), \
                patch("tools.native_release_gate.files.digest", return_value="e" * 64):
            self.assertEqual(set(receipts(Path("synthetic-structural-receipts"), manifest)), set(reports))
            original = copy.deepcopy(reports[selected])
            for change in ({"passed": False}, {"acceptanceComplete": False}, {"gaps": ["no-compatible-version-pair"]},
                           {"purpose": "candidate"}, {"harnessSourceCommit": "f" * 40}, {"archiveSha256": "f" * 64},
                           {"rebootedBootId": original["initialBootId"]}, {"guestResults": original["guestResults"][:-1]},
                           {"predecessor": {**previous, "archiveSha256": "f" * 64}}, {"guestPrerequisites": {}}):
                reports[selected] = {**original, **change}
                with self.subTest(change=list(change)), self.assertRaises(InstallError):
                    receipts(Path("synthetic-structural-receipts"), manifest)
            reports[selected] = original

    def test_vm_only_diagnostics_select_only_exact_own_candidate_workflows(self):
        run = {"head_sha": "a" * 40, "head_branch": "feat/native", "event": "push",
               "path": ".github/workflows/native-runtime.yml", "head_repository": {"full_name": REPOSITORY}}
        self.assertEqual(candidate_source(run), ("a" * 40, "refs/heads/feat/native"))
        for change in ({"event": "pull_request_target"}, {"path": RELEASE_WORKFLOW}, {"head_sha": "main"},
                       {"head_repository": {"full_name": "attacker/fork"}}, {"head_branch": "feat/../../main"}):
            with self.assertRaises(InstallError):
                candidate_source({**run, **change})

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
