"""Shared normal validation/refusal controls; no library or SDK is acquired."""
import ast
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.typescript_guest import native_build, owned_result_library


class TypeScriptOwnedLibraryTests(unittest.TestCase):
    def test_archive_reader_accepts_only_identical_original_duplicate_members(self):
        def member(name,payload):
            header=(name+'/').ljust(16)+'0'.ljust(12)+'0'.ljust(6)+'0'.ljust(6)+'100644'.ljust(8)+str(len(payload)).ljust(10)+'`\n'
            return header.encode()+payload+(b'\n' if len(payload)%2 else b'')
        raw=b'actual-object';identity={'bytes':len(raw),'sha256':owned_result_library.digest(raw)}
        with tempfile.TemporaryDirectory() as temporary:
            archive=Path(temporary)/'objects.a'
            archive.write_bytes(b'!<arch>\n'+member('lz4.o',raw)+member('lz4.o',raw))
            selected,observed=owned_result_library.archive_objects(archive,{'mozglue/static/lz4.o':identity},time.monotonic()+5,4096)
            self.assertEqual(selected,{'mozglue/static/lz4.o':raw})
            self.assertEqual(observed['matchingMembers'],{'mozglue/static/lz4.o':2})
            archive.write_bytes(b'!<arch>\n'+member('lz4.o',raw)+member('lz4.o',b'x'*len(raw)))
            with self.assertRaisesRegex(ValueError,'conflicting-identity'):
                owned_result_library.archive_objects(archive,{'mozglue/static/lz4.o':identity},time.monotonic()+5,4096)
            archive.write_bytes(b'!<arch>\n'+member('lz4.o',b'short'))
            with self.assertRaisesRegex(ValueError,'conflicting-size'):
                owned_result_library.archive_objects(archive,{'mozglue/static/lz4.o':identity},time.monotonic()+5,4096)

    def test_extracted_validator_preserves_every_original_normal_check(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/typescript_normal_library_validation.json').read_bytes())
        self.assertEqual(fixture['revision'],'17b2558bf08f2221657a5d2866b00218fb597d9e')
        self.assertEqual(hashlib.sha256(fixture['block'].encode()).hexdigest(),fixture['blockSha256'])
        original='def original(library_root):\n'+''.join(line[4:] for line in fixture['block'].splitlines(keepends=True))
        old=ast.parse(original).body[0]
        current=ast.parse(inspect.getsource(native_build.validated_library)).body[0]
        # Authenticate only the reviewed recipe-call extension before comparing
        # the complete historical validator. Every old inventory/byte/header/
        # archive check and the original expected fixture remain unchanged.
        reviewed = ast.parse("library_recipe_equivalence(name,read_file(ROOT/name),identity)").body
        historical = ast.parse("raise ValueError('typescript-native-library-recipe-drift')").body
        predicate = ast.parse("file_identity(ROOT/name) != identity",mode='eval').body
        found = 0
        for node in ast.walk(current):
            if isinstance(node,ast.If) and ast.dump(ast.Module(body=node.body,type_ignores=[])) == ast.dump(ast.Module(body=reviewed,type_ignores=[])):
                self.assertEqual(ast.dump(node.test),ast.dump(predicate))
                self.assertEqual(node.orelse,[])
                node.body = historical
                found += 1
        self.assertEqual(found,1)
        self.assertEqual(ast.dump(ast.Module(body=current.body[1:-1],type_ignores=[])),
                         ast.dump(ast.Module(body=old.body,type_ignores=[])))

    def test_normal_builder_calls_the_same_upfront_validator_before_acquisition(self):
        class Refused(Exception):
            pass
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);library=root/'library';library.mkdir()
            with patch.object(native_build.sys,'platform','linux'), \
                 patch.object(native_build,'validated_library',side_effect=Refused('original-validation')) as validator, \
                 patch.object(native_build.promise_library,'acquire',side_effect=AssertionError('acquisition-before-gate')):
                with self.assertRaises(Refused):native_build.build(root/'engine',library)
                validator.assert_called_once_with(library.resolve())

    def test_shared_validator_refuses_non_completed_library_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for status in ('failed','in-progress','core-compiled',''):
                (root/'library-build.json').write_text(json.dumps({'status':status}))
                with self.assertRaisesRegex(ValueError,'successful-original-library-receipt'):
                    native_build.validated_library(root)

    def test_library_paths_refuse_escape_and_unrelated_material(self):
        prefix=owned_result_library.producer.PREFIX+'library/'
        self.assertEqual(owned_result_library.library_member(prefix+'obj/js/src/build/libjs_static.a'),
                         'obj/js/src/build/libjs_static.a')
        for name in (prefix+'../outside',prefix+'/absolute',prefix+'obj/../outside',
                     prefix+'C:/outside',prefix+'obj\\outside',prefix+'./obj',
                     owned_result_library.producer.ENGINE+'engine.wasm'):
            with self.assertRaises(ValueError):owned_result_library.library_member(name)

    def test_own_reconstruction_calls_normal_validation_and_has_no_mach_fallback(self):
        source=Path(owned_result_library.__file__).read_text()
        tree=ast.parse(source)
        function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='reconstruct')
        calls=[node for node in ast.walk(function) if isinstance(node,ast.Call)]
        shared=[node for node in calls if isinstance(node.func,ast.Attribute) and
                isinstance(node.func.value,ast.Name) and node.func.value.id=='native_build'
                and node.func.attr=='validated_library']
        self.assertEqual(len(shared),1)
        self.assertNotIn("'mach'",source)
        self.assertNotIn('promise_library.build(',source)


if __name__=='__main__':unittest.main()
