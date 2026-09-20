"""Regressions for the feature-hidden workspace cycles reported on PR #446."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import check_testkit_dependencies as subject


class TestkitDependencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.errors = patch.object(subject.foundation, "ERRORS", [])
        self.errors.start()
        self.addCleanup(self.errors.stop)
        self.fixture()

    def manifest(self, name, extra=""):
        path = self.root / "crates" / name / "Cargo.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'[package]\nname = "{name}"\nversion = "0.0.0"\n{extra}', encoding="utf-8")

    def fixture(self):
        names = (*subject.PACKAGES, "latent-node")
        members = ", ".join(f'"crates/{name}"' for name in names)
        (self.root / "Cargo.toml").write_text(f"[workspace]\nmembers = [{members}]\n", encoding="utf-8")
        self.manifest("latent-core", '[features]\ntest-support = []\n')
        # These optional edges remain real architecture edges with defaults off.
        self.manifest("latent-testkit", '[dependencies]\nlatent-core = { path = "../latent-core", features = ["test-support"] }\nlatent-node = { path = "../latent-node", optional = true }\n[features]\ndefault = ["runtime"]\nruntime = ["dep:latent-node"]\n')
        self.manifest("latent-node", '[dependencies]\nlatent-admission = { path = "../latent-admission" }\nlatent-scheduler = { path = "../latent-scheduler" }\n')
        for name in ("latent-admission", "latent-scheduler"):
            self.manifest(name, '[dependencies]\nlatent-core = { path = "../latent-core" }\n[dev-dependencies]\nlatent-core = { path = "../latent-core", features = ["test-support"] }\n')

    def append(self, name, value):
        path = self.root / "crates" / name / "Cargo.toml"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(value)

    def test_neutral_core_direction_is_acyclic(self):
        subject.check_workspace(self.root)
        self.assertEqual(subject.foundation.ERRORS, [])

    def test_original_feature_hidden_admission_and_scheduler_cycles_fail(self):
        for name in ("latent-admission", "latent-scheduler"):
            with self.subTest(owner=name):
                self.fixture()
                subject.foundation.ERRORS.clear()
                self.append(name, 'latent-testkit = { path = "../latent-testkit", default-features = false }\n')
                with patch.object(subject.subprocess, "run") as cargo:
                    with self.assertRaisesRegex(RuntimeError, "workspace dependency cycle"):
                        subject.main(self.root)
                    cargo.assert_not_called()

    def test_target_specific_optional_and_build_cycles_remain_errors(self):
        for table in ('target.\'cfg(unix)\'.dependencies', "build-dependencies", "dependencies"):
            with self.subTest(table=table):
                self.fixture()
                subject.foundation.ERRORS.clear()
                self.append("latent-core", f'[{table}]\nlatent-testkit = {{ path = "../latent-testkit", optional = true, default-features = false }}\n')
                with self.assertRaisesRegex(RuntimeError, "workspace dependency cycle"):
                    subject.check_workspace(self.root)

    def test_alias_cannot_hide_a_path_dependency_cycle(self):
        self.append("latent-admission", 'helper = { package = "latent-testkit", path = "../latent-testkit", default-features = false }\n')
        with self.assertRaisesRegex(RuntimeError, "workspace dependency cycle"):
            subject.check_workspace(self.root)

    def test_missing_test_support_feature_fails(self):
        self.manifest("latent-admission", '[dev-dependencies]\nlatent-core = { path = "../latent-core" }\n')
        with self.assertRaisesRegex(RuntimeError, "must select latent-core/test-support"):
            subject.check_workspace(self.root)

    def test_empty_workspace_is_not_success(self):
        (self.root / "Cargo.toml").write_text("[workspace]\nmembers = []\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "missing helper graph owners"):
            subject.check_workspace(self.root)

    def test_selected_graph_rejects_empty_or_heavy_results(self):
        for output in ("", "latent-core v0.0.0\nwasmtime v47.0.4\n", "latent-core v0.0.0\nlatent-node v0.0.0\n"):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                subject.check_selected("latent-core", output)
        subject.check_selected("latent-core", "latent-core v0.0.0\ntokio v1.53.1\n")

    def test_selected_checks_include_test_dependencies(self):
        for package in subject.PACKAGES:
            command = subject.cargo_command(package)
            self.assertIn("--locked", command)
            self.assertEqual(command[command.index("--edges") + 1], "normal,build,dev")
        self.assertIn("--no-default-features", subject.cargo_command("latent-testkit"))
        self.assertIn("test-support", subject.cargo_command("latent-core"))

    def test_repository_itself_obeys_unconditional_graph_contract(self):
        subject.check_workspace(subject.ROOT)


if __name__ == "__main__":
    unittest.main()
