"""CLI presentation after successful semantic replay; no benchmark execution."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import validate_optimization_backend_revision as cli
from tools.optimization_evidence.common import canonical


class BackendValidatorCliTests(unittest.TestCase):
    def invoke(self, value, *, compared=None, output=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite, aggregate, destination = root / "suite.json", root / "aggregate.json", root / "new.json"
            suite.write_bytes(b"{}")
            argv = ["validator", str(suite)]
            if compared is not None:
                aggregate.write_bytes(canonical(compared))
                argv += ["--aggregate", str(aggregate)]
            if output:
                argv += ["--output", str(destination)]
            stdout, stderr = io.StringIO(), io.StringIO()
            # Isolate the CLI contract; validators' actual fixture tests prove
            # semantic replay separately. These are not qualifying raw graphs.
            with patch.object(cli, "validate_suite", return_value=value) as replay, \
                    patch.object(cli.sys, "argv", argv), redirect_stdout(stdout), redirect_stderr(stderr):
                status = cli.main()
            replay.assert_called_once_with(suite)
            return status, stdout.getvalue(), stderr.getvalue(), destination.read_bytes() if destination.exists() else None

    def test_ownership_smoke_and_full_display_attempts_after_equal_aggregate(self):
        for status, count in (("incomplete", "88"), ("complete", "3160")):
            value = {"schema": "latent.optimization.ownership-aggregate.v1", "status": status,
                     "validated_attempts": count, "population_complete": True}
            code, stdout, stderr, output = self.invoke(value, compared=value, output=True)
            self.assertEqual(code, 0)
            self.assertEqual(stdout, f"{status}: {count} invocations; population_complete=True\n")
            self.assertEqual(stderr, "")
            self.assertEqual(output, canonical(value) + b"\n")

    def test_all_historical_schemas_keep_their_call_field_and_unit(self):
        for name in ("backend-revision", "cold", "cache-behavior", "budget-lifecycle", "recovery"):
            value = {"schema": f"latent.optimization.{name}-aggregate.v1", "status": "complete",
                     "validated_calls": "12", "population_complete": True}
            code, stdout, stderr, _ = self.invoke(value, compared=value)
            self.assertEqual((code, stdout, stderr), (0, "complete: 12 calls; population_complete=True\n", ""))

    def test_engine_smoke_and_full_display_attempts_after_equal_aggregate(self):
        for status, count in (("incomplete", "260"), ("complete", "27790")):
            with self.subTest(status=status):
                value = {"schema": "latent.optimization.engine-aggregate.v1", "status": status,
                         "validated_attempts": count, "population_complete": True}
                code, stdout, stderr, output = self.invoke(value, compared=value, output=True)
                self.assertEqual(code, 0)
                self.assertEqual(stdout, f"{status}: {count} invocations; population_complete=True\n")
                self.assertEqual(stderr, "")
                self.assertEqual(output, canonical(value) + b"\n")

    def test_changed_engine_aggregate_still_fails_before_output_or_success_display(self):
        value = {"schema": "latent.optimization.engine-aggregate.v1", "status": "complete",
                 "validated_attempts": "27790", "population_complete": True}
        code, stdout, stderr, output = self.invoke(value, compared=dict(value, validated_attempts="27789"), output=True)
        self.assertEqual((code, stdout, output), (1, "", None))
        self.assertIn("backend-aggregate-does-not-replay", stderr)

    def test_failed_engine_replay_retains_nonzero_cli_status(self):
        value = {"schema": "latent.optimization.engine-aggregate.v1", "status": "failed",
                 "validated_attempts": "0", "population_complete": False}
        code, stdout, stderr, _ = self.invoke(value)
        self.assertEqual((code, stdout, stderr), (1, "failed: 0 invocations; population_complete=False\n", ""))

    def test_changed_aggregate_still_fails_before_output_or_success_display(self):
        value = {"schema": "latent.optimization.ownership-aggregate.v1", "status": "incomplete",
                 "validated_attempts": "88", "population_complete": True}
        code, stdout, stderr, output = self.invoke(value, compared=dict(value, validated_attempts="87"), output=True)
        self.assertEqual((code, stdout, output), (1, "", None))
        self.assertIn("backend-aggregate-does-not-replay", stderr)

    def test_failed_ownership_replay_retains_nonzero_cli_status(self):
        value = {"schema": "latent.optimization.ownership-aggregate.v1", "status": "failed",
                 "validated_attempts": "0", "population_complete": False}
        code, stdout, stderr, _ = self.invoke(value)
        self.assertEqual((code, stdout, stderr), (1, "failed: 0 invocations; population_complete=False\n", ""))

    def test_unrecognized_schema_cannot_guess_a_count_or_write_an_output(self):
        value = {"schema": "latent.optimization.unknown-aggregate.v1", "status": "complete",
                 "validated_attempts": "88", "validated_calls": "12", "population_complete": True}
        code, stdout, stderr, output = self.invoke(value, output=True)
        self.assertEqual((code, stdout, output), (1, "", None))
        self.assertIn("unsupported-backend-aggregate-display-schema", stderr)

    def test_catalog_mutation_displays_all_commands_and_requires_identical_replay(self):
        value = {"schema": "latent.optimization.catalog-mutation-aggregate.v1", "status": "complete",
                 "validated_commands": "45592", "population_complete": True}
        code, stdout, stderr, output = self.invoke(value, compared=value, output=True)
        self.assertEqual((code, stdout, stderr),
                         (0, "complete: 45592 catalog operations; population_complete=True\n", ""))
        self.assertEqual(output, canonical(value) + b"\n")
        code, stdout, stderr, output = self.invoke(value, compared=dict(value, validated_commands="45591"), output=True)
        self.assertEqual((code, stdout, output), (1, "", None))
        self.assertIn("backend-aggregate-does-not-replay", stderr)


if __name__ == "__main__":
    unittest.main()
