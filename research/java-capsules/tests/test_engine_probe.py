"""Observer ownership tests; no mocked result is an engine qualification."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
with mock.patch.object(sys, "path", [str(PROJECT), *sys.path]):
    spec = importlib.util.spec_from_file_location("java_engine_probe", PROJECT / "engine_probe.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)


class EngineObserverTests(unittest.TestCase):
    def test_generated_target_is_removed_after_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with engine.observer(root) as target:
                self.assertEqual(target.read_text(), engine.WRAPPER)
            self.assertFalse(target.exists())
            self.assertFalse(target.parent.exists())

    def test_generated_target_is_removed_on_exception_or_cancellation(self):
        for failure in (ValueError, KeyboardInterrupt):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaises(failure), engine.observer(root) as target:
                    raise failure()
                self.assertFalse(target.exists())

    def test_existing_target_and_directory_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "crates/latent-wasmtime/examples/java_feasibility_generated.rs"
            target.parent.mkdir(parents=True)
            target.write_text("existing source")
            with self.assertRaises(FileExistsError), engine.observer(root):
                pass
            self.assertEqual(target.read_text(), "existing source")

    def test_changed_owned_target_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "changed-while-owned"), engine.observer(root) as target:
                target.write_text("concurrent change")
            self.assertEqual(target.read_text(), "concurrent change")

    def test_preexisting_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "crates/latent-wasmtime/examples"
            directory.mkdir(parents=True)
            with engine.observer(root):
                pass
            self.assertTrue(directory.is_dir())

    def test_symlinked_parent_cannot_redirect_owned_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            (root / "crates").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "observer-symlink"), engine.observer(root):
                pass
            self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_phase_timeouts_cannot_escape_owned_supervisor_bound(self):
        from probe import Attempt
        with tempfile.TemporaryDirectory() as temporary:
            attempt = Attempt(Path(temporary), {})
            for timeout in (0, -1, 601, float("nan")):
                with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "invalid-phase-timeout"):
                    attempt.run("invalid", [], timeout_seconds=timeout)
