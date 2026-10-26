"""Pure controls only: no kernel archive, compiler, SDK or process execution."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_host_stream_kernel_stream_objects as owner


class StreamObjectOwner(unittest.TestCase):
    def test_original_deadline_rejects_invalid_and_expired_start_before_work(self):
        for value in (None, True, 1, float('nan'), float('inf'), -1.0, 101.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                owner.deadline(value, now=100.0)
        with self.assertRaises(ValueError):
            owner.deadline(0.0, now=1315.0)
        self.assertEqual(owner.deadline(10.0, now=20.0), 1330.0)

    def test_public_gate_rejects_private_members_and_reserves_admission_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); output=root/'public';output.mkdir()
            private=root/'private';private.mkdir();(private/'key').write_bytes(b'not-public')
            receipt=b'{"status":"failed","stage":"eighteen-objects"}\n'
            (output/'receipt.json').write_bytes(receipt)
            record=owner.admit(output)
            self.assertEqual(set(record['files']), {'receipt.json'})
            self.assertEqual((output/'receipt.json').read_bytes(),receipt)
            self.assertEqual((private/'key').read_bytes(),b'not-public')
            (output/'private-key').write_bytes(b'never-upload')
            with self.assertRaises(ValueError):owner.admit(output)
            (output/'private-key').unlink()
            with patch.object(owner,'MAX_PUBLIC',owner.MAX_DOCUMENT+len(receipt)-1):
                with self.assertRaises(ValueError):owner.admit(output)
            with patch.object(owner,'MAX_PUBLIC',owner.MAX_DOCUMENT+len(receipt)):
                self.assertLessEqual(owner.admit(output)['payloadBytes']+len((output/'ADMISSION.json').read_bytes()),owner.MAX_PUBLIC)

    def test_object_gate_accepts_relocatable_without_claiming_link_and_refuses_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'one.o'; raw=bytearray(128)
            raw[:7]=b'\x7fELF\x02\x01\x01'
            struct.pack_into('<HHI',raw,16,1,62,1)
            struct.pack_into('<Q',raw,40,64)
            struct.pack_into('<HH',raw,58,64,1)
            path.write_bytes(raw)
            self.assertEqual(owner.object_identity(path),owner.identity(bytes(raw)))
            struct.pack_into('<H',raw,16,2);path.write_bytes(raw)
            with self.assertRaises(ValueError):owner.object_identity(path)


if __name__=='__main__':unittest.main()
