from io import BytesIO
import stat
from unittest import TestCase
from unittest.mock import patch
import zipfile

from tools import replay_typescript_refusal_inputs as replay
from tools.phase2_operator_process import WorkflowError


class FixedRefusalToolInputs(TestCase):
    def test_scope_is_only_original_two_build_tools_not_host_companions_or_signer(self):
        self.assertEqual(set(replay.TOOLS), {'examples/capsule_contracts', 'examples/package'})
        self.assertEqual(replay.ARTIFACT, 12208056916)
        self.assertEqual(replay.RUN, 39290090984)
        self.assertEqual(replay.JOB, 118188191208)
        self.assertEqual(sum(row['bytes'] for row in replay.TOOLS.values()), 24950912)

    def test_member_extracts_only_exact_unique_regular_bounded_name(self):
        raw = BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('expected.json', b'{}')
            archive.writestr('../unselected', b'not read')
        with zipfile.ZipFile(raw) as archive:
            self.assertEqual(replay.member(archive, 'expected.json', 16), b'{}')
            with self.assertRaisesRegex(WorkflowError, 'exact-member'):
                replay.member(archive, 'absent.json', 16)
            with self.assertRaisesRegex(WorkflowError, 'type-or-bound'):
                replay.member(archive, 'expected.json', 1)

    def test_symlink_member_and_duplicate_fixed_name_are_refused(self):
        raw = BytesIO()
        entry = zipfile.ZipInfo('expected')
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr(entry, b'elsewhere')
        with zipfile.ZipFile(raw) as archive, self.assertRaisesRegex(WorkflowError, 'type-or-bound'):
            replay.member(archive, 'expected', 32)
        raw = BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('expected', b'a')
            with self.assertWarns(UserWarning):
                archive.writestr('expected', b'b')
        with zipfile.ZipFile(raw) as archive, self.assertRaisesRegex(WorkflowError, 'exact-member'):
            replay.member(archive, 'expected', 32)

    def test_original_receipt_substitution_refuses_before_interpretation(self):
        with self.assertRaisesRegex(WorkflowError, 'receipt-digest'):
            replay.checked_receipt(b'{"status":"passed","binaries":{}}')

    def test_range_seek_single_read_and_total_bound_refuse_without_network(self):
        with patch.object(replay.urllib.request, 'urlopen', side_effect=AssertionError('network must not run')):
            with self.assertRaisesRegex(WorkflowError, 'fixed-range-source'):
                replay.Ranges('http://untrusted.invalid', 1)
            remote = replay.Ranges('https://example.invalid/fixed', replay.SIZE)
            with self.assertRaisesRegex(WorkflowError, 'range-bound'):
                remote.read(8 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(WorkflowError, 'seek-bound'):
                remote.seek(-1)
            remote.transferred = 2 * remote.size
            with self.assertRaisesRegex(WorkflowError, 'total-range-bound'):
                remote.read(1)

    def test_network_exception_message_cannot_publish_signed_download_url(self):
        remote = replay.Ranges('https://example.invalid/?private-signature=not-public', 10)
        with patch.object(replay.urllib.request, 'urlopen', side_effect=OSError('private-signature=not-public')), \
             self.assertRaisesRegex(ValueError, '^refusal-replay-range-unavailable$') as raised:
            remote.read(1)
        self.assertNotIn('private-signature', str(raised.exception))
