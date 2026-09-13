from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools import validate_workflow_actions


PIN = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "a" * 64


class WorkflowActionPolicyTests(unittest.TestCase):
    def _root(self, workflow: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        directory = root / ".github" / "workflows"
        directory.mkdir(parents=True)
        path = directory / "ci.yml"
        path.write_text(workflow, encoding="utf-8")
        return temporary, root

    def test_accepts_full_sha_local_action_and_digest_pinned_docker_action(self) -> None:
        temporary, root = self._root(
            "jobs:\n"
            "  check:\n"
            "    steps:\n"
            f"      - uses: actions/checkout@{PIN} # v4\n"
            "      - uses: ./actions/local\n"
            f"      - uses: docker://example.invalid/tool@sha256:{DIGEST} # 1.2.3\n"
        )
        self.addCleanup(temporary.cleanup)

        workflows, references, findings = validate_workflow_actions.validate_repository(root)
        self.assertEqual(workflows, 1)
        self.assertEqual(references, 3)
        self.assertEqual(findings, [])

    def test_accepts_external_reusable_workflow_pinned_to_full_sha(self) -> None:
        temporary, root = self._root(
            "jobs:\n"
            "  reuse:\n"
            f"    uses: example/project/.github/workflows/reuse.yml@{PIN} # v2\n"
        )
        self.addCleanup(temporary.cleanup)

        _, references, findings = validate_workflow_actions.validate_repository(root)
        self.assertEqual(references, 1)
        self.assertEqual(findings, [])

    def test_rejects_moving_tag_short_sha_dynamic_and_missing_comment(self) -> None:
        cases = {
            "moving tag": "      - uses: actions/checkout@v4 # v4\n",
            "short sha": "      - uses: actions/checkout@0123456789ab # v4\n",
            "dynamic": "      - uses: actions/checkout@${{ inputs.ref }} # dynamic\n",
            "missing comment": f"      - uses: actions/checkout@{PIN}\n",
        }
        for name, uses_line in cases.items():
            with self.subTest(name=name):
                temporary, root = self._root(
                    "jobs:\n  check:\n    steps:\n" + uses_line
                )
                try:
                    _, _, findings = validate_workflow_actions.validate_repository(root)
                    self.assertTrue(findings)
                finally:
                    temporary.cleanup()

    def test_rejects_mutable_docker_tag_and_unsafe_local_path(self) -> None:
        temporary, root = self._root(
            "jobs:\n"
            "  check:\n"
            "    steps:\n"
            "      - uses: docker://alpine:3.20 # 3.20\n"
            "      - uses: ./../outside\n"
        )
        self.addCleanup(temporary.cleanup)

        _, _, findings = validate_workflow_actions.validate_repository(root)
        messages = [finding.message for finding in findings]
        self.assertTrue(any("sha256" in message for message in messages))
        self.assertTrue(any("unsafe local" in message for message in messages))

    def test_rejects_oversized_workflow(self) -> None:
        temporary, root = self._root(
            "#" * (validate_workflow_actions.MAX_WORKFLOW_BYTES + 1)
        )
        self.addCleanup(temporary.cleanup)

        _, references, findings = validate_workflow_actions.validate_repository(root)
        self.assertEqual(references, 0)
        self.assertEqual(len(findings), 1)
        self.assertIn("byte policy ceiling", findings[0].message)

    def test_rejects_symlinked_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / ".github" / "workflows"
            directory.mkdir(parents=True)
            target = root / "workflow.yml"
            target.write_text("jobs: {}\n", encoding="utf-8")
            (directory / "ci.yml").symlink_to(target)

            _, references, findings = validate_workflow_actions.validate_repository(root)
            self.assertEqual(references, 0)
            self.assertEqual(len(findings), 1)
            self.assertIn("ordinary regular file", findings[0].message)

    def test_repository_workflows_satisfy_policy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        workflows, references, findings = validate_workflow_actions.validate_repository(root)
        self.assertGreater(workflows, 0)
        self.assertGreater(references, 0)
        self.assertEqual([finding.render(root) for finding in findings], [])


if __name__ == "__main__":
    unittest.main()
