"""Select the existing Cargo harness and confine disposable NATS cleanup."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "run_nats_event_tests.py"
SPEC = importlib.util.spec_from_file_location("nats_runner", SCRIPT)
RUNNER = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(SCRIPT.parent), *sys.path]):
    SPEC.loader.exec_module(RUNNER)


class NatsRunnerTests(unittest.TestCase):
    def test_reuses_only_the_named_harness_inside_the_cargo_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            executable = target / "nats_events"
            executable.touch()
            manifest = root / "cargo.jsonl"
            artifact = {"reason": "compiler-artifact", "target": {"name": "nats_events"},
                        "profile": {"test": True}, "executable": str(executable)}
            manifest.write_text(json.dumps(artifact) + "\n", encoding="utf-8")
            with patch.dict(RUNNER.os.environ, {"CARGO_TARGET_DIR": str(target)}):
                result = RUNNER.test_command(manifest)
                self.assertEqual(result[0], str(executable.resolve()))
                self.assertNotIn("cargo", result)
                self.assertIn("--ignored", result)
                outside = root / "unrelated"
                outside.touch()
                artifact["executable"] = str(outside)
                manifest.write_text(json.dumps(artifact), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    RUNNER.test_command(manifest)

    def test_missing_or_ambiguous_cargo_artifacts_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "cargo.jsonl"
            for items in [[], [{"reason": "compiler-artifact", "target": {"name": "nats_events"},
                               "profile": {"test": True}, "executable": name} for name in ["a", "b"]]]:
                manifest.write_text("\n".join(json.dumps(item) for item in items), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    RUNNER.test_command(manifest)

    def test_cleanup_verifies_label_and_immutable_id(self):
        reply = subprocess.CompletedProcess([], 0, json.dumps([{"Id": "owned-id", "Config": {"Labels": {RUNNER.LABEL: "token"}}}]), "")
        with patch.object(RUNNER.subprocess, "run", return_value=reply), patch.object(RUNNER, "command") as execute:
            RUNNER.close("owned-name", "token", "owned-id")
            self.assertEqual(execute.call_args.args[0], ["docker", "rm", "--force", "owned-id"])
            execute.reset_mock()
            for token, identity in [("another-token", "owned-id"), ("token", "another-id")]:
                with self.assertRaises(RuntimeError):
                    RUNNER.close("owned-name", token, identity)
                execute.assert_not_called()

    def test_daemon_failure_cannot_report_successful_cleanup(self):
        failure = subprocess.CompletedProcess([], 1, "", "daemon unavailable")
        absent = subprocess.CompletedProcess([], 1, "", "No such container")
        with patch.object(RUNNER, "command") as execute:
            with patch.object(RUNNER.subprocess, "run", return_value=failure):
                with self.assertRaises(RuntimeError):
                    RUNNER.close("name", "token", None)
            with patch.object(RUNNER.subprocess, "run", return_value=absent):
                RUNNER.close("name", "token", None)
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
