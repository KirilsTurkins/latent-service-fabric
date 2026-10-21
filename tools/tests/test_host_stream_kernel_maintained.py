"""Read-only maintained-source authentication and hostile archive boundaries."""
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import host_stream_kernel_maintained as kernel


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
        'gitBlob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def archive(rows):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as output:
        for name, raw, kind in rows:
            row = tarfile.TarInfo(name)
            row.type = kind
            row.size = len(raw) if kind == tarfile.REGTYPE else 0
            row.linkname = 'outside'
            output.addfile(row, io.BytesIO(raw) if kind == tarfile.REGTYPE else None)
    buffer.seek(0)
    return tarfile.open(fileobj=buffer, mode='r|')


class MaintainedKernelSource(unittest.TestCase):
    def test_frozen_primary_inputs_do_not_claim_kernel_configuration_or_installation(self):
        value = kernel.manifest()
        self.assertEqual(value['commit'], kernel.COMMIT)
        self.assertEqual(len(value['source']), 71)
        self.assertEqual(sum(row['bytes'] for row in value['source'].values()), 5117172)
        self.assertEqual(value['archive']['members'], 92471)
        for key in ('kernelBuilt', 'configurationResolved', 'completeAllocationClosure', 'productionInstallation'):
            self.assertIs(value[key], False)
        self.assertIs(value['localPgpVerificationPerformed'], False)
        self.assertTrue(value['allSelectedGitBlobIdentitiesIndependentlyMatched'])
        self.assertIn('security/selinux/hooks.c', value['source'])
        self.assertIn('arch/x86/configs/x86_64_defconfig', value['source'])
        with patch.object(kernel.paths, 'read', return_value=b'{}'), \
                self.assertRaisesRegex(ValueError, 'manifest-byte-identity'):
            kernel.manifest()

    def test_every_selected_byte_and_git_object_identity_is_required(self):
        raw = b'original maintained source\n';expected = {'net/socket.c': identity(raw)}
        self.assertEqual(kernel.authenticate_files({'net/socket.c': raw}, expected), len(raw))
        for selected in ({}, {'net/socket.c': raw, 'extra': raw}, {'net/socket.c': raw[:-1]},
                {'net/socket.c': b'X'+raw[1:]}, {'net/socket.c': bytearray(raw)}):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                kernel.authenticate_files(selected, expected)
        for field in ('sha256', 'gitBlob'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'byte-identity'):
                kernel.authenticate_files({'net/socket.c': raw}, {'net/socket.c': {**identity(raw), field: '0'*64}})

    def test_streaming_selection_never_extracts_unselected_members(self):
        rows = [('linux/net/socket.c', b'kept', tarfile.REGTYPE), ('linux/extra', b'ignored', tarfile.REGTYPE)]
        with archive(rows) as source:
            result = kernel.selected_members(source, {'net/socket.c': identity(b'kept')}, 'linux', 2, 11, lambda: None)
        self.assertEqual(result, {'net/socket.c': b'kept'})

    def test_traversal_foreign_prefix_backslash_duplicate_and_links_refuse(self):
        for name, kind in (('linux/../net/socket.c', tarfile.REGTYPE),
                ('other/net/socket.c', tarfile.REGTYPE), ('linux/net\\socket.c', tarfile.REGTYPE),
                ('linux/net/socket.c', tarfile.SYMTYPE), ('linux/net/socket.c', tarfile.LNKTYPE)):
            with self.subTest(name=name, kind=kind), archive([(name, b'kept', kind)]) as source, self.assertRaises(ValueError):
                kernel.selected_members(source, {'net/socket.c': identity(b'kept')}, 'linux', 1, 4, lambda: None)
        row = ('linux/net/socket.c', b'kept', tarfile.REGTYPE)
        with archive([row, row]) as source, self.assertRaisesRegex(ValueError, 'membership'):
            kernel.selected_members(source, {'net/socket.c': identity(b'kept')}, 'linux', 2, 8, lambda: None)

    def test_omitted_or_extra_archive_members_expansion_and_content_drift_refuse(self):
        row = ('linux/net/socket.c', b'kept', tarfile.REGTYPE)
        for count, expanded, expected in ((2, 4, identity(b'kept')), (0, 4, identity(b'kept')),
                (1, 3, identity(b'kept')), (1, 5, identity(b'kept')), (1, 4, identity(b'else'))):
            with self.subTest(count=count, expanded=expanded), archive([row]) as source, self.assertRaises(ValueError):
                kernel.selected_members(source, {'net/socket.c': expected}, 'linux', count, expanded, lambda: None)

    def test_archive_hash_and_original_deadline_gate_before_any_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()/'archive';path.write_bytes(b'not an authenticated archive')
            value = {'archive': {'bytes': path.stat().st_size, 'sha256': '0'*64}, 'source': {}}
            with self.assertRaisesRegex(ValueError, 'archive-byte-identity'):
                kernel.authenticate_archive(path, value)
            original = RuntimeError('source-read-cancelled')
            def stop(): raise original
            with archive([('linux/net/socket.c', b'kept', tarfile.REGTYPE)]) as source, \
                    self.assertRaises(RuntimeError) as caught:
                kernel.selected_members(source, {'net/socket.c': identity(b'kept')}, 'linux', 1, 4, stop)
            self.assertIs(caught.exception, original)

    def test_extra_files_are_bounded_data_from_same_archive_and_never_bypass_original_pins(self):
        expected = {'net/socket.c': identity(b'kept')}
        rows = [('linux/net/socket.c', b'kept', tarfile.REGTYPE), ('linux/security/extra.c', b'extra', tarfile.REGTYPE)]
        with archive(rows) as source:
            selected = kernel.selected_members(source, expected, 'linux', 2, 9, lambda: None, ('security/extra.c',))
        self.assertEqual(selected, {'net/socket.c': b'kept', 'security/extra.c': b'extra'})
        for extras in (('security/extra.c',)*2, ('../outside',), ('net/socket.c',), tuple('path'+str(i) for i in range(33))):
            with self.subTest(extras=extras), self.assertRaises(ValueError):
                kernel.extra_selection(extras, expected)
        with archive([('linux/net/socket.c', b'else', tarfile.REGTYPE), rows[1]]) as source, self.assertRaisesRegex(ValueError, 'byte-identity'):
            kernel.selected_members(source, expected, 'linux', 2, 9, lambda: None, ('security/extra.c',))
        with archive(rows[:1]) as source, self.assertRaisesRegex(ValueError, 'membership'):
            kernel.selected_members(source, expected, 'linux', 1, 4, lambda: None, ('security/extra.c',))


if __name__ == '__main__':
    unittest.main()
