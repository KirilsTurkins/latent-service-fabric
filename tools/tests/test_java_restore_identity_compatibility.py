"""Optional restore metadata retains current identity and physical-owner gates."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.java_transaction_qualification import offline_campaign, restore_installation as restore
from tools.tests import test_java_restore_target_identity as target_controls


class RestoreIdentityCompatibility(unittest.TestCase):
    def test_omitted_source_identity_keeps_optional_projection_and_input_unchanged(self):
        original = {'state': {'formatVersion': 2, 'checkpointRoot': '/original',
                              'createIfMissing': False, 'operations': []}}
        before = copy.deepcopy(original)
        self.assertIsNone(restore.requested_identity(original))
        self.assertEqual(original, before)

    def test_present_invalid_source_or_destination_alias_is_not_legacy_omission(self):
        for invalid in (None, '', 'x' * 129, 'foreign/path', 'é', True, {},
                        restore.RESTORED_STORE_IDENTITY):
            with self.subTest(invalid=invalid):
                original = {'state': {'formatVersion': 2, 'storeIdentity': invalid}}
                before = copy.deepcopy(original)
                with self.assertRaises(ValueError):
                    restore.requested_identity(original)
                self.assertEqual(original, before)

    def test_canonical_source_requires_distinct_target_without_mutating_settings(self):
        for source in ('original', 'A0._-z', 'x' * 128):
            with self.subTest(source=source):
                original = {'state': {'formatVersion': 2, 'storeIdentity': source,
                                      'native': {'unchanged': True}}}
                before = copy.deepcopy(original)
                self.assertEqual(restore.requested_identity(original), restore.RESTORED_STORE_IDENTITY)
                self.assertNotEqual(source, restore.RESTORED_STORE_IDENTITY)
                self.assertEqual(original, before)

    def test_both_collectors_keep_legacy_omission_without_selecting_a_new_identity(self):
        fixture = target_controls.RestoreTargetIdentity()
        for pending in (False, True):
            with self.subTest(pending=pending), tempfile.TemporaryDirectory() as temporary:
                runner, original, snapshot, requests = fixture.runner(Path(temporary).resolve(),
                    pending=pending, returned_identity='synthetic-source-control')
                del original['state']['storeIdentity']
                runner.configuration.write_text(json.dumps(original), encoding='utf-8')
                with patch.object(restore, 'catalogs', side_effect=fixture.copied_catalogs), \
                     patch.object(offline_campaign.http, 'aggregate', return_value={'count': '5'}):
                    with self.assertRaises(target_controls.SelectedConfiguration):
                        fixture.invoke(runner, snapshot, pending=pending)
                self.assertEqual(len(requests), 2)
                self.assertTrue(all('destinationStoreIdentity' not in row for row in requests))
                selected = json.loads(runner.configuration.read_text(encoding='utf-8'))
                self.assertNotIn('storeIdentity', selected['state'])
                self.assertEqual(selected['state']['native'], original['state']['native'])
                self.assertEqual(selected['providers'], original['providers'])

    def test_both_canonical_collectors_require_the_actual_matching_receipt(self):
        fixture = target_controls.RestoreTargetIdentity()
        for pending in (False, True):
            for identity in (restore.RESTORED_STORE_IDENTITY, 'foreign-target'):
                with self.subTest(pending=pending, identity=identity), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary).resolve()
                    runner, original, snapshot, requests = fixture.runner(root, pending=pending,
                                                                          returned_identity=identity)
                    with patch.object(restore, 'catalogs', side_effect=fixture.copied_catalogs), \
                         patch.object(offline_campaign.http, 'aggregate', return_value={'count': '5'}):
                        if identity == restore.RESTORED_STORE_IDENTITY:
                            with self.assertRaises(target_controls.SelectedConfiguration):
                                fixture.invoke(runner, snapshot, pending=pending)
                            fixture.assert_selection(runner, original, requests)
                        else:
                            with self.assertRaisesRegex(ValueError, 'restored-store-identity'):
                                fixture.invoke(runner, snapshot, pending=pending)
                            self.assertEqual(len(requests), 2)
                            self.assertFalse((root / ('pending-restored-node.json' if pending
                                                     else 'restored-node.json')).exists())
                            runner.refresh_authority.assert_not_called()

    def test_present_malformed_source_stops_both_collectors_before_copy_or_native_action(self):
        fixture = target_controls.RestoreTargetIdentity()
        for pending in (False, True):
            for invalid in (None, '', 'foreign/path', 'x' * 129, restore.RESTORED_STORE_IDENTITY):
                with self.subTest(pending=pending, invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                    runner, original, snapshot, requests = fixture.runner(Path(temporary).resolve(),
                                                                         pending=pending)
                    original['state']['storeIdentity'] = invalid
                    runner.configuration.write_text(json.dumps(original), encoding='utf-8')
                    with patch.object(restore, 'catalogs') as copied, \
                         patch.object(offline_campaign.http, 'aggregate', return_value={'count': '5'}):
                        with self.assertRaises(ValueError):
                            fixture.invoke(runner, snapshot, pending=pending)
                    self.assertEqual(requests, [])
                    copied.assert_not_called()
                    runner.refresh_authority.assert_not_called()


if __name__ == '__main__':
    unittest.main()
