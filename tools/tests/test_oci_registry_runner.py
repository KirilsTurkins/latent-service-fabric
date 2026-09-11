"""Ownership and resource guards of the disposable registry runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "run_oci_registry_tests.py"
SPEC = importlib.util.spec_from_file_location("oci_runner", SCRIPT)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RegistryRunnerTests(unittest.TestCase):
    def test_launch_pins_image_loopback_and_container_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = RUNNER.Registry(Path(temporary))
            replies = ["sha256:image", "container", '[{"HostIp":"127.0.0.1","HostPort":"34567"}]']
            with patch.object(RUNNER, "command", side_effect=replies) as execute:
                self.assertEqual(registry.launch(), "https://127.0.0.1:34567")
            arguments = execute.call_args_list[1].args[0]
            for option, value in [("--memory", "256m"), ("--memory-swap", "256m"),
                                  ("--pids-limit", "64"), ("--publish", "127.0.0.1::5000")]:
                self.assertEqual(arguments[arguments.index(option) + 1], value)
            self.assertIn("/var/lib/registry:rw,nosuid,nodev,size=134217728", arguments)
            self.assertIn("--read-only", arguments)
            self.assertIn("--rm", arguments)
            self.assertEqual(arguments[-3:], [RUNNER.IMAGE, "serve", "/fixtures/config.json"])
            self.assertNotIn("--volume", arguments)

    def test_cleanup_removes_verified_id_only(self) -> None:
        registry = RUNNER.Registry(Path("."))
        identity = "a" * 64
        reply = subprocess.CompletedProcess([], 0, json.dumps({"id": identity,
            "labels": {RUNNER.LABEL: registry.token}}), "")
        with patch.object(RUNNER.subprocess, "run", return_value=reply), patch.object(RUNNER, "command") as execute:
            registry.close()
        self.assertEqual(execute.call_args.args[0], ["docker", "rm", "--force", identity])

    def test_cleanup_rejects_unowned_container_and_daemon_failure(self) -> None:
        registry = RUNNER.Registry(Path("."))
        replies = [subprocess.CompletedProcess([], 0, json.dumps({"id": "b" * 64,
                    "labels": {RUNNER.LABEL: "another-run"}}), ""),
                   subprocess.CompletedProcess([], 1, "", "daemon unavailable")]
        for reply in replies:
            with self.subTest(reply=reply.returncode), patch.object(RUNNER.subprocess, "run", return_value=reply), \
                    patch.object(RUNNER, "command") as execute:
                with self.assertRaises(RuntimeError):
                    registry.close()
                execute.assert_not_called()

    def test_recovery_validates_name_and_does_not_overwrite_other_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state.json"
            state.write_text('{"name":"unrelated","token":"' + "a" * 32 + '"}', encoding="ascii")
            with self.assertRaises(RuntimeError):
                RUNNER.cleanup_state(state)
            registry = RUNNER.Registry(Path(temporary), state)
            original = state.read_bytes()
            with patch.object(RUNNER, "command", return_value="image"):
                with self.assertRaises(FileExistsError):
                    registry.launch()
            absent = subprocess.CompletedProcess([], 1, "", "No such object")
            with patch.object(RUNNER.subprocess, "run", return_value=absent):
                registry.close()
            self.assertEqual(state.read_bytes(), original)

    def test_absent_owned_container_removes_recovery_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state.json"
            registry = RUNNER.Registry(Path(temporary), state)
            state.write_text(json.dumps({"name": registry.name, "token": registry.token}), encoding="ascii")
            absent = subprocess.CompletedProcess([], 1, "", "error: no such container")
            with patch.object(RUNNER.subprocess, "run", return_value=absent):
                RUNNER.cleanup_state(state)
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
