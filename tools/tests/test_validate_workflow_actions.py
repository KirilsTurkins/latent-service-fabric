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
        action = root / "actions/local"
        action.mkdir(parents=True)
        (action / "action.yml").write_text("runs: {using: composite, steps: []}\n", encoding="utf-8")

        workflows, references, findings = validate_workflow_actions.validate_repository(root)
        self.assertEqual(workflows, 1)
        self.assertEqual(references, 3)
        self.assertEqual(findings, [])

    def test_yaml_forms_cannot_hide_mutable_executable_references(self) -> None:
        cases = [
            "jobs: {check: {steps: [{uses: actions/checkout@v4}]}}\n",
            "jobs:\n  check:\n    steps:\n      - 'uses': actions/checkout@v4\n",
            "jobs:\n  check:\n    steps:\n      - &step {uses: actions/checkout@v4}\n      - *step\n",
            "jobs: {reuse: {'uses': example/repo/.github/workflows/ci.yml@main}}\n",
        ]
        for workflow in cases:
            with self.subTest(workflow=workflow):
                temporary, root = self._root(workflow)
                try:
                    _, references, findings = validate_workflow_actions.validate_repository(root)
                    self.assertGreater(references, 0)
                    self.assertTrue(any("full 40-character" in finding.message for finding in findings))
                finally:
                    temporary.cleanup()

    def test_script_text_is_not_an_executable_action_reference(self) -> None:
        temporary, root = self._root(
            "jobs:\n  check:\n    steps:\n      - run: |\n          cat <<'EXAMPLE'\n"
            "          uses: actions/checkout@v4\n          EXAMPLE\n"
        )
        self.addCleanup(temporary.cleanup)
        _, references, findings = validate_workflow_actions.validate_repository(root)
        self.assertEqual((references, findings), (0, []))

    def test_local_composite_and_local_reusable_dependencies_are_inspected(self) -> None:
        temporary, root = self._root(
            "jobs:\n  check:\n    steps:\n      - uses: ./actions/first\n"
            "  reuse:\n    uses: ./.github/workflows/reuse.yml\n"
        )
        self.addCleanup(temporary.cleanup)
        for name, contents in [
            ("actions/first/action.yml", "runs: {using: composite, steps: [{uses: ./actions/second}]}\n"),
            ("actions/second/action.yaml", "runs: {using: composite, steps: [{uses: actions/checkout@v4}]}\n"),
            (".github/workflows/reuse.yml", "jobs: {check: {steps: [{uses: actions/setup-python@v5}]}}\n"),
        ]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        workflows, references, findings = validate_workflow_actions.validate_repository(root)
        self.assertEqual((workflows, references), (2, 5))
        self.assertEqual({f.path.name for f in findings}, {"action.yaml", "reuse.yml"})

    def test_yaml_duplicates_nesting_and_nonscalar_uses_fail_closed(self) -> None:
        for workflow in [
            "jobs: {}\njobs: {}\n",
            "jobs: {check: {steps: [{uses: [actions/checkout@v4]}]}}\n",
            "jobs: {check: {steps: [{<<: {uses: actions/checkout@v4}}]}}\n",
            "jobs: " + "[" * 70 + "]" * 70 + "\n",
        ]:
            with self.subTest(workflow=workflow):
                temporary, root = self._root(workflow)
                try:
                    self.assertTrue(validate_workflow_actions.validate_repository(root)[2])
                finally:
                    temporary.cleanup()

    def test_missing_local_action_is_an_actionable_failure(self) -> None:
        temporary, root = self._root("jobs: {check: {steps: [{uses: ./missing}]}}\n")
        self.addCleanup(temporary.cleanup)
        findings = validate_workflow_actions.validate_repository(root)[2]
        self.assertEqual(len(findings), 1)
        self.assertIn("action.yml", findings[0].message)

    def test_external_subpaths_and_local_paths_cannot_escape(self) -> None:
        for reference in [f"owner/repo/../outside@{PIN}", "./actions/../outside", "./actions//local", "./actions/./local", "./${{ inputs.action }}"]:
            with self.subTest(reference=reference):
                temporary, root = self._root(f"jobs:\n  check:\n    steps:\n      - uses: {reference} # version\n")
                try:
                    self.assertTrue(validate_workflow_actions.validate_repository(root)[2])
                finally:
                    temporary.cleanup()

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
            try:
                (directory / "ci.yml").symlink_to(target)
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows host does not grant symlink creation; exercised on Linux CI")
                raise

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
