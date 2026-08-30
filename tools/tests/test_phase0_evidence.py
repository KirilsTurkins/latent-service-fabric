from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import phase0_evidence


class Phase0ExecutionEvidenceIdentityTests(unittest.TestCase):
    def git(self, root: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()

    def commit(self, root: Path, message: str) -> tuple[str, str]:
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", message)
        return (
            self.git(root, "rev-parse", "HEAD"),
            self.git(root, "rev-parse", "HEAD^{tree}"),
        )

    def test_pinned_build_inputs_are_execution_relevant(self) -> None:
        self.assertIn("rust-toolchain.toml", phase0_evidence.EXECUTION_RELEVANT_PATHS)
        self.assertIn("tools/toolchain.toml", phase0_evidence.EXECUTION_RELEVANT_PATHS)
        self.assertIn("tools/toolchain-smoke", phase0_evidence.EXECUTION_RELEVANT_PATHS)

    def test_pinned_build_input_changes_alter_the_canonical_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "tools/toolchain-smoke").mkdir(parents=True)
            tracked_inputs = (
                root / "rust-toolchain.toml",
                root / "tools/toolchain.toml",
                root / "tools/toolchain-smoke/Cargo.toml",
            )
            for path in tracked_inputs:
                path.write_text("version = 1\n", encoding="utf-8")

            self.git(root, "init", "--quiet")
            self.git(root, "config", "user.name", "Phase 0 test")
            self.git(root, "config", "user.email", "phase0@example.invalid")
            commit, tree = self.commit(root, "initial pinned build inputs")

            with mock.patch.object(phase0_evidence, "REPOSITORY_ROOT", root):
                previous = phase0_evidence.execution_evidence_identity(commit, tree)
                for index, path in enumerate(tracked_inputs, start=2):
                    with self.subTest(path=path.relative_to(root)):
                        path.write_text(f"version = {index}\n", encoding="utf-8")
                        commit, tree = self.commit(
                            root, f"change {path.relative_to(root)}"
                        )
                        current = phase0_evidence.execution_evidence_identity(
                            commit, tree
                        )
                        self.assertNotEqual(previous["sha256"], current["sha256"])
                        previous = current


if __name__ == "__main__":
    unittest.main()
