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

    def test_classdir_source_freeze_is_exact_and_preserves_default_source_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in owner.CLASSDIR_SOURCE_PATHS:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                raw=(owner.ROOT/name).read_bytes()
                if name=='tools/host_stream_kernel_stream_classdir.py':
                    # TEST-ONLY exact historical positive fixture. The extended
                    # current helper is bound in full ONLY by the new52 mode;
                    # production old50 still refuses its changed whole bytes.
                    raw=raw[:10630]
                    self.assertEqual(owner.identity(raw),{'bytes':10630,
                        'sha256':'d0f71e8566f9e8db028855737857a9671ae6e3412df9e745817b06378f24878f'})
                target.write_bytes(raw)
            normal=owner.selected_sources(root)
            current=owner.selected_sources(root,classdir=True)
            self.assertEqual(len(normal),47)
            self.assertEqual(len(current),50)
            self.assertTrue(all(current[name]==value for name,value in normal.items()))
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir=1)
            path=root/'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-classdir.c'
            path.write_bytes(path.read_bytes()+b'\n')
            self.assertEqual(owner.selected_sources(root),normal)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir=True)

    def test_classdir_public_gate_refuses_other_original_object_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            (output/'receipt.json').write_bytes(b'{"status":"failed","stage":"classdir-objects"}\n')
            record=owner.admit(output,classdir=True)
            self.assertEqual(set(record['files']),{'receipt.json'})
            self.assertEqual(set(owner.CLASSDIR_TARGETS),
                {'net/factory.o','drivers/base/core.o','lib/kobject.o','net/core/net-sysfs.o'})
            self.assertIsNotNone(owner.public_allowed('objects/net/socket.o'))
            self.assertIsNone(owner.public_allowed('objects/net/socket.o',classdir=True))
            forbidden=output/'objects/net/socket.o';forbidden.parent.mkdir(parents=True)
            forbidden.write_bytes(b'rejected before publication')
            with self.assertRaises(ValueError):owner.admit(output,classdir=True)

    def test_classdir_kernfs_freeze_binds_full_projector_and_keeps_historical_modes_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in owner.REGISTRATION_SOURCE_PATHS:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((owner.ROOT/name).read_bytes())
            current=owner.selected_sources(root,classdir_kernfs=True)
            normal=owner.selected_sources(root)
            self.assertEqual(len(current),52)
            self.assertEqual(len(normal),47)
            self.assertTrue(all(current[name]==value for name,value in normal.items()))
            helper='tools/host_stream_kernel_stream_classdir.py'
            self.assertEqual(current[helper],owner.identity((owner.ROOT/helper).read_bytes()))
            self.assertGreater(current[helper]['bytes'],10630)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir=True)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir_kernfs=1)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir=True,classdir_kernfs=True)
            path=root/'research/standard-outbound/linux-6.12-lineage/factory-stream-classdir-registration.c'
            path.write_bytes(path.read_bytes()+b'\n')
            self.assertEqual(owner.selected_sources(root),normal)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir_kernfs=True)

    def test_classdir_kernfs_public_gate_keeps_exact_nine_targets_and_current_only_channels(self):
        expected={'net/factory.o','drivers/base/core.o','lib/kobject.o','fs/sysfs/dir.o',
            'fs/kernfs/dir.o','lib/idr.o','lib/radix-tree.o','security/security.o','security/selinux/hooks.o'}
        self.assertEqual(set(owner.mode_targets(classdir_kernfs=True)),expected)
        self.assertEqual(len(owner.mode_targets()),18)
        self.assertEqual(len(owner.mode_targets(classdir=True)),4)
        self.assertIsNotNone(owner.public_allowed('logs/00-baseline-fetch.stdout.txt',classdir_kernfs=True))
        self.assertIsNone(owner.public_allowed('logs/00-baseline-fetch.stdout.txt'))
        self.assertIsNone(owner.public_allowed('logs/00-baseline-fetch.stdout.txt',classdir=True))
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            (output/'receipt.json').write_bytes(b'{"status":"failed","stage":"classdir-kernfs-objects"}\n')
            self.assertEqual(set(owner.admit(output,classdir_kernfs=True)['files']),{'receipt.json'})
            for name in ('net/socket.o','net/core/net-sysfs.o'):
                self.assertIsNone(owner.public_allowed('objects/'+name,classdir_kernfs=True))
            forbidden=output/'objects/net/core/net-sysfs.o';forbidden.parent.mkdir(parents=True)
            forbidden.write_bytes(b'unchanged TU is outside this programme')
            with self.assertRaises(ValueError):owner.admit(output,classdir_kernfs=True)


if __name__=='__main__':unittest.main()
