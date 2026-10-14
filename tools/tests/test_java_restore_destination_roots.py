"""Actual directory controls; mocked stopped-native proof is not qualification."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os
import stat
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import restore_destination_roots as roots


class RestoreDestinationRoots(unittest.TestCase):
    @contextmanager
    def fixture(self, *, stopped=True):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            scope = work / 'recovery'
            scope.mkdir(mode=0o700)
            client_directory = work / 'client'
            client_directory.mkdir(mode=0o700)
            data = scope / 'data'
            data.mkdir(mode=0o700)
            client = SimpleNamespace(directory=client_directory, deadline=time.monotonic() + 30,
                                     node=None, cancellation=SimpleNamespace(check=Mock()))
            node = SimpleNamespace(process=None, shutdown=[])
            if stopped:
                with patch.object(roots, 'require_stopped_owner') as proof:
                    yield client, node, scope, data / 'state', scope / 'checkpoint', proof
            else:
                yield client, node, scope, data / 'state', scope / 'checkpoint', None

    def test_creates_only_two_empty_directories_and_reports_no_authority_or_files(self):
        with self.fixture() as (client, node, scope, state, checkpoint, proof):
            observed = roots.provision(client, node, scope, state, checkpoint)
            proof.assert_called_once_with(client, node)
            self.assertTrue(state.is_dir())
            self.assertTrue(checkpoint.is_dir())
            self.assertEqual(list(state.iterdir()), [])
            self.assertEqual(list(checkpoint.iterdir()), [])
            self.assertEqual(set(scope.iterdir()), {state.parent, checkpoint})
            self.assertEqual(list(client.directory.iterdir()), [])
            self.assertNotEqual(scope, client.directory)
            self.assertEqual(observed['directoriesCreated'], 2)
            self.assertEqual(observed['durableFilesCreated'], 0)
            self.assertFalse(observed['currentAuthorityInferred'])
            self.assertEqual(observed['posixModeObserved'], os.name == 'posix')
            if os.name == 'posix':
                self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(checkpoint.stat().st_mode), 0o700)

    def test_missing_stopped_owner_refuses_before_directory_creation(self):
        with self.fixture(stopped=False) as (client, node, scope, state, checkpoint, _):
            with self.assertRaisesRegex(ValueError, 'positive-original-node-retirement-required'):
                roots.provision(client, node, scope, state, checkpoint)
            self.assertFalse(state.exists())
            self.assertFalse(checkpoint.exists())

    def test_preexisting_directory_is_not_reused_or_changed(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            state.mkdir(mode=0o700)
            sentinel = state / 'retained'
            sentinel.write_bytes(b'original evidence')
            with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                roots.provision(client, node, scope, state, checkpoint)
            self.assertEqual(sentinel.read_bytes(), b'original evidence')
            self.assertFalse(checkpoint.exists())

    def test_preexisting_second_root_refuses_before_creating_first(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            checkpoint.mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                roots.provision(client, node, scope, state, checkpoint)
            self.assertFalse(state.exists())
            self.assertEqual(list(checkpoint.iterdir()), [])

    def test_existing_file_is_preserved_and_refused(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            state.write_bytes(b'failed native receipt')
            with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                roots.provision(client, node, scope, state, checkpoint)
            self.assertEqual(state.read_bytes(), b'failed native receipt')
            self.assertFalse(checkpoint.exists())

    def test_equal_and_nested_paths_are_refused_without_creation(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            for other in (state, state / 'nested', state.parent):
                with self.subTest(other=other), self.assertRaisesRegex(ValueError, 'independent-restore'):
                    roots.provision(client, node, scope, state, other)
            self.assertFalse(state.exists())
            self.assertFalse(checkpoint.exists())

    def test_relative_and_outside_owner_paths_are_refused_without_creation(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            for other in (Path('relative-state'), client.directory / 'unowned-state'):
                with self.subTest(other=other), self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                    roots.provision(client, node, scope, other, checkpoint)
            self.assertFalse(state.exists())
            self.assertFalse(checkpoint.exists())

    def test_missing_parent_is_not_provisioned(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            absent = scope / 'missing'
            with self.assertRaises((FileNotFoundError, ValueError)):
                roots.provision(client, node, scope, absent / 'state', checkpoint)
            self.assertFalse(absent.exists())
            self.assertFalse(checkpoint.exists())

    def symlink(self, destination, target):
        try:
            destination.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest('host does not permit a file-system symlink')

    def test_existing_and_dangling_symlinks_are_refused(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            target = scope / 'retained'
            self.symlink(state, target)
            for existing in (False, True):
                with self.subTest(existing=existing):
                    if existing:
                        target.mkdir(mode=0o700)
                    with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                        roots.provision(client, node, scope, state, checkpoint)
                    self.assertTrue(state.is_symlink())
                    self.assertEqual(target.exists(), existing)
                    self.assertFalse(checkpoint.exists())

    def test_symlinked_parent_cannot_redirect_creation(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            alias = scope / 'alias'
            self.symlink(alias, state.parent)
            with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                roots.provision(client, node, scope, alias / 'state', checkpoint)
            self.assertFalse(state.exists())
            self.assertFalse(checkpoint.exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX directory mode requires a POSIX host')
    def test_actual_nonprivate_parent_is_refused_without_chmod_or_creation(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            for parent in (scope, state.parent):
                with self.subTest(parent=parent):
                    parent.chmod(0o755)
                    with self.assertRaisesRegex(ValueError, 'private-restore'):
                        roots.provision(client, node, scope, state, checkpoint)
                    self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o755)
                    self.assertFalse(state.exists())
                    self.assertFalse(checkpoint.exists())
                    parent.chmod(0o700)

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'owned UID requires a POSIX host')
    def test_foreign_uid_is_refused_without_creation(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            with patch.object(os, 'geteuid', return_value=os.geteuid() + 1):
                with self.assertRaisesRegex(ValueError, 'owned-restore'):
                    roots.provision(client, node, scope, state, checkpoint)
            self.assertFalse(state.exists())
            self.assertFalse(checkpoint.exists())

    def test_expired_original_deadline_refuses_before_creation(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            client.deadline = time.monotonic() - 1
            with self.assertRaisesRegex(ValueError, 'restore-destination-root-deadline'):
                roots.provision(client, node, scope, state, checkpoint)
            self.assertFalse(state.exists())
            self.assertFalse(checkpoint.exists())

    def test_original_cancellation_refuses_before_creation(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            client.cancellation.check.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                roots.provision(client, node, scope, state, checkpoint)
            self.assertFalse(state.exists())
            self.assertFalse(checkpoint.exists())

    def test_cancellation_between_roots_retains_first_empty_failed_directory(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            client.cancellation.check.side_effect = [None, None, KeyboardInterrupt]
            with self.assertRaises(KeyboardInterrupt):
                roots.provision(client, node, scope, state, checkpoint)
            self.assertTrue(state.is_dir())
            self.assertEqual(list(state.iterdir()), [])
            self.assertFalse(checkpoint.exists())

    def test_deadline_between_roots_retains_first_without_renewal(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            deadline = client.deadline
            with patch.object(roots.time, 'monotonic', side_effect=[deadline - 1, deadline - 1, deadline]):
                with self.assertRaisesRegex(ValueError, 'restore-destination-root-deadline'):
                    roots.provision(client, node, scope, state, checkpoint)
            self.assertEqual(client.deadline, deadline)
            self.assertTrue(state.is_dir())
            self.assertFalse(checkpoint.exists())

    def test_second_creation_error_preserves_first_and_original_error(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            mkdir = Path.mkdir
            def refuse(path, *args, **kwargs):
                if path == checkpoint:
                    raise PermissionError('controlled creation refusal')
                return mkdir(path, *args, **kwargs)
            with patch.object(Path, 'mkdir', refuse):
                with self.assertRaisesRegex(PermissionError, 'controlled creation refusal'):
                    roots.provision(client, node, scope, state, checkpoint)
            self.assertTrue(state.is_dir())
            self.assertEqual(list(state.iterdir()), [])
            self.assertFalse(checkpoint.exists())

    def test_final_emptiness_refusal_does_not_remove_unexpected_file(self):
        with self.fixture() as (client, node, scope, state, checkpoint, _):
            calls = 0
            def injected():
                nonlocal calls
                calls += 1
                if calls == 4:
                    (state / 'unexpected').write_bytes(b'retained failure')
            client.cancellation.check.side_effect = injected
            with self.assertRaisesRegex(ValueError, 'empty-restore'):
                roots.provision(client, node, scope, state, checkpoint)
            self.assertEqual((state / 'unexpected').read_bytes(), b'retained failure')
            self.assertTrue(checkpoint.is_dir())


if __name__ == '__main__':
    unittest.main()
