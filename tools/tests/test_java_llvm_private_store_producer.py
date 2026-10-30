"""R8 source/control checks only: no LLVM, JVM, compiler or guest invocation."""
from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from tools.java_guest import llvm_ssa_patch as old_patch, llvm_ssa_results as old_results
from tools.java_guest import llvm_ssa_producer as old_producer
from tools.java_guest import llvm_private_store_patch as patch
from tools.java_guest import llvm_private_store_results as results
from tools.java_guest import llvm_private_store_producer as producer
from tools.java_guest import llvm_private_store_distribution as carrier


class PrivateScalarProducer(unittest.TestCase):
    def test_exact_seven_member_patch_refuses_all_preimages_before_any_write(self):
        value = patch.manifest()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            before = {name: row['original'].encode() for name, row in old_patch.manifest()['files'].items()}
            before[patch.TARGET] = value['target']['original'].encode()
            for name, raw in before.items():
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            for name in patch.TESTS:
                (source / name).parent.mkdir(parents=True, exist_ok=True)
            wrong = source / patch.TARGET
            wrong.write_bytes(before[patch.TARGET] + b'\n')
            with self.assertRaisesRegex(ValueError, 'source-identity'):
                patch.apply(source)
            self.assertEqual({name: (source / name).read_bytes() for name in old_patch.PATHS},
                             {name: before[name] for name in old_patch.PATHS})
            wrong.write_bytes(before[patch.TARGET])
            (source / patch.TESTS[1]).write_bytes(b'preexisting file')
            with self.assertRaisesRegex(ValueError, 'not-absent'):
                patch.apply(source)
            self.assertEqual(wrong.read_bytes(), before[patch.TARGET])
            (source / patch.TESTS[1]).unlink()
            record = patch.apply(source)
            self.assertEqual(record['after'], patch.identities('modified'))
            self.assertEqual(record['before'], patch.identities('original'))
            self.assertEqual(record['basePatchSha256'], old_patch.PATCH_SHA256)
            self.assertEqual(old_patch.check(source, 'modified'), old_patch.identities('modified'))
            self.assertEqual(wrong.read_bytes(), value['target']['modified'].encode())
            for name in patch.TESTS:
                self.assertEqual((source / name).read_bytes(), value['tests'][name]['modified'].encode())
            with self.assertRaisesRegex(ValueError, 'source-identity'):
                patch.apply(source)

    def test_exact_old_nine_and_thirteen_plus_two_lit_no_missing_extra_or_skip(self):
        names = [Path(row['path']).name for row in results.selection()['wasmTests']]
        root = ET.Element('testsuite', failures='0', errors='0', skipped='0')
        for name in names:
            ET.SubElement(root, 'testcase', name=name)
        good = ET.tostring(root)
        actual = results.lit(good)
        self.assertEqual(actual['privateScalar']['sourceRunLines'], 5)
        self.assertEqual((actual['passed'], actual['originalSjLj']['passed'], actual['privateScalar']['passed']), (15, 13, 2))
        self.assertEqual(results.units, old_results.units)
        self.assertEqual(patch.unit_cases(), old_patch.unit_cases())
        self.assertEqual(len(patch.unit_cases()), 9)
        self.assertEqual(results.cross_pass, old_results.cross_pass)
        for name in patch.TESTS:
            self.assertIn(name, [row['path'] for row in results.selection()['wasmTests']])
        self.assertEqual(sum(row['modified'].count('; RUN:') for row in patch.manifest()['tests'].values()), 5)
        root.remove(root[-1])
        with self.assertRaisesRegex(ValueError, 'case-set'):
            results.lit(ET.tostring(root))
        root = ET.fromstring(good)
        ET.SubElement(root[-1], 'skipped')
        with self.assertRaisesRegex(ValueError, 'not-passed'):
            results.lit(ET.tostring(root))
        root = ET.fromstring(good)
        root[-1].set('name', names[0])
        with self.assertRaisesRegex(ValueError, 'case-set'):
            results.lit(ET.tostring(root))

    def test_typed_carrier_has_both_patch_identities_and_keeps_original_owner_bounds(self):
        self.assertIs(producer.Commands, old_producer.Commands)
        self.assertEqual((producer.SECONDS, producer.BUILD_SECONDS, producer.BUILD_JOBS, producer.LINK_JOBS),
                         (5400, 4500, 4, 1))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            products = root / 'products'
            binary = products / 'toolchain/bin/clang-21'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'small nonexecutable carrier fixture')
            for name in carrier.TOP - {'toolchain'}:
                (products / name).write_bytes(name.encode())
            limit = time.monotonic() + 10
            created = carrier.create(root, '1' * 40, limit)
            manifest = json.loads((root / carrier.MANIFEST).read_bytes())
            carrier.verify_carrier(root, carrier.ARCHIVE, manifest, limit)
            self.assertEqual(set(manifest['members']) & carrier.TOP, carrier.TOP)
            self.assertIn('LLVM-PATCH.json', manifest['members'])
            self.assertIn('LLVM-PRIVATE-STORES.json', manifest['members'])
            (products / 'LLVM-PRIVATE-STORES.json').unlink()
            with self.assertRaisesRegex(ValueError, 'product-set'):
                carrier.payload_rows(products, limit)
            with mock.patch.object(carrier, 'CARRIER_BYTES', created['archive']['bytes'] - 1):
                with self.assertRaisesRegex(ValueError, 'file-bound'):
                    carrier.verify_carrier(root, carrier.ARCHIVE, manifest, limit)


if __name__ == '__main__':
    unittest.main()
