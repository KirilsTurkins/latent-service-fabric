"""Bounded observation, package-ready publication and failure cleanup checks."""

from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import signal
import tempfile
import unittest
from unittest import mock

from tools import build_echo_capsule as echo
from tools import build_provenance as build
from tools.build_observation import build_environment, file_identity, finish_observation, public_repository, resolve_tools
from tools.build_snapshot import SnapshotError, canonical, digest
from tools.tests.test_build_snapshot import git, repository
from tools.tests.test_build_inventory import artifact, messages


ROOT = Path(__file__).resolve().parents[2]


class BuildProvenanceTests(unittest.TestCase):
    def test_environment_drops_secrets_wrappers_and_cargo_flag_overrides(self) -> None:
        with mock.patch.dict(os.environ, {"LSF_SIGNING_KEY": "secret", "GITHUB_TOKEN": "secret",
                "RUSTC_WRAPPER": "unapproved", "CARGO_ENCODED_RUSTFLAGS": "unapproved",
                "PROGRAMFILES(X86)": "approved-windows-installation-root",
                "PROGRAMDATA": "approved-windows-installer-data",
                "CARGO_PROFILE_RELEASE_DEBUG": "true"}):
            environment = build_environment(Path("temporary"))
        for name in ("LSF_SIGNING_KEY", "GITHUB_TOKEN", "RUSTC_WRAPPER", "CARGO_ENCODED_RUSTFLAGS",
                     "CARGO_PROFILE_RELEASE_DEBUG"):
            self.assertNotIn(name, environment)
        self.assertEqual(environment["CARGO_BUILD_JOBS"], "2")
        # Rust's MSVC discovery locates vswhere through this standard Windows
        # installation root even outside a developer command prompt.
        self.assertEqual(environment["PROGRAMFILES(X86)"], "approved-windows-installation-root")
        self.assertEqual(environment["PROGRAMDATA"], "approved-windows-installer-data")

    @unittest.skipUnless(os.name == "nt", "Windows compiler installation discovery")
    def test_windows_installer_discovery_matches_the_approved_host_environment(self) -> None:
        installation_root = os.environ.get("PROGRAMFILES(X86)")
        if not installation_root:
            self.skipTest("Windows installer root is unavailable")
        tool = Path(installation_root) / "Microsoft Visual Studio/Installer/vswhere.exe"
        if not tool.is_file():
            self.skipTest("Visual Studio discovery is unavailable")
        command = [str(tool), "-latest", "-products", "*", "-requires",
                   "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ambient = build.run_bounded(command, root, dict(os.environ), 30, 4096).stdout
            explicit = build.run_bounded(command, root, build_environment(root), 30, 4096).stdout
            self.assertTrue(ambient == explicit, "sanitized environment lost compiler installation discovery")

    def test_repository_label_rejects_credentials_private_paths_and_ambiguous_urls(self) -> None:
        self.assertEqual(public_repository("https://example.invalid/repository"), "https://example.invalid/repository")
        for value in ("http://example.invalid/x", "https://user:secret@example.invalid/x",
                      "https://example.invalid/x?token=secret", "https://example.invalid/x#secret",
                      "C:/private/source", "file:///private/source", "https://example.invalid/x\n",
                      "https://example.invalid/%40secret", "https://example.invalid:invalid/x",
                      "https://example.invalid:443/x", "https://example.invalid/x/",
                      "https://example.invalid", "https://example.invalid/a//b",
                      "https://example.invalid/a/../b", "https://-example.invalid/a",
                      "https://" + "a" * 64 + ".invalid/a", "https://example.invalid/" + "a" * 490):
            with self.subTest(value=value), self.assertRaises((SnapshotError, ValueError)):
                public_repository(value)

    def test_clock_regression_duration_and_empty_output_suppress_observation(self) -> None:
        arguments = {"repository": "https://example.invalid/repository", "revision": "a" * 40,
                     "inventory": b"[]", "component": b"component", "materials": [],
                     "started": 100, "finished": 101, "elapsed": 1.0, "reproducible": False}
        result = finish_observation(**arguments)
        self.assertEqual(result["reproducibility"], "not-checked")
        self.assertEqual(result["componentDigest"], digest(b"component"))
        self.assertEqual(result["source"]["repositoryTrust"], "operator-asserted")
        for changed in ({"finished": 99}, {"finished": 3701}, {"elapsed": 3601.0}, {"component": b""}):
            with self.subTest(changed=changed), self.assertRaises(SnapshotError):
                finish_observation(**{**arguments, **changed})

    def test_actual_toolchain_binaries_are_selected_instead_of_shims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {name: root / (name + ".exe") for name in ("rustup", "cargo", "rustc", "wasm-tools")}
            for name, path in paths.items():
                path.write_bytes(name.encode())
            calls = []
            def command(argv, **_kwargs):
                calls.append(argv)
                if argv[1] == "which":
                    stdout = str(paths[argv[-1]]).encode()
                else:
                    tool = Path(argv[0]).stem
                    stdout = f"{tool} {'1.254.0' if tool == 'wasm-tools' else '1.97.1'}".encode()
                return subprocess.CompletedProcess(argv, 0, stdout, b"")
            with mock.patch("tools.build_observation.shutil.which", side_effect=lambda name, **_: str(paths[name])), \
                    mock.patch("tools.build_observation.run_bounded", side_effect=command):
                selected, materials = resolve_tools({"rust": {"toolchain": "1.97.1"},
                    "contracts": {"wasm-tools": "1.254.0"}}, root, {})
            self.assertEqual(selected["cargo"], paths["cargo"])
            self.assertEqual(selected["rustc"], paths["rustc"])
            self.assertEqual({row["name"] for row in materials}, {"cargo", "rustc", "wasm-tools"})
            self.assertIn([str(paths["rustup"]), "which", "--toolchain", "1.97.1", "rustc"], calls)
            self.assertNotEqual(materials[0]["digest"], file_identity(paths["rustup"], "shim")["digest"])

    def _pipeline(self, parent: Path, *, failure: str | None = None,
                  legacy: bool = False) -> tuple[Path, dict | None]:
        repo = parent / "repo"
        repository(repo)
        for relative in ("tools/toolchain.toml", "examples/echo-contract/wit/echo.wit",
                         "examples/echo-contract/capsule.json", "examples/echo-contract/contracts.json",
                         "wit/platform/context/package.wit", "wit/platform/log/package.wit"):
            destination = repo / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / relative).read_bytes())
        (repo / "tools/toolchain-smoke").mkdir(exist_ok=True)
        (repo / "tools/toolchain-smoke/Cargo.toml").write_bytes(
            b'[package]\nname="latent-toolchain-smoke"\nversion="1.0.0"\n')
        (repo / "Cargo.lock").write_bytes(b'version=4\n[[package]]\nname="latent-toolchain-smoke"\nversion="1.0.0"\n')
        git(repo, "add", ".")
        git(repo, "commit", "--quiet", "-m", "build inputs")
        revision = git(repo, "rev-parse", "HEAD")
        # This dirty checkout must not replace the captured WIT retained for packaging.
        (repo / "wit/platform/context/package.wit").write_bytes(b"dirty WIT replacement")
        target = parent / "target"
        target.mkdir()
        cache = parent / "cargo-cache"
        cache.mkdir()
        output = target / "echo-observed"
        legacy_output = target / "echo-legacy" if legacy else None
        tool_paths = {name: parent / (name + ".exe") for name in ("cargo", "rustc", "wasm-tools")}
        for name, path in tool_paths.items():
            path.write_bytes(name.encode())
        materials = [file_identity(path, name) for name, path in sorted(tool_paths.items())]
        original_root = echo.ROOT
        component = b"synthetic component for observer orchestration only"
        observed_root = []
        def compile_once(_target, reproducible, *, artifact_observer):
            observed_root.append(echo.ROOT)
            self.assertEqual(echo.command_from_environment("RUSTC", "unused"), [str(tool_paths["rustc"])])
            self.assertEqual(echo.canonical_build_environment()["RUSTC"], str(tool_paths["rustc"]))
            self.assertNotEqual(echo.ROOT, repo)
            if failure == "build":
                raise echo.BuildError("fixture build failed")
            if failure == "source":
                (echo.ROOT / "Cargo.lock").write_bytes(b"altered")
            if failure == "tool":
                tool_paths["rustc"].write_bytes(b"altered")
            if failure == "sigterm":
                handler = signal.getsignal(signal.SIGTERM)
                self.assertTrue(callable(handler))
                handler(signal.SIGTERM, None)
            artifact_observer(messages([artifact(_target,
                echo.ROOT / "tools/toolchain-smoke/Cargo.toml", "echo-capsule", "example")]), _target)
            if reproducible:
                artifact_observer(messages([artifact(_target,
                    echo.ROOT / "tools/toolchain-smoke/Cargo.toml", "echo-capsule", "example")]), _target)
            return component, reproducible
        def stage(component_bytes, *, output_directory, **_kwargs):
            output_directory.mkdir()
            capsule = json.loads((echo.ROOT / "examples/echo-contract/capsule.json").read_bytes())
            capsule["component"]["digest"] = digest(component_bytes)
            (output_directory / "capsule.json").write_bytes(canonical(capsule))
            (output_directory / "contracts.json").write_bytes((echo.ROOT / "examples/echo-contract/contracts.json").read_bytes())
            (output_directory / "build.json").write_bytes(b"legacy receipt must not be published")
            (output_directory / echo.ARTIFACT_NAME).write_bytes(component_bytes)
            (output_directory / "input.json").write_bytes(b'["hello"]')
            interface = output_directory / "interface"
            interface.mkdir()
            (interface / "component.wit").write_bytes(b"maintained interface output")
        with ExitStack() as mocks:
            mocks.enter_context(mock.patch.dict(os.environ, {"CARGO_HOME": str(cache)}))
            mocks.enter_context(mock.patch.object(build, "resolve_tools", return_value=(tool_paths, materials)))
            mocks.enter_context(mock.patch.object(echo, "verify_tool_versions"))
            mocks.enter_context(mock.patch.object(echo, "build_component", side_effect=compile_once))
            mocks.enter_context(mock.patch.object(echo, "validate_and_stage_output", side_effect=stage))
            if failure == "legacy":
                mocks.enter_context(mock.patch.object(build, "copy_legacy_fixture",
                                                       side_effect=SnapshotError("fixture export failed")))
            if failure == "publish":
                original_rename = Path.rename
                def rename(source, destination):
                    if destination == legacy_output:
                        raise OSError("fixture publication failed")
                    return original_rename(source, destination)
                mocks.enter_context(mock.patch.object(Path, "rename", rename))
            if failure:
                with self.assertRaises((SnapshotError, echo.BuildError, OSError, SystemExit)):
                    build.observed_build(repository=repo, revision=revision,
                        repository_label="https://example.invalid/source", target_root=target, output=output,
                        legacy_output=legacy_output)
                self.assertEqual(list(target.iterdir()), [])
                observation = None
            else:
                observation = build.observed_build(repository=repo, revision=revision,
                    repository_label="https://example.invalid/source", target_root=target, output=output,
                    legacy_output=legacy_output)
        self.assertEqual(echo.ROOT, original_root)
        self.assertTrue(all(not path.exists() for path in observed_root))
        return output, observation

    def test_pipeline_publishes_only_exact_package_inputs_and_compact_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            output, observation = self._pipeline(parent)
            self.assertEqual(json.loads((output / "observation.json").read_bytes()), observation)
            self.assertEqual((output / "wit/context.wit").read_bytes(), (ROOT / "wit/platform/context/package.wit").read_bytes())
            self.assertFalse((output / "build.json").exists())
            self.assertFalse((output / "source").exists())
            recipe = json.loads((output / "package-source.json").read_bytes())
            self.assertEqual(len(recipe["layers"]), 7)
            self.assertEqual(observation["componentDigest"], digest((output / "echo-capsule.wasm").read_bytes()))
            inventory_bytes = (output / "sbom-inputs.json").read_bytes()
            inventory = json.loads(inventory_bytes)
            self.assertEqual(inventory["dependencyCompleteness"], "observed-units-incomplete")
            self.assertEqual(len(inventory["entries"]), 7)
            self.assertEqual([row for row in observation["materials"] if row["name"] == "dependency-inventory"],
                [{"name": "dependency-inventory", "digest": digest(inventory_bytes), "size": len(inventory_bytes)}])
            self.assertNotIn(str(parent), inventory_bytes.decode())
            self.assertNotIn("sbom-inputs.json", {row["path"] for row in recipe["layers"]})
            for row in observation["materials"]:
                self.assertNotIn(str(parent), json.dumps(row))
            self.assertEqual({path.name for path in output.parent.iterdir()}, {output.name})

    def test_failed_build_or_changed_source_or_tool_leaves_no_output(self) -> None:
        for failure in ("build", "source", "tool"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                self._pipeline(Path(temporary), failure=failure)

    def test_normal_termination_between_commands_cleans_snapshot_and_suppresses_outputs(self) -> None:
        before = signal.getsignal(signal.SIGTERM)
        with tempfile.TemporaryDirectory() as temporary:
            self._pipeline(Path(temporary), failure="sigterm")
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)

    def test_optional_legacy_export_reuses_exact_build_without_receipt_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, observation = self._pipeline(Path(temporary), legacy=True)
            legacy = output.parent / "echo-legacy"
            self.assertEqual((legacy / echo.ARTIFACT_NAME).read_bytes(),
                             (output / echo.ARTIFACT_NAME).read_bytes())
            self.assertEqual(observation["componentDigest"], digest((legacy / echo.ARTIFACT_NAME).read_bytes()))
            self.assertTrue((legacy / "build.json").exists())
            self.assertFalse((output / "build.json").exists())
            self.assertTrue((legacy / "interface/component.wit").exists())
            self.assertEqual({path.name for path in output.parent.iterdir()}, {output.name, legacy.name})

    def test_failed_legacy_staging_or_second_publication_rolls_back_both_outputs(self) -> None:
        for failure in ("legacy", "publish"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                self._pipeline(Path(temporary), failure=failure, legacy=True)

    def test_existing_output_is_preserved_without_starting_a_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "existing"
            output.mkdir()
            (output / "user-file").write_bytes(b"keep")
            with self.assertRaises(SnapshotError):
                build.observed_build(repository=ROOT, revision="a" * 40,
                    repository_label="https://example.invalid/source", target_root=root, output=output)
            self.assertEqual((output / "user-file").read_bytes(), b"keep")
            for legacy in (output, root / "new/nested", root.parent / "outside"):
                with self.subTest(legacy=legacy), self.assertRaises(SnapshotError):
                    build.observed_build(repository=ROOT, revision="a" * 40,
                        repository_label="https://example.invalid/source", target_root=root,
                        output=root / "new", legacy_output=legacy)


if __name__ == "__main__":
    unittest.main()
