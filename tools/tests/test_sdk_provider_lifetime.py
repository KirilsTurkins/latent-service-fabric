"""The owned fixture must cover its caller, never extend the caller's deadline."""
import io
import json
from contextlib import nullcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.phase2_operator_process import WorkflowError
from tools import sdk_provider_http_fixture as fixture
from tools.sdk_provider_scenario import close_failed_provider, start_provider


class ProviderLifetimeTests(unittest.TestCase):
    def client(self, deadline=2000):
        return SimpleNamespace(deadline=deadline, environment={}, cancellation=Mock())

    def test_default_explicit_and_shorter_owner_use_absolute_expiry_despite_startup_delay(self):
        for owner, maximum, expected in ((2000, None, 400), (2000, 900, 1000), (2000, 1200, 1300),
                                         (150, 900, 150), (150, None, 150)):
            with self.subTest(owner=owner, maximum=maximum):
                process = Mock()
                process.line.return_value = {"port": 12345}
                options = {} if maximum is None else {"maximum_seconds": maximum}
                with patch("tools.sdk_provider_scenario.Process", return_value=process) as launch, \
                     patch("tools.sdk_provider_scenario.time.monotonic", side_effect=(100, 105)):
                    actual, port = start_provider(self.client(owner), Path("control"), **options)
                self.assertIs(actual, process)
                self.assertEqual(port, 12345)
                self.assertEqual(launch.call_count, 1)
                self.assertEqual(launch.call_args.args[0][-2:], ["--deadline-monotonic", str(expected)])
                self.assertEqual(launch.call_args.kwargs, {"maximum": 4096})
                process.line.assert_called_once_with(min(expected, 115))
                process.close.assert_not_called()
                with patch.object(fixture.time, "monotonic", return_value=105):
                    self.assertEqual(fixture.expiry(expected), expected)

    def test_invalid_owner_or_lifetime_fails_before_process_creation(self):
        for maximum in (True, 0, -1, 1200.0, 1201, float("inf"), None):
            with self.subTest(maximum=maximum), \
                 patch("tools.sdk_provider_scenario.Process") as launch, \
                 self.assertRaisesRegex(WorkflowError, "lifetime-bound"):
                start_provider(self.client(), Path("control"), maximum_seconds=maximum)
            launch.assert_not_called()
        for owner in (True, 100, 99, float("nan"), float("inf"), "2000"):
            with self.subTest(owner=owner), \
                 patch("tools.sdk_provider_scenario.Process") as launch, \
                 patch("tools.sdk_provider_scenario.time.monotonic", return_value=100), \
                 self.assertRaisesRegex(WorkflowError, "owner-deadline"):
                start_provider(self.client(owner), Path("control"), maximum_seconds=900)
            launch.assert_not_called()

    def test_child_rejects_invalid_or_startup_expired_deadline_before_opening_listener(self):
        for deadline in (True, 100, 99, float("nan"), float("inf"), 1301, "200"):
            with self.subTest(deadline=deadline), \
                 patch.object(fixture.time, "monotonic", return_value=100), \
                 patch.object(fixture.socket, "socket") as create, \
                 self.assertRaisesRegex(ValueError, "invalid provider fixture deadline"):
                fixture.run(Path("unused"), deadline=deadline)
            create.assert_not_called()
        with patch.object(fixture.time, "monotonic", return_value=100):
            self.assertEqual(fixture.expiry(), 400)

    def test_real_loop_keeps_default300_and_stops_at_explicit1200_without_reset(self):
        for deadline, expected_accepts in ((None, 1), (1300, 2)):
            with self.subTest(deadline=deadline):
                now = [100]
                listener = Mock()
                listener.getsockname.return_value = ("127.0.0.1", 12345)
                def accept():
                    now[0] = 401 if now[0] == 100 else 1300
                    raise TimeoutError()
                listener.accept.side_effect = accept
                context = Mock(__enter__=Mock(return_value=listener), __exit__=Mock(return_value=False))
                with patch.object(fixture, "STOPPING", False), \
                     patch.object(fixture.time, "monotonic", side_effect=lambda: now[0]), \
                     patch.object(fixture.socket, "socket", return_value=context), \
                     patch("sys.stdout", io.StringIO()), \
                     self.assertRaises(fixture.ProviderDeadlineExpired):
                    fixture.run(Path("unused"), deadline=deadline)
                self.assertEqual(listener.accept.call_count, expected_accepts)
                context.__exit__.assert_called_once()
                self.assertTrue(all(call.args[0] <= 0.1 for call in listener.settimeout.call_args_list))

    def test_request_and_physical_close_wait_are_clipped_to_owner_without_widening_local_caps(self):
        connection = Mock()
        connection.recv.return_value = b"GET /allowed HTTP/1.1\r\n\r\n"
        with patch.object(fixture.time, "monotonic", return_value=100):
            self.assertEqual(fixture.request(connection, 100.01), (b"GET", False, True))
        self.assertAlmostEqual(connection.settimeout.call_args.args[0], 0.01)
        connection.reset_mock()
        connection.recv.return_value = b""
        with patch.object(fixture, "STOPPING", False), \
             patch.object(fixture.time, "monotonic", return_value=100), \
             patch.object(fixture, "marker") as marker, \
             patch.object(fixture.select, "select", return_value=([connection], [], [])):
            fixture.hold(connection, Path("unused"), "hold-test", 100.025)
        self.assertAlmostEqual(connection.settimeout.call_args.args[0], 0.025)
        connection.recv.assert_called_once_with(1)
        self.assertEqual([call.args[1] for call in marker.call_args_list],
                         ["started-hold-test", "closed-hold-test"])
        for owner, finish, expected in ((100.025, 100.025, fixture.ProviderDeadlineExpired),
                                        (1000, 103, ValueError)):
            now = [100]
            def select(*_args):
                now[0] = finish
                return [], [], []
            with self.subTest(owner=owner), patch.object(fixture, "STOPPING", False), \
                 patch.object(fixture.time, "monotonic", side_effect=lambda: now[0]), \
                 patch.object(fixture, "marker"), \
                 patch.object(fixture.select, "select", side_effect=select) as wait, \
                 self.assertRaises(expected) as failure:
                fixture.hold(connection, Path("unused"), "hold-test", owner)
            self.assertEqual(type(failure.exception), expected)
            self.assertLessEqual(wait.call_args.args[3], 0.05)
            self.assertLessEqual(wait.call_args.args[3], owner - 100)

    def test_request_count_bound_remains32_with_one_attempt_each(self):
        connection = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
        listener = Mock()
        listener.getsockname.return_value = ("127.0.0.1", 12345)
        listener.accept.return_value = connection, ("127.0.0.1", 12346)
        context = Mock(__enter__=Mock(return_value=listener), __exit__=Mock(return_value=False))
        with patch.object(fixture, "STOPPING", False), \
             patch.object(fixture.time, "monotonic", return_value=100), \
             patch.object(fixture.socket, "socket", return_value=context), \
             patch.object(fixture, "request", return_value=(b"GET", True, True)) as request, \
             patch.object(fixture, "mode", return_value="reply"), patch("sys.stdout", io.StringIO()), \
             self.assertRaisesRegex(ValueError, "provider fixture bound expired"):
            fixture.run(Path("unused"), deadline=1000)
        self.assertEqual(request.call_count, 32)
        self.assertEqual(listener.accept.call_count, 32)
        context.__exit__.assert_called_once()

    def test_failed_peer_lifecycle_is_reaped_without_exposing_raw_output_or_rechecking_reaped_pid(self):
        for closed, finished, stderr, fails in ((False, False, b"sdk-provider-fixture-deadline-expired\n", False),
                                                (False, False, b"private arbitrary failure", False),
                                                (True, True, b"sdk-provider-fixture-failed\n", False),
                                                (False, True, b"sdk-provider-fixture-failed\n", False),
                                                (False, False, b"private arbitrary failure", True)):
            with self.subTest(closed=closed, finished=finished, fails=fails):
                process = Mock(closed=closed, buffers=[bytearray(), bytearray(stderr)])
                process.owner.finished = finished
                process.owner.exited.return_value = True
                process.owner.process.returncode = 1
                def close():
                    process.closed = True
                    process.owner.finished = True
                process.close.side_effect = close
                if fails:
                    process.drain.side_effect = RuntimeError("private arbitrary failure")
                observed = close_failed_provider(process)
                self.assertTrue(observed["closed"] and observed["reaped"])
                self.assertEqual(observed["exitedBeforeCleanup"], None if closed or finished else True)
                self.assertEqual(observed["exitCode"], 1)
                self.assertEqual(observed["observationAvailable"], not fails)
                self.assertNotIn("private", repr(observed))
                if closed or finished:
                    process.owner.exited.assert_not_called()
                if closed:
                    process.drain.assert_not_called()
                process.close.assert_called_once()

    def test_observation_and_cleanup_failure_or_cancellation_remain_closed_negative_facts(self):
        for observe_error, close_error in ((RuntimeError("private"), None),
                                           (KeyboardInterrupt(), None),
                                           (None, RuntimeError("private")),
                                           (None, SystemExit(143))):
            with self.subTest(observe=type(observe_error), close=type(close_error)):
                process = Mock(closed=False, buffers=[bytearray(), bytearray(b"private")])
                process.owner.finished = False
                process.owner.exited.return_value = False
                process.owner.process.returncode = None
                process.drain.side_effect = observe_error
                def close():
                    # Real Process.close marks itself closed even when its
                    # owner could not be reaped. Never report that as success.
                    process.closed = True
                    if close_error is not None:
                        raise close_error
                    process.owner.finished = True
                process.close.side_effect = close
                observed = close_failed_provider(process)
                self.assertEqual(observed["reaped"], close_error is None)
                self.assertEqual(observed["observationAvailable"], observe_error is None)
                self.assertEqual(observed["observationError"], "cancelled" if isinstance(observe_error, KeyboardInterrupt)
                                 else "unavailable" if observe_error else "none")
                self.assertEqual(observed["cleanupError"], "cancelled" if isinstance(close_error, SystemExit)
                                 else "cleanup-failed" if close_error else "none")
                self.assertIsNone(observed["exitCode"])
                self.assertNotIn("private", repr(observed))
                process.close.assert_called_once()

    def test_authoring_profile_is_typescript_only_and_cleanup_cannot_erase_original_failure(self):
        from tools import run_rust_capsule_workflow as workflow
        for language, seconds in (("typescript", 1200), ("go", 900), ("dotnet", 900),
                                  ("java", 900), ("rust", 180), ("c", 180)):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                evidence = Path(temporary) / "evidence"
                peer = Mock(closed=False, buffers=[bytearray(), bytearray()])
                peer.owner.exited.return_value = False
                peer.owner.finished = False
                peer.owner.process.returncode = None
                def close():
                    if peer.closed:
                        return
                    peer.closed = True
                    raise RuntimeError("private cleanup failure")
                peer.close.side_effect = close
                recipe = "c-guest" if language == "c" else language + "-capsule"
                metadata = {"schemaVersion": "latent.capsule.demo.v1", "tenant": "examples",
                    "trust": "isolated-short-lived-demo-only", "expiresAtUnixSeconds": 10000,
                    "releases": [{"name": "my-" + name, "buildType": f"https://latent.dev/build/{recipe}/v1"}
                                 for name in workflow.TEMPLATES]}
                with patch.object(workflow.sys, "platform", "linux"), \
                     patch.object(workflow.sys, "version_info", (3, 13)), \
                     patch.object(workflow, "source_identity", return_value={}), \
                     patch.object(workflow, "file_identity", return_value={}), \
                     patch.object(workflow, "read_json", return_value=metadata), \
                     patch.object(workflow.time, "time", return_value=100), \
                     patch.object(workflow.time, "monotonic", return_value=100), \
                     patch.object(workflow, "owned_cancellation", return_value=nullcontext(Mock())), \
                     patch.object(workflow, "RecordingClient") as client, \
                     patch.object(workflow, "start_provider", return_value=(peer, 12345)) as start, \
                     patch.object(workflow, "configure", side_effect=WorkflowError("original-authoring-failure")), \
                     self.assertRaisesRegex(WorkflowError, "original-authoring-failure"):
                    workflow.run(Path("cli"), Path("node"), Path("fixture"), evidence, language=language)
                self.assertEqual(client.call_args.args[3], 100 + seconds)
                invocation = 5000 if language in {"rust", "c"} else 120000
                control = 125000 if language == "typescript" else 15000
                self.assertEqual(client.call_args.kwargs["invocation_timeout_millis"], invocation)
                self.assertEqual(client.call_args.kwargs["control_timeout_millis"], control)
                self.assertEqual(start.call_args.kwargs, {"maximum_seconds": seconds})
                failure = json.loads((evidence / "FAILED.json").read_text())
                self.assertEqual(failure["reason"], "original-authoring-failure")
                self.assertEqual(failure["limits"]["overallSeconds"], seconds)
                self.assertEqual(failure["limits"]["peerSeconds"], seconds)
                self.assertEqual(failure["limits"]["invocationMillis"], invocation)
                self.assertEqual(failure["limits"]["controlMillis"], control)
                self.assertEqual(failure["limits"]["controlProcessSeconds"], 130 if language == "typescript" else 25)
                self.assertEqual(failure["peerFailure"]["cleanupError"], "cleanup-failed")
                self.assertFalse(failure["peerFailure"]["reaped"])
                self.assertFalse((evidence / "workflow.json").exists())


if __name__ == "__main__":
    unittest.main()
