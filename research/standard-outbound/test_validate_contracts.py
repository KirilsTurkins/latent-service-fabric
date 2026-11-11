"""Staging/runner regressions; actual WIT validation requires wasm-tools."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import validate_contracts


class ContractValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.research = self.repository / "research/standard-outbound"
        self.companion = self.research / "nonblocking-v2/package.wit"
        self.companion.parent.mkdir(parents=True)
        self.companion.write_bytes(b"package example:companion@0.2.0;\n")
        self.dependency = self.repository / "wit/platform/network"
        self.dependency.mkdir(parents=True)
        (self.dependency / "package.wit").write_bytes(b"package example:network@0.1.0;\n")
        (self.dependency / "types.wit").write_bytes(b"interface shared {}\n")
        (self.dependency / "README.md").write_text("Not WIT", encoding="utf-8")

    def test_staging_copies_the_complete_exact_v1_wit_without_changing_sources(self) -> None:
        before = {
            path.relative_to(self.repository): path.read_bytes()
            for path in self.repository.rglob("*") if path.is_file()
        }
        staged = self.root / "staged"
        validate_contracts.stage_companion(self.repository, staged)
        self.assertEqual((staged / "package.wit").read_bytes(), self.companion.read_bytes())
        for name in ("package.wit", "types.wit"):
            self.assertEqual(
                (staged / "deps/network" / name).read_bytes(),
                (self.dependency / name).read_bytes(),
            )
        self.assertFalse((staged / "deps/network/README.md").exists())
        after = {
            path.relative_to(self.repository): path.read_bytes()
            for path in self.repository.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)

    def test_missing_v1_is_an_error_not_a_synthesized_dependency(self) -> None:
        for source in self.dependency.glob("*.wit"):
            source.unlink()
        with self.assertRaises(FileNotFoundError):
            validate_contracts.stage_companion(self.repository, self.root / "staged")

    def test_stale_staging_directory_is_not_reused(self) -> None:
        staged = self.root / "staged"
        staged.mkdir()
        with self.assertRaises(FileExistsError):
            validate_contracts.stage_companion(self.repository, staged)

    def test_runner_parses_original_v1_directory_and_isolated_v2_then_cleans_up(self) -> None:
        staged = []

        def check_stage(arguments, *, check):
            self.assertTrue(check)
            if arguments[1:3] == ["component", "wit"]:
                source = Path(arguments[3])
                if source != self.research:
                    staged.append(source)
                    self.assertEqual((source / "package.wit").read_bytes(), self.companion.read_bytes())
                    self.assertEqual(
                        (source / "deps/network/package.wit").read_bytes(),
                        (self.dependency / "package.wit").read_bytes(),
                    )

        with patch.object(validate_contracts.subprocess, "run", side_effect=check_stage) as run:
            with patch("builtins.print"):
                validate_contracts.validate(self.repository, self.root / "output", "pinned-wasm-tools")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][3], str(self.research))
        self.assertEqual([command[1] for command in commands], ["component", "validate", "component", "validate"])
        self.assertEqual(len(staged), 1)
        self.assertFalse(staged[0].exists())

    def test_parser_failure_stops_validation_and_does_not_report_success(self) -> None:
        failure = subprocess.CalledProcessError(1, ["wasm-tools", "component", "wit"])
        with patch.object(validate_contracts.subprocess, "run", side_effect=failure) as run:
            with patch("builtins.print") as report:
                with self.assertRaises(subprocess.CalledProcessError):
                    validate_contracts.validate(self.repository, self.root / "output", "wasm-tools")
        run.assert_called_once()
        report.assert_not_called()

    def test_v2_parser_failure_removes_staging_and_does_not_report_success(self) -> None:
        staged = []

        def reject_v2(arguments, *, check):
            self.assertTrue(check)
            if arguments[1:3] == ["component", "wit"]:
                source = Path(arguments[3])
                if source != self.research:
                    staged.append(source)
                    raise subprocess.CalledProcessError(1, arguments)

        with patch.object(validate_contracts.subprocess, "run", side_effect=reject_v2):
            with patch("builtins.print") as report:
                with self.assertRaises(subprocess.CalledProcessError):
                    validate_contracts.validate(self.repository, self.root / "output", "wasm-tools")
        self.assertEqual(len(staged), 1)
        self.assertFalse(staged[0].exists())
        report.assert_not_called()

    def test_generated_outputs_cannot_pollute_source_packages(self) -> None:
        for output in (self.research, self.research / "generated", self.dependency / "generated"):
            with self.subTest(output=output):
                with patch.object(validate_contracts.subprocess, "run") as run:
                    with self.assertRaises(ValueError):
                        validate_contracts.validate(self.repository, output, "wasm-tools")
                    run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
