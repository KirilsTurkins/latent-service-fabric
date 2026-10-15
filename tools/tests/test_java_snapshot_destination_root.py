"""Real filesystem layout; mocked native handoffs never qualify a snapshot."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os
import stat
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import offline_campaign, pending_campaign
from tools.java_transaction_qualification import restore_destination_roots as restore_roots
from tools.java_transaction_qualification import snapshot_destination_root as snapshots
from tools.java_transaction_qualification import restore_installation
from tools.tests import test_java_restore_target_identity as identity_controls


class SnapshotDestinationRoot(unittest.TestCase):
    @contextmanager
    def fixture(self, *, pending=False, current=True, stopped=True):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            scope, evidence = work / 'recovery', work / 'client'
            scope.mkdir(mode=0o700)
            evidence.mkdir(mode=0o700)
            client = SimpleNamespace(directory=evidence, node=None, deadline=time.monotonic() + 30,
                cancellation=SimpleNamespace(check=Mock()), evidence=SimpleNamespace(record=Mock()))
            node = SimpleNamespace(process=None, shutdown=[])
            cls = pending_campaign.PendingCampaign if pending else offline_campaign.OfflineCampaign
            subject = cls.__new__(cls)
            subject.directory, subject.client, subject.node, subject.current_v2 = scope, client, node, current
            subject.action = Mock(return_value=object())
            with patch.object(offline_campaign, 'original_snapshot', return_value={'parser-stub': True}) as parse:
                if stopped:
                    with patch.object(snapshots, 'require_stopped_owner'), \
                         patch.object(restore_roots, 'require_stopped_owner'):
                        yield subject, scope, client, parse
                else:
                    yield subject, scope, client, parse

    def separate(self, left, right):
        # Model the existing native rule with actual filesystem identities;
        # this does not run ProtectedRoot or establish native platform support.
        identity = lambda path: (path.stat().st_dev, path.stat().st_ino)
        ancestors = lambda path: {identity(parent) for parent in (path, *path.parents)}
        return identity(left) not in ancestors(right) and identity(right) not in ancestors(left)

    def test_current_collectors_use_three_separate_roots_and_one_original_action(self):
        for pending in (False, True):
            with self.subTest(pending=pending), self.fixture(pending=pending) as (subject, scope, client, parse):
                operation = 'java-pending-backup' if pending else 'java-restore-checkpoint'
                name = 'signed-pending.snapshot' if pending else 'restore-checkpoint-v2.snapshot'
                file, returned = subject.snapshot(name, operation)
                root = Path(file['root'])
                self.assertEqual(root.parent, scope)
                self.assertNotEqual(root, scope)
                self.assertEqual(list(root.iterdir()), [])
                data = scope / ('pending-restored-data' if pending else 'restored-data')
                data.mkdir(mode=0o700)
                state = data / 'state'
                checkpoint = scope / ('pending-restored-checkpoint' if pending else 'restored-checkpoint')
                restore_roots.provision(client, subject.node, scope, state, checkpoint)
                for left, right in ((root, state), (root, checkpoint), (state, checkpoint)):
                    self.assertTrue(self.separate(left, right))
                self.assertFalse(self.separate(scope, state))
                self.assertEqual(list(client.directory.iterdir()), [])
                subject.action.assert_called_once_with({'action': 'snapshot', 'operationId': operation,
                                                       'file': {'root': str(root), 'name': name}})
                parse.assert_called_once_with(subject.action.return_value, operation)
                self.assertEqual(returned, {'parser-stub': True})

    def test_distinct_offline_operations_get_fresh_roots_with_the_same_original_scope(self):
        with self.fixture() as (subject, scope, client, _):
            deadline = client.deadline
            first, _ = subject.snapshot('schema-checkpoint-v1.snapshot', 'java-schema-checkpoint')
            second, _ = subject.snapshot('restore-checkpoint-v2.snapshot', 'java-restore-checkpoint')
            self.assertNotEqual(first['root'], second['root'])
            self.assertTrue(self.separate(Path(first['root']), Path(second['root'])))
            self.assertEqual(subject.action.call_count, 2)
            self.assertEqual(client.deadline, deadline)
            self.assertEqual(set(scope.iterdir()), {Path(first['root']), Path(second['root'])})

    def test_legacy_format_one_keeps_its_original_request_and_delegation(self):
        with self.fixture(current=False, stopped=False) as (subject, scope, client, parse):
            with patch.object(snapshots, 'provision', side_effect=AssertionError('legacy owner changed')) as create:
                file, _ = subject.snapshot('old.snapshot', 'old-operation')
            self.assertEqual(file, {'root': str(scope), 'name': 'old.snapshot'})
            subject.action.assert_called_once_with({'action': 'snapshot', 'operationId': 'old-operation', 'file': file})
            parse.assert_called_once_with(subject.action.return_value, 'old-operation')
            create.assert_not_called()
            client.evidence.record.assert_not_called()
            self.assertEqual(list(scope.iterdir()), [])

    def test_same_current_operation_is_not_reused_or_sent_again(self):
        with self.fixture() as (subject, scope, _, _):
            file, _ = subject.snapshot('one.snapshot', 'same-operation')
            with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                subject.snapshot('two.snapshot', 'same-operation')
            subject.action.assert_called_once()
            self.assertEqual(list(Path(file['root']).iterdir()), [])

    def test_failed_native_handoff_retains_created_root_without_retry_or_snapshot_claim(self):
        with self.fixture() as (subject, scope, _, parse):
            failure = RuntimeError('controlled unknown native outcome')
            subject.action.side_effect = failure
            with self.assertRaises(RuntimeError) as observed:
                subject.snapshot('one.snapshot', 'operation')
            self.assertIs(observed.exception, failure)
            root = scope / 'snapshot-operation'
            self.assertTrue(root.is_dir())
            self.assertEqual(list(root.iterdir()), [])
            with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                subject.snapshot('one.snapshot', 'operation')
            subject.action.assert_called_once()
            parse.assert_not_called()

    def test_missing_original_stopped_owner_refuses_before_creation_or_action(self):
        with self.fixture(stopped=False) as (subject, scope, _, _):
            with self.assertRaisesRegex(ValueError, 'positive-original-node-retirement-required'):
                subject.snapshot('one.snapshot', 'operation')
            self.assertEqual(list(scope.iterdir()), [])
            subject.action.assert_not_called()

    def test_original_cutoff_or_cancellation_refuses_before_creation_or_action(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled), self.fixture() as (subject, scope, client, _):
                if cancelled:
                    client.cancellation.check.side_effect = KeyboardInterrupt
                else:
                    client.deadline = time.monotonic() - 1
                deadline = client.deadline
                with self.assertRaises(KeyboardInterrupt if cancelled else ValueError):
                    subject.snapshot('one.snapshot', 'operation')
                self.assertEqual(client.deadline, deadline)
                self.assertEqual(list(scope.iterdir()), [])
                subject.action.assert_not_called()

    def test_cutoff_after_validation_suppresses_creation_and_action_without_renewal(self):
        with self.fixture() as (subject, scope, client, _):
            deadline = client.deadline
            with patch.object(restore_roots.time, 'monotonic', side_effect=[deadline - 1, deadline]):
                with self.assertRaisesRegex(ValueError, 'restore-destination-root-deadline'):
                    subject.snapshot('one.snapshot', 'operation')
            self.assertEqual(client.deadline, deadline)
            self.assertEqual(list(scope.iterdir()), [])
            subject.action.assert_not_called()

    def test_cancellation_after_creation_retains_empty_root_and_suppresses_action(self):
        with self.fixture() as (subject, scope, client, _):
            client.cancellation.check.side_effect = [None, None, KeyboardInterrupt]
            with self.assertRaises(KeyboardInterrupt):
                subject.snapshot('one.snapshot', 'operation')
            self.assertEqual(list((scope / 'snapshot-operation').iterdir()), [])
            subject.action.assert_not_called()

    def test_existing_empty_or_nonempty_root_is_preserved_without_reuse(self):
        for populated in (False, True):
            with self.subTest(populated=populated), self.fixture() as (subject, scope, _, _):
                root = scope / 'snapshot-operation'
                root.mkdir(mode=0o700)
                if populated:
                    (root / 'retained').write_bytes(b'failed evidence')
                with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                    subject.snapshot('one.snapshot', 'operation')
                self.assertEqual([p.name for p in root.iterdir()], ['retained'] if populated else [])
                subject.action.assert_not_called()

    def test_existing_file_is_preserved_and_refused(self):
        with self.fixture() as (subject, scope, _, _):
            root = scope / 'snapshot-operation'
            root.write_bytes(b'original interrupted evidence')
            with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                subject.snapshot('one.snapshot', 'operation')
            self.assertEqual(root.read_bytes(), b'original interrupted evidence')
            subject.action.assert_not_called()

    def test_path_or_noncanonical_operation_ids_refuse_before_creation(self):
        with self.fixture() as (subject, scope, _, _):
            for operation in (None, True, [], '', 'x' * 129, '../other', 'a/b', 'a\\b', 'é', 'a\n'):
                with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'operation-identity'):
                    subject.snapshot('one.snapshot', operation)
            self.assertEqual(list(scope.iterdir()), [])
            subject.action.assert_not_called()

    def test_canonical_operation_boundary_does_not_truncate_original_identity(self):
        with self.fixture() as (subject, scope, client, _):
            operation = 'x' * 128
            file, _ = subject.snapshot('one.snapshot', operation)
            self.assertEqual(Path(file['root']).name, 'snapshot-' + operation)
            self.assertEqual(subject.action.call_args.args[0]['operationId'], operation)
            observed = client.evidence.record.call_args.args[1]
            self.assertEqual(observed['operationId'], operation)
            self.assertEqual(observed['durableFilesCreated'], 0)
            self.assertFalse(observed['currentAuthorityInferred'])
            self.assertEqual(observed['posixModeObserved'], os.name == 'posix')

    def test_manual_identity_fixture_releases_provision_mock_after_its_error(self):
        original = restore_roots.provision
        fixture = identity_controls.RestoreTargetIdentity()
        with tempfile.TemporaryDirectory() as temporary:
            runner, _, snapshot, _ = fixture.runner(Path(temporary).resolve(), pending=True)
            self.assertIs(restore_roots.provision, original)
            with patch.object(restore_installation, 'catalogs', side_effect=fixture.copied_catalogs):
                with self.assertRaises(identity_controls.SelectedConfiguration):
                    fixture.invoke(runner, snapshot, pending=True)
            self.assertIs(restore_roots.provision, original)
        with self.fixture() as (subject, scope, client, _):
            data = scope / 'data'
            data.mkdir(mode=0o700)
            state, checkpoint = data / 'state', scope / 'checkpoint'
            observed = original(client, subject.node, scope, state, checkpoint)
            self.assertEqual(observed['directoriesCreated'], 2)
            self.assertTrue(state.is_dir())
            self.assertTrue(checkpoint.is_dir())

    def test_missing_scope_is_not_created_or_widened_to_its_parent(self):
        with self.fixture() as (subject, scope, _, _):
            subject.directory = scope / 'absent'
            with self.assertRaises((FileNotFoundError, ValueError)):
                subject.snapshot('one.snapshot', 'operation')
            self.assertFalse(subject.directory.exists())
            subject.action.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'POSIX private directory mode requires a POSIX host')
    def test_actual_nonprivate_scope_refuses_without_chmod_or_creation(self):
        with self.fixture() as (subject, scope, _, _):
            scope.chmod(0o755)
            with self.assertRaisesRegex(ValueError, 'private-restore'):
                subject.snapshot('one.snapshot', 'operation')
            self.assertEqual(stat.S_IMODE(scope.stat().st_mode), 0o755)
            self.assertEqual(list(scope.iterdir()), [])
            subject.action.assert_not_called()

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'owned UID requires a POSIX host')
    def test_actual_foreign_uid_refuses_without_creation(self):
        with self.fixture() as (subject, scope, _, _):
            with patch.object(os, 'geteuid', return_value=os.geteuid() + 1):
                with self.assertRaisesRegex(ValueError, 'owned-restore'):
                    subject.snapshot('one.snapshot', 'operation')
            self.assertEqual(list(scope.iterdir()), [])
            subject.action.assert_not_called()

    def symlink(self, alias, target):
        try:
            alias.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest('host does not permit a file-system symlink')

    def test_dangling_and_existing_root_symlink_cannot_redirect_creation(self):
        with self.fixture() as (subject, scope, _, _):
            root, target = scope / 'snapshot-operation', scope / 'target'
            self.symlink(root, target)
            for exists in (False, True):
                with self.subTest(exists=exists):
                    if exists:
                        target.mkdir(mode=0o700)
                    with self.assertRaisesRegex(ValueError, 'fresh-scoped'):
                        subject.snapshot('one.snapshot', 'operation')
                    self.assertTrue(root.is_symlink())
                    self.assertEqual(target.exists(), exists)
            subject.action.assert_not_called()

    def test_symlinked_scope_cannot_redirect_creation(self):
        with self.fixture() as (subject, scope, _, _):
            alias = scope.with_name('alias')
            self.symlink(alias, scope)
            subject.directory = alias
            with self.assertRaisesRegex(ValueError, 'canonical-restore'):
                subject.snapshot('one.snapshot', 'operation')
            self.assertEqual(list(scope.iterdir()), [])
            subject.action.assert_not_called()

    def test_creation_error_preserves_original_error_and_suppresses_action(self):
        with self.fixture() as (subject, scope, _, _):
            failure = PermissionError('controlled creation refusal')
            with patch.object(Path, 'mkdir', side_effect=failure):
                with self.assertRaises(PermissionError) as observed:
                    subject.snapshot('one.snapshot', 'operation')
            self.assertIs(observed.exception, failure)
            self.assertEqual(list(scope.iterdir()), [])
            subject.action.assert_not_called()

    def test_real_scope_replacement_before_creation_refuses_without_action(self):
        with self.fixture() as (subject, scope, client, _):
            def replace():
                scope.rename(scope.with_name('retained-old-scope'))
                scope.mkdir(mode=0o700)
            calls = [0]
            def boundary():
                calls[0] += 1
                if calls[0] == 2:
                    replace()
            client.cancellation.check.side_effect = boundary
            with self.assertRaisesRegex(ValueError, 'scope-changed'):
                subject.snapshot('one.snapshot', 'operation')
            self.assertEqual(list(scope.iterdir()), [])
            subject.action.assert_not_called()

    def test_real_created_root_replacement_refuses_and_retains_both_directories(self):
        with self.fixture() as (subject, scope, client, _):
            root = scope / 'snapshot-operation'
            calls = [0]
            def replace():
                calls[0] += 1
                if calls[0] == 3:
                    root.rename(scope / 'retained-created-root')
                    root.mkdir(mode=0o700)
            client.cancellation.check.side_effect = replace
            with self.assertRaisesRegex(ValueError, 'custody-changed'):
                subject.snapshot('one.snapshot', 'operation')
            self.assertTrue(root.is_dir())
            self.assertTrue((scope / 'retained-created-root').is_dir())
            subject.action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
