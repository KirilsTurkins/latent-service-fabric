"""Runner regressions; the bindings lane separately executes the real WIT compiler."""

import json
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
        (self.research / "streams.wit").write_bytes(b"package example:network@0.1.0;\n")
        self.dependency = self.repository / "wit/platform/network"
        self.dependency.mkdir(parents=True)
        (self.dependency / "package.wit").write_bytes(b"package example:network@0.1.0;\n")
        (self.dependency / "types.wit").write_bytes(b"interface shared {}\n")
        (self.dependency / "README.md").write_text("Not WIT", encoding="utf-8")
        (self.repository / "tools").mkdir()
        (self.repository / "tools/toolchain.toml").write_text(
            '[contracts]\nwasm-tools = "1.254.0"\n', encoding="utf-8",
        )
        self.output = self.root / "output"

    def compiler(self, arguments, **options):
        self.assertTrue(options["check"])
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertEqual(options["timeout"], validate_contracts.COMMAND_TIMEOUT_SECONDS)
        self.assertEqual(options["cwd"], self.repository)
        if arguments[1:] == ["--version"]:
            return subprocess.CompletedProcess(arguments, 0, "wasm-tools 1.254.0 (test build)\n")
        if arguments[1:3] == ["component", "wit"]:
            # Deliberately not a WIT parser: only the real bindings lane can
            # establish that these sources encode and validate successfully.
            Path(arguments[-1]).write_bytes(b"test-only-compiler-output")
        return subprocess.CompletedProcess(arguments, 0)

    def validate(self):
        return validate_contracts.validate(self.repository, self.output, "pinned-wasm-tools")

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

        def check_stage(arguments, **options):
            if arguments[1:3] == ["component", "wit"]:
                source = Path(arguments[3])
                if source != self.research:
                    staged.append(source)
                    self.assertEqual((source / "package.wit").read_bytes(), self.companion.read_bytes())
                    self.assertEqual(
                        (source / "deps/network/package.wit").read_bytes(),
                        (self.dependency / "package.wit").read_bytes(),
                    )
            return self.compiler(arguments, **options)

        with patch.object(validate_contracts.subprocess, "run", side_effect=check_stage) as run:
            with patch("builtins.print"):
                result = self.validate()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[1][3], str(self.research))
        self.assertEqual([command[1] for command in commands],
                         ["--version", "component", "validate", "component", "validate"])
        self.assertEqual(len(staged), 1)
        self.assertFalse(staged[0].exists())
        self.assertEqual(json.loads((self.output / "validation.json").read_text()), result)
        self.assertFalse(result["runtimeQualification"])
        self.assertEqual(result["evidenceKind"], "type-only-contract-validation")
        self.assertEqual(result["sources"], validate_contracts.source_identity(self.repository))
        self.assertEqual(set(result["artifacts"]), {"v1.wasm", "v2.wasm"})
        for name, identity in result["artifacts"].items():
            data = (self.output / name).read_bytes()
            self.assertEqual(identity["bytes"], len(data))
            self.assertEqual(identity["sha256"], validate_contracts.hashlib.sha256(data).hexdigest())

    def test_wrong_tool_version_is_rejected_before_outputs_or_parser_calls(self) -> None:
        for version in ("wasm-tools 1.254.00", "wasm-tools 1.254.0-dev", "other-tool 1.254.0", ""):
            with self.subTest(version=version):
                result = subprocess.CompletedProcess([], 0, version)
                with patch.object(validate_contracts.subprocess, "run", return_value=result) as run:
                    with self.assertRaises(ValueError):
                        self.validate()
                run.assert_called_once()
                self.assertFalse(self.output.exists())

    def test_repository_pin_not_a_duplicate_constant_selects_the_compiler(self) -> None:
        (self.repository / "tools/toolchain.toml").write_text(
            '[contracts]\nwasm-tools = "2.0.0"\n', encoding="utf-8",
        )
        with patch.object(validate_contracts.subprocess, "run", side_effect=self.compiler):
            with self.assertRaisesRegex(ValueError, "Expected wasm-tools 2.0.0"):
                self.validate()
        self.assertFalse(self.output.exists())

    def test_each_parser_and_validator_failure_has_no_completion_or_published_artifacts(self) -> None:
        for index in range(1, 5):
            with self.subTest(command=index):
                self.output = self.root / f"failure-{index}"
                calls = []

                def fail(arguments, **options):
                    calls.append(arguments)
                    if len(calls) == index + 1:
                        raise subprocess.CalledProcessError(9, arguments)
                    return self.compiler(arguments, **options)

                with patch.object(validate_contracts.subprocess, "run", side_effect=fail):
                    with patch("builtins.print") as report:
                        with self.assertRaises(subprocess.CalledProcessError):
                            self.validate()
                self.assertEqual(len(calls), index + 1)
                self.assertEqual(list(self.output.iterdir()), [])
                report.assert_not_called()

    def test_timeout_is_failure_and_retires_temporary_staging(self) -> None:
        def timeout(arguments, **options):
            if arguments[1:3] == ["component", "wit"]:
                raise subprocess.TimeoutExpired(arguments, options["timeout"])
            return self.compiler(arguments, **options)

        with patch.object(validate_contracts.subprocess, "run", side_effect=timeout):
            with patch("builtins.print") as report:
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.validate()
        self.assertEqual(list(self.output.iterdir()), [])
        report.assert_not_called()

    def test_success_exit_without_new_artifact_is_not_validation(self) -> None:
        for empty in (False, True):
            with self.subTest(empty=empty):
                self.output = self.root / f"missing-{empty}"

                def incomplete(arguments, **options):
                    if arguments[1:3] == ["component", "wit"]:
                        if empty:
                            Path(arguments[-1]).touch()
                        return subprocess.CompletedProcess(arguments, 0)
                    return self.compiler(arguments, **options)

                with patch.object(validate_contracts.subprocess, "run", side_effect=incomplete):
                    with patch("builtins.print") as report:
                        with self.assertRaises((FileNotFoundError, ValueError)):
                            self.validate()
                self.assertEqual(list(self.output.iterdir()), [])
                report.assert_not_called()

    def test_existing_output_and_its_evidence_are_never_reused_or_overwritten(self) -> None:
        self.output.mkdir()
        previous = self.output / "validation.json"
        previous.write_bytes(b"previous result must survive")
        with patch.object(validate_contracts.subprocess, "run") as run:
            with self.assertRaises(FileExistsError):
                self.validate()
        run.assert_not_called()
        self.assertEqual(previous.read_bytes(), b"previous result must survive")

    def test_generated_outputs_cannot_pollute_source_packages(self) -> None:
        for output in (self.research, self.research / "generated", self.dependency / "generated"):
            with self.subTest(output=output):
                with patch.object(validate_contracts.subprocess, "run") as run:
                    with self.assertRaises(ValueError):
                        validate_contracts.validate(self.repository, output, "wasm-tools")
                run.assert_not_called()

    def test_changed_source_or_pin_cannot_receive_a_success_observation(self) -> None:
        for path in (self.companion, self.repository / "tools/toolchain.toml"):
            original = path.read_bytes()
            self.output = self.root / path.suffix.removeprefix(".")

            def mutate(arguments, **options):
                result = self.compiler(arguments, **options)
                if arguments[1] == "validate":
                    path.write_bytes(original + b"\n")
                return result

            with self.subTest(path=path):
                with patch.object(validate_contracts.subprocess, "run", side_effect=mutate):
                    with patch("builtins.print") as report:
                        with self.assertRaisesRegex(ValueError, "changed during validation"):
                            self.validate()
                self.assertEqual(list(self.output.iterdir()), [])
                report.assert_not_called()
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
