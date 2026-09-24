"""Select the existing Cargo harness and confine disposable S3 cleanup."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "run_s3_blob_tests.py"
SPEC = importlib.util.spec_from_file_location("s3_runner", SCRIPT)
RUNNER = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(SCRIPT.parent), *sys.path]):
    SPEC.loader.exec_module(RUNNER)


class S3RunnerTests(unittest.TestCase):
    def test_reuses_only_the_named_harness_inside_the_cargo_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            executable = target / "s3_blobs"
            executable.touch()
            manifest = root / "cargo.jsonl"
            artifact = {"reason": "compiler-artifact", "target": {"name": "s3_blobs"},
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
            for items in [[], [{"reason": "compiler-artifact", "target": {"name": "s3_blobs"},
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


class SourceBuiltImageRunnerTests(unittest.TestCase):
    """Exercise orchestration with all network, Docker and harness calls mocked."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.image = "sha256:" + "a" * 64
        self.identity = "b" * 64
        self.token = "c" * 32
        self.args = SimpleNamespace(image_receipt=self.root / "fixture.json", cargo_container=None,
                                    test_manifest=self.root / "cargo.jsonl", workspace="/workspace")
        self.info = {"Id": self.identity, "Image": self.image,
                     "Config": {"Labels": {RUNNER.LABEL: self.token}},
                     "NetworkSettings": {"Ports": {"9000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "32123"}]}}}

    def patches(self, info=None, returncode=0):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(redirect_stdout(io.StringIO()))
        stack.enter_context(patch.object(RUNNER.uuid, "uuid4", return_value=SimpleNamespace(hex=self.token)))
        self.certificates = stack.enter_context(patch.object(RUNNER, "certificates"))
        stack.enter_context(patch.object(RUNNER.shutil, "copyfile"))
        self.client = stack.enter_context(patch.object(RUNNER, "Client"))
        self.cleanup = stack.enter_context(patch.object(RUNNER, "close"))
        self.resolve = stack.enter_context(patch.object(RUNNER, "image_from_receipt", return_value=self.image))
        self.selection = stack.enter_context(patch.object(RUNNER, "test_command", return_value=["prepared-s3", "real_s3_", "--ignored"]))
        self.harness = stack.enter_context(patch.object(RUNNER.subprocess, "run", return_value=subprocess.CompletedProcess([], returncode)))

        def command(arguments, **_options):
            if arguments[:2] == ["docker", "run"]:
                return self.identity
            if arguments == ["docker", "inspect", self.identity]:
                return json.dumps([self.info if info is None else info])
            raise AssertionError("unexpected external command: " + repr(arguments))

        self.command = stack.enter_context(patch.object(RUNNER, "command", side_effect=command))
        return stack

    def test_invalid_supplied_receipt_never_rebuilds_pulls_or_starts_server(self):
        self.patches()
        original = RuntimeError("invalid immutable image receipt")
        self.resolve.side_effect = original
        with self.assertRaises(RuntimeError) as caught:
            RUNNER.run(self.args, self.root)
        self.assertIs(caught.exception, original)
        self.command.assert_not_called()
        self.certificates.assert_not_called()
        self.harness.assert_not_called()
        self.cleanup.assert_not_called()

    def test_supplied_receipt_runs_exact_image_without_pull_or_changed_server_limits(self):
        self.patches(returncode=7)
        self.assertEqual(RUNNER.run(self.args, self.root), 7)
        self.resolve.assert_called_once_with(self.args.image_receipt, self.command)
        self.assertEqual(self.command.call_count, 2)
        launch = self.command.call_args_list[0].args[0]
        self.assertEqual(launch[:3], ["docker", "run", "--pull=never"])
        for option, value in (("--memory", "512m"), ("--memory-swap", "512m"), ("--cpus", "1"),
                              ("--pids-limit", "128"), ("--publish", "127.0.0.1::9000"),
                              ("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges")):
            self.assertEqual(launch.count(option), 1)
            self.assertEqual(launch[launch.index(option) + 1], value)
        self.assertIn("--read-only", launch)
        self.assertIn("/data:rw,nosuid,nodev,size=67108864", launch)
        self.assertIn("/tmp:rw,nosuid,nodev,size=8388608", launch)
        self.assertEqual(launch[launch.index(self.image):],
                         [self.image, "server", "--quiet", "--certs-dir", "/certs", "--address", ":9000", "/data"])
        self.selection.assert_called_once_with(self.args.test_manifest)
        self.harness.assert_called_once()
        self.assertEqual(self.harness.call_args.args[0], ["prepared-s3", "real_s3_", "--ignored"])
        self.assertEqual(self.harness.call_args.kwargs["timeout"], 300)
        self.client.return_value.prepare.assert_called_once_with()
        self.cleanup.assert_called_once_with("lsf-s3-test-" + self.token, self.token, self.identity)

    def test_missing_receipt_rejects_before_commands_certificates_or_harness(self):
        self.args.image_receipt = None
        self.patches()
        with self.assertRaises(RuntimeError):
            RUNNER.run(self.args, self.root)
        self.command.assert_not_called()
        self.certificates.assert_not_called()
        self.resolve.assert_not_called()
        self.client.assert_not_called()
        self.selection.assert_not_called()
        self.harness.assert_not_called()
        self.cleanup.assert_not_called()

    def test_cli_requires_image_receipt_before_creating_temporary_state(self):
        self.patches()
        diagnostic = io.StringIO()
        with patch.object(RUNNER.sys, "argv", ["run_s3_blob_tests.py", "--test-manifest", str(self.args.test_manifest)]), \
                patch.object(RUNNER.tempfile, "TemporaryDirectory") as temporary, \
                patch.object(Path, "mkdir") as mkdir, redirect_stderr(diagnostic):
            with self.assertRaises(SystemExit) as caught:
                RUNNER.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("--image-receipt", diagnostic.getvalue())
            temporary.assert_not_called()
            mkdir.assert_not_called()
        self.command.assert_not_called()
        self.certificates.assert_not_called()
        self.resolve.assert_not_called()
        self.client.assert_not_called()
        self.harness.assert_not_called()
        self.cleanup.assert_not_called()

    def test_server_image_or_ownership_mismatch_stops_before_fixture_effects(self):
        for field in ("Id", "Image", "owner"):
            with self.subTest(field=field):
                info = copy.deepcopy(self.info)
                if field == "owner":
                    info["Config"]["Labels"][RUNNER.LABEL] = "foreign"
                else:
                    info[field] = "foreign"
                with self.patches(info=info):
                    with self.assertRaisesRegex(RuntimeError, "owned immutable fixture image"):
                        RUNNER.run(self.args, self.root)
                    self.client.assert_not_called()
                    self.harness.assert_not_called()
                    self.cleanup.assert_called_once_with("lsf-s3-test-" + self.token, self.token, self.identity)

    def test_harness_exception_is_forwarded_once_after_owned_server_cleanup(self):
        self.patches()
        original = subprocess.TimeoutExpired(["prepared-s3"], 300)
        self.harness.side_effect = original
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            RUNNER.run(self.args, self.root)
        self.assertIs(caught.exception, original)
        self.harness.assert_called_once()
        self.cleanup.assert_called_once_with("lsf-s3-test-" + self.token, self.token, self.identity)


if __name__ == "__main__":
    unittest.main()
