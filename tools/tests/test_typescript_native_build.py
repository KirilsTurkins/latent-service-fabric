"""Native engine build-input guards; actual CMake execution is a separate gate."""
from pathlib import Path
import tempfile
import time
import unittest

from tools.typescript_guest import native_build as owner


class NativeBuildInputs(unittest.TestCase):
    def test_archive_composition_keeps_original_input_cap_and_bounds_added_objects(self):
        # Exact sizes retained from the normal hosted mach product and its
        # required upstream objects; no large allocation is needed here.
        limits = owner.combined_archive_limits({'bytes':535993684},{'objects':{'bytes':2863676}})
        self.assertEqual(limits['originalLibraryMaximumBytes'],512*1024**2)
        self.assertEqual(limits['maximumCombinedBytes'],535993684+2863676+4*1024**2)
        for library,objects in (({'bytes':512*1024**2+1},{'x':{'bytes':1}}),
                ({'bytes':1},{'x':{'bytes':16*1024**2+1}}),({'bytes':1},{}),
                ({'bytes':True},{'x':{'bytes':1}}),({'bytes':1},{'x':{'bytes':False}}),
                ({'bytes':1},{str(index):{'bytes':1} for index in range(65)})):
            with self.subTest(library=library,objects=objects), self.assertRaisesRegex(ValueError,'composition-input-bound'):
                owner.combined_archive_limits(library,objects)

    def test_upstream_object_list_rejects_changed_shape_duplicates_and_path_escape(self):
        original = b'    set(SM_OBJ_FILES\n        memory/build/original.o\n        mfbt/one.o\n    )\n'
        self.assertEqual(owner.supporting_objects(original),['memory/build/original.o','mfbt/one.o'])
        for changed in (original+original, original.replace(b'mfbt/one.o',b'../escape.o'),
                        original.replace(b'mfbt/one.o',b'/outside.o'),
                        original.replace(b'mfbt/one.o',b'memory/build/original.o'),
                        original.replace(b'mfbt/one.o',b'host-tool;injected.o')):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError,'supporting-objects'):
                owner.supporting_objects(changed)

    def test_header_staging_preserves_original_bytes_and_adds_exact_original_confdefs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); library = root/'library'
            (library/'obj/dist/include/js').mkdir(parents=True)
            (library/'obj/js/src').mkdir(parents=True)
            header = library/'obj/dist/include/js/Original.h'; header.write_bytes(b'exact-header')
            confdefs = library/'obj/js/src/js-confdefs.h'; confdefs.write_bytes(b'exact-config')
            staged = root/'selected'
            owner.materialize_headers(library,staged,time.monotonic()+10)
            self.assertEqual((staged/'js/Original.h').read_bytes(),b'exact-header')
            self.assertEqual((staged/'js-confdefs.h').read_bytes(),b'exact-config')
            self.assertEqual(header.read_bytes(),b'exact-header')
            self.assertFalse((library/'obj/dist/include/js-confdefs.h').exists())
            (staged/'js/Original.h').write_bytes(b'private-staging')
            self.assertEqual(header.read_bytes(),b'exact-header')

    def test_header_deadline_and_conflicting_original_configuration_fail_closed(self):
        for expired in (True,False):
            with self.subTest(expired=expired), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); library = root/'library'
                (library/'obj/dist/include').mkdir(parents=True)
                (library/'obj/js/src').mkdir(parents=True)
                (library/'obj/dist/include/js-confdefs.h').write_bytes(b'changed-config')
                (library/'obj/js/src/js-confdefs.h').write_bytes(b'original-config')
                with self.assertRaisesRegex(ValueError,'installed-header-bound|confdefs-differs'):
                    owner.materialize_headers(library,root/'selected',time.monotonic()+(-1 if expired else 10))
                self.assertEqual((library/'obj/js/src/js-confdefs.h').read_bytes(),b'original-config')

    def test_source_inventory_returns_original_bytes_without_mutating_carrier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'nested').mkdir()
            (root/'nested/file').write_bytes(b'original')
            original, links = owner.sources(root)
            self.assertEqual(original,{'nested/file':b'original'})
            self.assertEqual(links,[])
            original['nested/file'] = b'changed'
            self.assertEqual((root/'nested/file').read_bytes(),b'original')


if __name__ == '__main__': unittest.main()
