"""Read-only readiness timeouts keep their original finite observation window."""
from contextlib import contextmanager, ExitStack, nullcontext
import copy
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.native_runtime import checks
from tools.native_runtime.common import InstallError, encode


class ReadinessFixture:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def reply(self):
        return {"schemaVersion": "latent.cli.result.v1", "category": "success",
            "data": {"inventory": {
                "node": {"id": "test-node", "attributes": {"lsf.security.profile": "local-experimental-v1"}},
                "health": {"ready": True}, "pressure": {"loadAvailable": True}}}}


@contextmanager
def readiness_fixture():
    fixture = ReadinessFixture()
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as owned:
        root = Path(temporary)
        fixture.layout = SimpleNamespace(cache=root, data=root)
        for name, value in {
            "service_identity": None,
            "load": {"nodeId": "test-node", "securityProfile": "local-experimental-v1"},
            "validate_layout": None, "current": root, "client_document": {},
        }.items():
            owned.enter_context(patch.object(checks, name, return_value=value))
        owned.enter_context(patch.object(checks.os, "geteuid", return_value=23001, create=True))
        owned.enter_context(patch.object(checks.files, "directory", return_value=nullcontext()))
        fixture.create = owned.enter_context(patch.object(checks.files, "create"))
        owned.enter_context(patch.object(checks.time, "monotonic", side_effect=lambda: fixture.now))
        owned.enter_context(patch.object(checks.time, "sleep", side_effect=fixture.sleep))
        fixture.execute = owned.enter_context(patch.object(checks, "execute",
            side_effect=AssertionError("unmocked readiness invocation")))
        yield fixture


class NativeReadinessTimeouts(unittest.TestCase):
    def test_completed_timeout_then_strict_ready_keeps_the_original_poll_window(self):
        with readiness_fixture() as fixture:
            def observe(*_arguments, **limits):
                if fixture.execute.call_count == 1:
                    fixture.now += limits["timeout"]
                    raise InstallError("command-timeout")
                return 0, encode(fixture.reply())
            fixture.execute.side_effect = observe
            try:
                observed = checks.readiness(fixture.layout, timeout=120)
            except InstallError as error:
                observed = {"failure": str(error)}
            self.assertTrue(observed.get("authenticated"),
                            "one completed bounded readiness timeout aborted the original polling window")
            self.assertTrue(observed["activationReady"])
            self.assertEqual(fixture.execute.call_count, 2)
            self.assertEqual(fixture.sleeps, [0.5])
            for call in fixture.execute.call_args_list:
                self.assertEqual(call.kwargs["timeout"], 2)
                self.assertEqual(call.kwargs["maximum"], 262144)
                self.assertEqual(call.args[0][-3:], ["node", "get", "test-node"])
                self.assertIn("500", call.args[0])
                self.assertIn("1000", call.args[0])

    def test_repeated_completed_timeouts_exhaust_the_original_absolute_cutoff(self):
        with readiness_fixture() as fixture:
            def timeout(*_arguments, **limits):
                fixture.now += limits["timeout"]
                raise InstallError("command-timeout")
            fixture.execute.side_effect = timeout
            with self.assertRaisesRegex(InstallError, "activation-readiness-failed-inspect-local-journal-and-check-config"):
                checks.readiness(fixture.layout, timeout=120)
            self.assertEqual(fixture.now, 120)
            self.assertEqual(fixture.execute.call_count, 48)
            self.assertTrue(all(call.kwargs["timeout"] == 2 for call in fixture.execute.call_args_list))

    def test_final_timeout_is_clipped_to_remaining_setup_and_poll_budget(self):
        with readiness_fixture() as fixture:
            fixture.create.side_effect = lambda *_arguments: setattr(fixture, "now", 119.75)
            def timeout(*_arguments, **limits):
                fixture.now += limits["timeout"]
                raise InstallError("command-timeout")
            fixture.execute.side_effect = timeout
            with self.assertRaisesRegex(InstallError, "activation-readiness-failed-inspect-local-journal-and-check-config"):
                checks.readiness(fixture.layout, timeout=120)
            self.assertEqual(fixture.execute.call_count, 1)
            self.assertEqual(fixture.execute.call_args.kwargs["timeout"], 0.25)
            self.assertEqual(fixture.now, 120)
            self.assertEqual(fixture.sleeps, [0])

    def test_other_errors_and_cleanup_faults_remain_fatal_without_another_read(self):
        class CleanupError(InstallError):
            pass
        for error in (InstallError("command-output-limit"), InstallError("linux-required"),
                      CleanupError("command-timeout"), subprocess.TimeoutExpired(["readiness-fixture"], 5),
                      RuntimeError("cleanup-unconfirmed")):
            with self.subTest(error=type(error).__name__), readiness_fixture() as fixture:
                fixture.execute.side_effect = error
                with self.assertRaises(type(error)) as failure:
                    checks.readiness(fixture.layout, timeout=120)
                self.assertIs(failure.exception, error)
                self.assertEqual(fixture.execute.call_count, 1)
                self.assertEqual(fixture.sleeps, [])

    def test_timeout_cannot_qualify_wrong_identity_profile_readiness_or_load(self):
        for field in ("identity", "profile", "ready", "load", "schema", "category"):
            with self.subTest(field=field), readiness_fixture() as fixture:
                reply = copy.deepcopy(fixture.reply())
                inventory = reply["data"]["inventory"]
                if field == "identity":
                    inventory["node"]["id"] = "foreign-node"
                elif field == "profile":
                    inventory["node"]["attributes"]["lsf.security.profile"] = "foreign-profile"
                elif field == "ready":
                    inventory["health"]["ready"] = False
                elif field == "load":
                    inventory["pressure"]["loadAvailable"] = False
                elif field == "schema":
                    reply["schemaVersion"] = "foreign-schema"
                else:
                    reply["category"] = "transport-failure"
                def observe(*_arguments, **limits):
                    fixture.now += limits["timeout"]
                    if fixture.execute.call_count == 1:
                        raise InstallError("command-timeout")
                    return 0, encode(reply)
                fixture.execute.side_effect = observe
                with self.assertRaisesRegex(InstallError, "activation-readiness-failed-inspect-local-journal-and-check-config"):
                    checks.readiness(fixture.layout, timeout=120)
                self.assertEqual(fixture.now, 120)
                self.assertGreater(fixture.execute.call_count, 1)

    def test_invalid_reply_after_timeout_stays_fatal_without_a_third_read(self):
        with readiness_fixture() as fixture:
            fixture.execute.side_effect = [InstallError("command-timeout"), (0, b"not-json")]
            with self.assertRaisesRegex(InstallError, "invalid-document"):
                checks.readiness(fixture.layout, timeout=120)
            self.assertEqual(fixture.execute.call_count, 2)
            self.assertEqual(fixture.sleeps, [0.5])


if __name__ == "__main__":
    unittest.main()
