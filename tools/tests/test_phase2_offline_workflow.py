"""Exercise the real cancellation/temp lifetime without Docker or executables."""
from contextlib import redirect_stdout
import io
import signal
import unittest
from unittest.mock import Mock, patch

from tools import run_phase2_offline_workflow as workflow


class OfflineWorkflowLifetimeTests(unittest.TestCase):
    def setUp(self):
        # Model the host's default handlers instead of sending an OS signal to
        # the test runner. The real owned_cancellation context installs, records,
        # delivers and restores handlers against this small registry.
        numbers = [signal.SIGINT, signal.SIGTERM]
        if hasattr(signal, "SIGBREAK"):
            numbers.append(signal.SIGBREAK)
        self.original_handlers = dict.fromkeys(numbers, signal.SIG_DFL)
        self.handlers = dict(self.original_handlers)

        def install(number, handler):
            previous = self.handlers[number]
            self.handlers[number] = handler
            return previous

        self.enterContext(patch.object(signal, "getsignal", side_effect=self.handlers.__getitem__))
        self.enterContext(patch.object(signal, "signal", side_effect=install))
        self.enterContext(patch.object(workflow.sys, "argv", [
            "offline-workflow", "--cli", "/fixture/latent", "--node", "/fixture/latentd",
            "--fixture-root", "/fixture/inputs", "--source-commit", "1" * 40,
        ]))
        self.directories = []
        self.registry = Mock()
        self.registry.launch.return_value = "https://127.0.0.1:5000"

        def registry(directory):
            self.assertTrue(directory.is_dir())
            (directory / "owned-fixture").write_bytes(b"public test material")
            self.directories.append(directory)
            return self.registry

        self.enterContext(patch.object(workflow, "Registry", side_effect=registry))
        self.certificates = self.enterContext(patch.object(workflow, "certificates"))
        self.ready = self.enterContext(patch.object(workflow, "ready"))
        self.run = self.enterContext(patch.object(workflow, "run", return_value='{"passed":true}'))
        self.stdout = self.enterContext(redirect_stdout(io.StringIO()))

    def interrupt(self, *_args):
        handler = self.handlers[signal.SIGTERM]
        self.assertTrue(callable(handler), "registry lifetime has no cleanup-aware signal owner")
        # Delivery must be deferred until a protected explicit checkpoint.
        handler(signal.SIGTERM, None)

    def assert_clean_failure(self):
        self.assertEqual(self.stdout.getvalue(), "", "a failure emitted a success receipt")
        self.registry.close.assert_called_once_with()
        self.assertEqual(len(self.directories), 1)
        self.assertFalse(self.directories[0].exists())
        self.assertEqual(self.handlers, self.original_handlers)

    def test_setup_cancellation_cleans_launched_registry_before_any_scenario(self):
        def launch():
            self.interrupt()
            return "https://127.0.0.1:5000"

        self.registry.launch.side_effect = launch
        with self.assertRaises(SystemExit) as stopped:
            workflow.main()
        self.assertEqual(stopped.exception.code, 128 + signal.SIGTERM)
        self.run.assert_not_called()
        self.assert_clean_failure()

    def test_readiness_failure_cleans_registry_and_never_runs_scenario(self):
        self.ready.side_effect = RuntimeError("fixed readiness failure")
        with self.assertRaisesRegex(RuntimeError, "fixed readiness failure"):
            workflow.main()
        self.run.assert_not_called()
        self.assert_clean_failure()

    def test_repeated_cleanup_cancellation_suppresses_an_already_computed_receipt(self):
        completed = []

        def close():
            self.interrupt()
            self.interrupt()
            completed.append(True)

        self.registry.close.side_effect = close
        with self.assertRaises(SystemExit) as stopped:
            workflow.main()
        self.assertEqual(stopped.exception.code, 128 + signal.SIGTERM)
        self.run.assert_called_once()
        self.assertEqual(completed, [True], "cancellation abandoned registry cleanup")
        self.assert_clean_failure()

    def test_unconfirmed_registry_cleanup_never_emits_a_success_receipt(self):
        self.registry.close.side_effect = RuntimeError("fixed cleanup failure")
        with self.assertRaisesRegex(RuntimeError, "fixed cleanup failure"):
            workflow.main()
        self.run.assert_called_once()
        self.assert_clean_failure()


if __name__ == "__main__":
    unittest.main()
