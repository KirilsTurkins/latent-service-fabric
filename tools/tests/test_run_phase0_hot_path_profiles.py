from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "run_phase0_hot_path_profiles.sh"
SOURCE_COMMIT = "a" * 40
SOURCE_TREE = "b" * 40


class HotPathProfileRunnerTests(unittest.TestCase):
    def command(self, calibration: Path, output: Path | str | None = None) -> list[str]:
        command = [
            str(RUNNER),
            "--published-source-commit",
            SOURCE_COMMIT,
            "--published-source-tree",
            SOURCE_TREE,
            "--published-source-ref",
            "phase0-test-source",
            "--calibration-aggregate",
            str(calibration),
        ]
        if output is not None:
            command.append(str(output))
        return command

    def run_runner(
        self,
        calibration: Path,
        output: Path | str | None = None,
        *,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.command(calibration, output),
            check=False,
            text=True,
            capture_output=True,
            env=environment,
        )

    def test_requires_an_explicit_absolute_external_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calibration = root / "calibration.json"
            calibration.write_text("{}\n", encoding="utf-8")

            missing = self.run_runner(calibration)
            self.assertEqual(missing.returncode, 2)
            self.assertIn("must be supplied as a fresh absolute path", missing.stderr)

            relative = self.run_runner(calibration, "evidence")
            self.assertEqual(relative.returncode, 2)
            self.assertIn("must be an absolute path outside the source tree", relative.stderr)

    def test_rejects_an_in_tree_or_reused_output_path_before_tool_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calibration = root / "calibration.json"
            calibration.write_text("{}\n", encoding="utf-8")

            in_tree = self.run_runner(
                calibration, ROOT / "target" / "phase0-hot-path-test-output"
            )
            self.assertEqual(in_tree.returncode, 2)
            self.assertIn("profile output directory must be outside the source tree", in_tree.stderr)

            reused = root / "existing-evidence"
            reused.mkdir()
            reused_result = self.run_runner(calibration, reused)
            self.assertEqual(reused_result.returncode, 2)
            self.assertIn("profile output directory must not already exist", reused_result.stderr)

    def test_requires_a_fresh_external_target_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calibration = root / "calibration.json"
            calibration.write_text("{}\n", encoding="utf-8")
            output = root / "evidence"
            base_environment = dict(os.environ)

            relative_environment = dict(base_environment)
            relative_environment["LSF_HOT_PATH_TARGET_DIR"] = "profile-build"
            relative = self.run_runner(
                calibration, output, environment=relative_environment
            )
            self.assertEqual(relative.returncode, 2)
            self.assertIn("LSF_HOT_PATH_TARGET_DIR must be an absolute path", relative.stderr)
            self.assertFalse(output.exists())

            in_tree_environment = dict(base_environment)
            in_tree_environment["LSF_HOT_PATH_TARGET_DIR"] = str(
                ROOT / "target" / "phase0-hot-path-test-build"
            )
            in_tree = self.run_runner(
                calibration, output, environment=in_tree_environment
            )
            self.assertEqual(in_tree.returncode, 2)
            self.assertIn("build output must be outside the source tree", in_tree.stderr)
            self.assertFalse(output.exists())

            reused_target = root / "existing-build"
            reused_target.mkdir()
            reused_environment = dict(base_environment)
            reused_environment["LSF_HOT_PATH_TARGET_DIR"] = str(reused_target)
            reused = self.run_runner(
                calibration, output, environment=reused_environment
            )
            self.assertEqual(reused.returncode, 2)
            self.assertIn("build output directory must not already exist", reused.stderr)
            self.assertFalse(output.exists())

    def write_executable(self, path: Path, contents: str) -> None:
        path.write_text(contents, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def fake_runner_environment(
        self,
        root: Path,
        *,
        execution_commit: str,
        execution_tree: str,
        check_ref_format_exit: int = 0,
        ref_capture: Path | None = None,
    ) -> tuple[Path, dict[str, str]]:
        source = root / "source"
        tools = source / "tools"
        tools.mkdir(parents=True)
        shutil.copy2(RUNNER, tools / RUNNER.name)
        shutil.copy2(ROOT / "tools" / "phase0_build_environment.sh", tools)
        bin_directory = root / "bin"
        bin_directory.mkdir()
        capture_assignment = (
            f'printf "%s" "${{2:-}}" > "{ref_capture}"\n'
            if ref_capture is not None
            else ""
        )
        self.write_executable(
            bin_directory / "git",
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "case \"${1:-}\" in\n"
            "  status) exit 0 ;;\n"
            "  rev-parse)\n"
            "    case \"${2:-}\" in\n"
            f"      HEAD) printf '%s\\n' '{execution_commit}' ;;\n"
            f"      'HEAD^{{tree}}') printf '%s\\n' '{execution_tree}' ;;\n"
            "      *) exit 97 ;;\n"
            "    esac\n"
            "    ;;\n"
            "  check-ref-format)\n"
            f"    {capture_assignment}"
            f"    exit {check_ref_format_exit} ;;\n"
            "  *) exit 98 ;;\n"
            "esac\n",
        )
        for command in ("cargo", "perf", "heaptrack", "heaptrack_print"):
            self.write_executable(bin_directory / command, "#!/usr/bin/env bash\nexit 0\n")
        self.write_executable(
            bin_directory / "uname", "#!/usr/bin/env bash\nprintf '%s\\n' Linux\n"
        )
        self.write_executable(
            bin_directory / "systemd-detect-virt",
            "#!/usr/bin/env bash\nprintf '%s\\n' none\n",
        )
        environment = dict(os.environ)
        # The production profiler runs repository validation after creating
        # its external target.  Fake-runner provenance tests must derive their
        # own fresh target instead of inheriting that outer path.
        environment.pop("LSF_HOT_PATH_TARGET_DIR", None)
        environment["PATH"] = f"{bin_directory}:{environment['PATH']}"
        environment["PYTHON"] = sys.executable
        return source, environment

    def test_rejects_a_same_tree_but_different_execution_head_before_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, environment = self.fake_runner_environment(
                root,
                execution_commit="c" * 40,
                execution_tree=SOURCE_TREE,
            )
            calibration = root / "calibration.json"
            calibration.write_text("{}\n", encoding="utf-8")
            output = root / "evidence"
            command = self.command(calibration, output)
            command[0] = str(source / "tools" / RUNNER.name)
            result = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                env=environment,
                cwd=source,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "local execution HEAD does not equal the declared published source commit",
                result.stderr,
            )
            self.assertFalse(output.exists())

    def test_canonicalizes_a_branch_ref_before_validating_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ref_capture = root / "checked-ref.txt"
            source, environment = self.fake_runner_environment(
                root,
                execution_commit=SOURCE_COMMIT,
                execution_tree=SOURCE_TREE,
                check_ref_format_exit=1,
                ref_capture=ref_capture,
            )
            calibration = root / "calibration.json"
            calibration.write_text("{}\n", encoding="utf-8")
            output = root / "evidence"
            command = self.command(calibration, output)
            command[0] = str(source / "tools" / RUNNER.name)
            source_ref_index = command.index("--published-source-ref") + 1
            command[source_ref_index] = "phase0-test-source"
            result = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                env=environment,
                cwd=source,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("published source ref is not a valid Git ref", result.stderr)
            self.assertEqual(ref_capture.read_text(encoding="utf-8"), "refs/heads/phase0-test-source")
            self.assertFalse(output.exists())

    def test_rejects_a_local_tag_when_origin_fetch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, environment = self.fake_runner_environment(
                root,
                execution_commit=SOURCE_COMMIT,
                execution_tree=SOURCE_TREE,
            )
            bin_directory = Path(environment["PATH"].split(os.pathsep, 1)[0])
            self.write_executable(
                bin_directory / "git",
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "case \"${1:-}\" in\n"
                "  status|check-ref-format|show-ref|cat-file|merge-base) exit 0 ;;\n"
                "  fetch) exit 1 ;;\n"
                "  rev-parse)\n"
                "    case \"${2:-}\" in\n"
                f"      HEAD) printf '%s\\n' '{SOURCE_COMMIT}' ;;\n"
                f"      'HEAD^{{tree}}'|*'^{{tree}}') printf '%s\\n' '{SOURCE_TREE}' ;;\n"
                f"      *) printf '%s\\n' '{SOURCE_COMMIT}' ;;\n"
                "    esac\n"
                "    ;;\n"
                "  *) exit 98 ;;\n"
                "esac\n",
            )
            calibration = root / "calibration.json"
            calibration.write_text("{}\n", encoding="utf-8")
            output = root / "evidence"
            command = self.command(calibration, output)
            command[0] = str(source / "tools" / RUNNER.name)
            source_ref_index = command.index("--published-source-ref") + 1
            command[source_ref_index] = "refs/tags/local-only"

            result = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                env=environment,
                cwd=source,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "cannot fetch durable published source tag from origin",
                result.stderr,
            )
            self.assertFalse(output.exists())

    def test_derives_a_fresh_external_target_instead_of_reusing_checkout_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, environment = self.fake_runner_environment(
                root,
                execution_commit=SOURCE_COMMIT,
                execution_tree=SOURCE_TREE,
            )
            bin_directory = Path(environment["PATH"].split(os.pathsep, 1)[0])
            self.write_executable(
                bin_directory / "git",
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "case \"${1:-}\" in\n"
                "  status|fetch|cat-file|merge-base|check-ref-format) exit 0 ;;\n"
                "  rev-parse)\n"
                "    case \"${2:-}\" in\n"
                f"      HEAD) printf '%s\\n' '{SOURCE_COMMIT}' ;;\n"
                f"      'HEAD^{{tree}}'|*'^{{tree}}') printf '%s\\n' '{SOURCE_TREE}' ;;\n"
                f"      --verify) printf '%s\\n' '{'c' * 40}' ;;\n"
                "      *) exit 97 ;;\n"
                "    esac\n"
                "    ;;\n"
                "  *) exit 98 ;;\n"
                "esac\n",
            )
            (source / "tools" / "aggregate_phase0_calibration.py").write_text(
                "raise SystemExit(0)\n", encoding="utf-8"
            )
            (source / "tools" / "aggregate_phase0_hot_path_profiles.py").write_text(
                "raise SystemExit(73)\n", encoding="utf-8"
            )
            checkout_target = source / "target" / "phase0-hot-path-work"
            checkout_target.mkdir(parents=True)
            marker = checkout_target / "pre-existing"
            marker.write_text("not collector output\n", encoding="utf-8")
            calibration = root / "calibration.json"
            calibration.write_text("{}\n", encoding="utf-8")
            output = root / "evidence"
            command = self.command(calibration, output)
            command[0] = str(source / "tools" / RUNNER.name)

            result = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                env=environment,
                cwd=source,
            )

            # The fake host collector terminates immediately after workspace
            # creation; reaching it proves target setup did not reuse the
            # checkout's old default target directory.
            self.assertEqual(result.returncode, 73)
            self.assertTrue(output.is_dir())
            self.assertTrue(Path(f"{output}.build").is_dir())
            self.assertEqual(marker.read_text(encoding="utf-8"), "not collector output\n")


if __name__ == "__main__":
    unittest.main()
