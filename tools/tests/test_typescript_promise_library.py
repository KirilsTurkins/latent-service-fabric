"""Finite acquisition/archive controls; none substitutes for a library build."""
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.typescript_guest import promise_library as owner


class Response(io.BytesIO):
    def geturl(self):
        return 'https://fixture.invalid/pinned-source'


class PromiseLibraryInputs(unittest.TestCase):
    def test_streamed_source_requires_exact_length_and_digest_before_use(self):
        for actual in (b'original', b'change!!', b'short', b'original-extra'):
            with self.subTest(actual=actual), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'source.archive'
                pin = {'url': 'https://fixture.invalid/source', 'bytes': 8,
                       'sha256': hashlib.sha256(b'original').hexdigest()}
                with patch.object(owner.urllib.request, 'urlopen', return_value=Response(actual)):
                    if actual == b'original':
                        result = owner.acquire(path, pin, time.monotonic()+10)
                        self.assertEqual(result, {key: pin[key] for key in ('bytes', 'sha256')})
                        self.assertEqual(path.read_bytes(), actual)
                    else:
                        with self.assertRaisesRegex(ValueError, 'upstream-pin-differs|acquisition-bound'):
                            owner.acquire(path, pin, time.monotonic()+10)
                        self.assertTrue(path.exists())

    def test_acquisition_expired_deadline_precedes_network_or_output(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(owner.urllib.request, 'urlopen') as network:
            target = Path(directory)/'source.archive'
            with self.assertRaisesRegex(ValueError, 'acquisition-deadline'):
                owner.acquire(target, {}, time.monotonic()-1)
            network.assert_not_called()
            self.assertFalse(target.exists())

    @staticmethod
    def carrier(path, names):
        with tarfile.open(path, 'w') as archive:
            root = tarfile.TarInfo('source'); root.type = tarfile.DIRTYPE; archive.addfile(root)
            for name, kind in names:
                member = tarfile.TarInfo(name)
                if kind == 'link':
                    member.type = tarfile.SYMTYPE; member.linkname = '../../outside'
                    archive.addfile(member)
                elif kind == 'device':
                    member.type = tarfile.CHRTYPE; archive.addfile(member)
                else:
                    member.size = 4; archive.addfile(member, io.BytesIO(b'data'))

    def test_normal_regular_carrier_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root/'source.tar'
            self.carrier(archive, [('source/file', 'file')])
            before = archive.read_bytes()
            selected = owner.extract(archive, root/'out', 'source', deadline=time.monotonic()+10)
            self.assertEqual((selected/'file').read_bytes(), b'data')
            self.assertEqual(archive.read_bytes(), before)

    def test_all_members_are_validated_before_any_regular_source_is_extracted(self):
        defects = [('source/../escape', 'file'), ('/absolute', 'file'), ('wrong/file', 'file'),
                   ('source\\file', 'file'), ('source/file', 'file'), ('source/./alias', 'file'),
                   ('source/link', 'link'), ('source/device', 'device')]
        for defect in defects:
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); archive = root/'source.tar'
                self.carrier(archive, [('source/file', 'file'), defect])
                with self.assertRaises((ValueError, tarfile.FilterError)):
                    owner.extract(archive, root/'out', 'source', deadline=time.monotonic()+10)
                self.assertEqual(list((root/'out').iterdir()), [])
                self.assertFalse((root/'outside').exists())

    def test_extracted_byte_member_count_and_original_deadline_bounds_fail_closed(self):
        for limit, value in (('MAX_EXTRACTED', 3), ('MAX_MEMBERS', 1), ('deadline', 0)):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); archive = root/'source.tar'
                self.carrier(archive, [('source/file', 'file')])
                if limit == 'deadline':
                    with self.assertRaisesRegex(ValueError, 'archive-member'):
                        owner.extract(archive, root/'out', 'source', deadline=time.monotonic()-1)
                else:
                    with patch.object(owner, limit, value), self.assertRaisesRegex(ValueError, 'archive-bound'):
                        owner.extract(archive, root/'out', 'source', deadline=time.monotonic()+10)
                self.assertEqual(list((root/'out').iterdir()), [])
