"""Mocked native handoffs; these controls do not qualify a restore or guest run."""
from pathlib import Path
from types import SimpleNamespace
import copy
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import offline_campaign, pending_campaign
from tools.java_transaction_qualification import restore_destination_roots
from tools.java_transaction_qualification import restore_installation as restore
from tools.java_transaction_qualification.state_configuration import declaration


TARGET = 'java-transaction-restored-qualification'


class SelectedConfiguration(Exception):
    """Stop at the real configuration handoff, before any native admission."""


class RestoreTargetIdentity(unittest.TestCase):
    def runner(self, root, *, pending, returned_identity=TARGET):
        source = root / 'source'
        source.mkdir()
        settings = {'dataDirectory': str(source), 'providers': {'original': 'retained'},
                    'credentials': [{'subject': 'synthetic-original'}],
                    'state': declaration(root / 'source-checkpoint')}
        path = root / 'node.json'
        path.write_text(json.dumps(settings), encoding='utf-8')
        cls = pending_campaign.PendingCampaign if pending else offline_campaign.OfflineCampaign
        runner = cls.__new__(cls)
        runner.configuration, runner.directory = path, root / 'offline'
        runner.directory.mkdir()
        runner.current_v2 = True
        runner.publication = 'publication:sha256:' + 'a' * 64
        runner.node = object()
        runner.client = SimpleNamespace(evidence=SimpleNamespace(record=Mock()))
        runner.campaign = SimpleNamespace(full_path=path,
            query=Mock(return_value=({}, {'key-version': {'none': None}})),
            result=Mock(return_value={'disposition': 'committed'}), socket=Mock(), wait_effect=Mock())
        runner.quiesce = Mock()
        runner.observation = Mock(return_value={'posts': 1})
        runner.recipient = Mock(return_value={'posts': 1})
        runner.refresh_authority = Mock(side_effect=SelectedConfiguration)
        snapshot = {'snapshotDigest': 'sha256:' + 'b' * 64, 'manifestDigest': 'sha256:' + 'c' * 64}
        window = dict(snapshot=snapshot, windowDigest='sha256:' + 'd' * 64)
        restored = dict(snapshot, destinationIdentity=returned_identity)
        requests = []

        def action(request):
            requests.append(copy.deepcopy(request))
            if request['action'] == 'inspect-restore':
                return window
            self.assertEqual(request['action'], 'restore')
            self.assertEqual(request['windowAcknowledgement'], window['windowDigest'])
            Path(request['destinationRoot']).mkdir()
            Path(request['destinationCheckpointRoot']).mkdir()
            return restored

        runner.action = action
        return runner, settings, snapshot, requests

    def copied_catalogs(self, client, node, source, destination, checkpoint):
        destination.mkdir()
        return {'sourceStateCopied': False, 'currentAuthorityInferred': False}

    def invoke(self, runner, snapshot, *, pending):
        file = {'root': '/synthetic-original-snapshot', 'name': 'snapshot'}
        # Manual TestCase users also retire this identity-only mock on failure.
        with patch.object(restore_destination_roots, 'provision'):
            if pending:
                return runner.restored(file, snapshot, {}, {'posts': 1})
            return runner.restore(4, file, snapshot, {})

    def assert_selection(self, runner, original, requests):
        self.assertEqual(len(requests), 2)
        self.assertEqual([row.get('destinationStoreIdentity') for row in requests], [TARGET, TARGET])
        self.assertNotEqual(TARGET, original['state']['storeIdentity'])
        self.assertEqual({key: value for key, value in requests[0].items() if key != 'action'},
                         {key: value for key, value in requests[1].items()
                          if key not in {'action', 'windowAcknowledgement'}})
        selected = json.loads(runner.configuration.read_text(encoding='utf-8'))
        self.assertEqual(selected['state']['storeIdentity'], TARGET)
        self.assertEqual(selected['state']['native'], original['state']['native'])
        self.assertEqual(selected['providers'], original['providers'])
        self.assertEqual(selected['credentials'], original['credentials'])
        self.assertFalse(selected['state']['createIfMissing'])
        runner.refresh_authority.assert_called_once_with(selected)

    def test_pending_uses_one_explicit_target_then_actual_receipt_identity_for_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner, original, snapshot, requests = self.runner(Path(temporary).resolve(), pending=True)
            with patch.object(restore, 'catalogs', side_effect=self.copied_catalogs):
                with self.assertRaises(SelectedConfiguration):
                    self.invoke(runner, snapshot, pending=True)
            self.assert_selection(runner, original, requests)

    def test_terminal_uses_one_explicit_target_then_actual_receipt_identity_for_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner, original, snapshot, requests = self.runner(Path(temporary).resolve(), pending=False)
            with patch.object(restore, 'catalogs', side_effect=self.copied_catalogs), \
                 patch.object(offline_campaign.http, 'aggregate', return_value={'count': '5'}):
                with self.assertRaises(SelectedConfiguration):
                    self.invoke(runner, snapshot, pending=False)
            self.assert_selection(runner, original, requests)

    def test_pending_foreign_receipt_stops_before_configuration_or_authority_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            runner, original, snapshot, requests = self.runner(root, pending=True,
                                                             returned_identity='foreign-target')
            with patch.object(restore, 'catalogs', side_effect=self.copied_catalogs):
                with self.assertRaisesRegex(ValueError, 'restored-store-identity'):
                    self.invoke(runner, snapshot, pending=True)
            self.assertEqual(len(requests), 2)
            self.assertFalse((root / 'pending-restored-node.json').exists())
            self.assertEqual(json.loads((root / 'node.json').read_text(encoding='utf-8')), original)
            runner.refresh_authority.assert_not_called()

    def test_terminal_foreign_receipt_stops_before_configuration_or_authority_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            runner, original, snapshot, requests = self.runner(root, pending=False,
                                                             returned_identity='foreign-target')
            with patch.object(restore, 'catalogs', side_effect=self.copied_catalogs), \
                 patch.object(offline_campaign.http, 'aggregate', return_value={'count': '5'}):
                with self.assertRaisesRegex(ValueError, 'restored-store-identity'):
                    self.invoke(runner, snapshot, pending=False)
            self.assertEqual(len(requests), 2)
            self.assertFalse((root / 'restored-node.json').exists())
            self.assertEqual(json.loads((root / 'node.json').read_text(encoding='utf-8')), original)
            runner.refresh_authority.assert_not_called()

    def test_selection_changes_only_roots_creation_and_actual_target_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            data, checkpoint = root / 'data', root / 'checkpoint'
            data.mkdir()
            (data / 'state').mkdir()
            checkpoint.mkdir()
            original = {'dataDirectory': '/original', 'state': declaration(root / 'old-checkpoint'),
                        'credentials': [{'subject': 'synthetic-original'}], 'providers': {'kept': True}}
            before = copy.deepcopy(original)
            selected = restore.selection(original, data, checkpoint, identity=TARGET)
            expected = copy.deepcopy(original)
            expected['dataDirectory'] = str(data)
            expected['state'].update(checkpointRoot=str(checkpoint), createIfMissing=False,
                                     storeIdentity=TARGET)
            self.assertEqual(selected, expected)
            self.assertEqual(original, before)

    def test_omitted_selection_identity_retains_original_identity_and_all_old_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            data, checkpoint = root / 'data', root / 'checkpoint'
            data.mkdir()
            (data / 'state').mkdir()
            checkpoint.mkdir()
            original = {'dataDirectory': '/original', 'state': declaration(root / 'old-checkpoint')}
            selected = restore.selection(original, data, checkpoint)
            self.assertEqual(selected['state'], dict(original['state'], checkpointRoot=str(checkpoint),
                                                     createIfMissing=False))

    def test_store_identity_retains_original_ascii_grammar_and_128_byte_boundary(self):
        for value in ('a', 'A0._-z', 'x' * 128, TARGET):
            with self.subTest(value=value):
                self.assertEqual(restore.store_identity(value), value)
        for value in ('', 'x' * 129, 'foreign/path', '..\x00', 'é', ' whitespace', True, 1, {}, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'canonical-restore-store-identity'):
                restore.store_identity(value)

    def test_invalid_receipt_identity_cannot_mutate_original_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            data, checkpoint = root / 'data', root / 'checkpoint'
            data.mkdir()
            (data / 'state').mkdir()
            checkpoint.mkdir()
            original = {'dataDirectory': '/original', 'state': declaration(root / 'old-checkpoint')}
            before = copy.deepcopy(original)
            for invalid in ('x' * 129, '/foreign', '', '\n', True):
                with self.subTest(value=invalid), self.assertRaises(ValueError):
                    restore.selection(original, data, checkpoint, identity=invalid)
                self.assertEqual(original, before)


if __name__ == '__main__':
    unittest.main()
