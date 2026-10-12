"""Real filesystem custody controls, separate from native restore qualification."""
from pathlib import Path
from types import SimpleNamespace
import copy
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.java_transaction_qualification import restore_installation as restore
from tools.java_transaction_qualification.state_configuration import declaration


class RestoreInstallationCustody(unittest.TestCase):
    def client(self):
        return SimpleNamespace(deadline=time.monotonic() + 30,
                               cancellation=SimpleNamespace(check=lambda: None))

    def test_copied_catalog_hardlinks_are_independent_and_state_checkpoint_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'source'
            source.mkdir(mode=0o700)
            (source / 'releases').mkdir()
            blob = source / 'releases/blob'
            blob.write_bytes(b'actual signed catalog input')
            os.link(blob, source / 'releases/publication')
            (source / 'state').mkdir()
            (source / 'state/database').write_bytes(b'original business state')
            checkpoint = source / 'checkpoint'
            checkpoint.mkdir()
            (checkpoint / 'clock').write_bytes(b'original protected clock')
            destination = root / 'destination'
            with patch.object(restore, 'require_stopped_owner') as stopped:
                observed = restore.catalogs(self.client(), object(), source, destination, checkpoint)
                stopped.assert_called_once()
            self.assertEqual(observed['files'], 2)
            self.assertEqual(observed['distinctBytes'], len(blob.read_bytes()))
            first, second = destination / 'releases/blob', destination / 'releases/publication'
            self.assertEqual(first.read_bytes(), blob.read_bytes())
            self.assertEqual((first.stat().st_dev, first.stat().st_ino),
                             (second.stat().st_dev, second.stat().st_ino))
            self.assertNotEqual((first.stat().st_dev, first.stat().st_ino),
                                (blob.stat().st_dev, blob.stat().st_ino))
            self.assertEqual(first.stat().st_nlink, 2)
            self.assertFalse((destination / 'state').exists())
            self.assertFalse((destination / 'checkpoint').exists())
            self.assertEqual((source / 'state/database').read_bytes(), b'original business state')
            self.assertFalse(observed['currentAuthorityInferred'])

    def test_external_link_is_refused_before_creating_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'source'
            source.mkdir(mode=0o700)
            (source / 'catalog').write_bytes(b'linked outside source custody')
            os.link(source / 'catalog', root / 'outside')
            checkpoint = root / 'clock'
            checkpoint.mkdir()
            with patch.object(restore, 'require_stopped_owner'), self.assertRaisesRegex(ValueError, 'links-must-remain'):
                restore.catalogs(self.client(), object(), source, root / 'destination', checkpoint)
            self.assertFalse((root / 'destination').exists())

    def test_source_change_during_copy_refuses_and_retains_failed_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'source'
            source.mkdir(mode=0o700)
            original = source / 'catalog'
            original.write_bytes(b'before')
            checkpoint = root / 'clock'
            checkpoint.mkdir()
            real_sync = os.fsync
            def change(descriptor):
                real_sync(descriptor)
                original.write_bytes(b'changed original')
            with patch.object(restore, 'require_stopped_owner'), patch.object(restore.os, 'fsync', change):
                with self.assertRaisesRegex(ValueError, 'custody-changed'):
                    restore.catalogs(self.client(), object(), source, root / 'destination', checkpoint)
            self.assertEqual((root / 'destination/catalog').read_bytes(), b'before')
            self.assertEqual(original.read_bytes(), b'changed original')

    def test_v2_selection_changes_only_roots_and_creation_and_refuses_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            data = root / 'data'
            data.mkdir()
            (data / 'state').mkdir()
            checkpoint = root / 'checkpoint'
            checkpoint.mkdir()
            original = {'dataDirectory': '/original/data', 'credentials': [{'subject': 'original'}],
                        'providers': {'original': 'unchanged'}, 'state': declaration(root / 'original-clock')}
            before = copy.deepcopy(original)
            selected = restore.selection(original, data, checkpoint)
            self.assertEqual(original, before)
            self.assertEqual(selected['dataDirectory'], str(data))
            expected = dict(original['state'], checkpointRoot=str(checkpoint), createIfMissing=False)
            self.assertEqual(selected['state'], expected)
            self.assertEqual(selected['providers'], original['providers'])
            self.assertEqual(selected['credentials'], original['credentials'])
            self.assertNotIn('stateRoot', selected['state'])
            for invalid in (data / 'state', data):
                with self.assertRaisesRegex(ValueError, 'independently-protected'):
                    restore.selection(original, data, invalid)
            with self.assertRaisesRegex(ValueError, 'explicit-current-v2'):
                restore.selection(dict(original, state={'formatVersion': 1}), data, checkpoint)


if __name__ == '__main__':
    unittest.main()
