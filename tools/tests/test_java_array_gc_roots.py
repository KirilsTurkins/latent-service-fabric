import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.java_guest import coroutine_patch as patch
from tools.rust_capsule_project import ROOT, read_file


class PinnedArrayTypeWorklistTests(unittest.TestCase):
    def test_exact_source_adds_only_array_graph_seed_and_refuses_unreviewed_preimages(self):
        raw = read_file(ROOT/'sdk/java-guest/fibers/compiler-patch/TypeInferer.java')
        self.assertEqual(hashlib.sha256(raw).hexdigest(), patch.TYPE_INFERER_SHA256)
        corrected = patch.corrected_type_source(raw)
        self.assertEqual(corrected, raw.replace(patch.TYPE_SEED_BEFORE.encode(), patch.TYPE_SEED_AFTER.encode()).replace(
            patch.TYPE_ELEMENT_BEFORE.encode(), patch.TYPE_ELEMENT_AFTER.encode()))
        self.assertIn(b'Licensed under the Apache License, Version 2.0', corrected)
        for changed in (raw+b' ', corrected, raw.replace(b'degree - 1', b'degree + 1'), b'private source'):
            with self.subTest(size=len(changed)), self.assertRaisesRegex(ValueError, 'unreviewed-teavm-type-source'):
                patch.corrected_type_source(changed)

    def test_real_ir_requires_old_scalar_root_and_new_nested_types_with_reference_roots(self):
        text = read_file(ROOT/'sdk/java-guest/fibers/compiler-patch/ArrayTypeCheck.java').decode()
        for required in ('new TypeInferer()', 'inferer.inferTypes(program, method.getReference())',
                'new GetElementInstruction(type)', 'ValueType.arrayOf(ValueType.arrayOf(ValueType.INTEGER))',
                'consume.setArguments(scalar, object, row, nested)',
                'original ? VariableType.OBJECT : VariableType.INT',
                'original ? VariableType.OBJECT : VariableType.INT_ARRAY',
                'new GCShadowStackContributor(new Characteristics(name -> null)).contribute(program, method)',
                'Set.of(scalar, object, row, nested) : Set.of(object, row)',
                'array-control-primitive-root-or-reference-root-lost'):
            self.assertIn(required, text)
        main = read_file(ROOT/'sdk/java-guest/fibers/compiler-patch/Check.java').decode()
        array_check = 'ArrayTypeCheck.check(args[0]);'
        legacy_print = r'System.out.println("{\"schemaVersion\":\"latent.java.coroutine-phi-control.v1\",\"mode\":\"'
        self.assertEqual(main.count(array_check), 1)
        self.assertEqual(main.count(legacy_print), 1)
        self.assertLess(main.index(array_check), main.index(legacy_print))
        self.assertEqual(patch.TYPE_CLASSES, frozenset(patch.TYPE_ROOT+name for name in (
            'TypeInferer.class', 'TypeInferer$1.class', 'TypeInferer$2.class',
            'TypeInferer$InferenceKind.class', 'TypeInferer$InferenceType.class')))

    def test_missing_type_class_or_control_refuses_before_private_jar_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); original = root/'original.jar'; classes = root/'classes'
            with zipfile.ZipFile(original, 'w') as jar:
                for name in sorted(patch.PATCH_CLASSES): jar.writestr(name, b'original class')
                jar.writestr('unchanged.class', b'original unrelated')
            for name in patch.PATCH_CLASSES|patch.CONTROLS:
                path = classes/name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'\xca\xfe\xba\xbecompiled')
            for missing in (sorted(patch.TYPE_CLASSES)[0], patch.ARRAY_CONTROL):
                path = classes/missing; raw = path.read_bytes(); path.unlink()
                output = root/'rejected.jar'
                with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'compiled-closure'):
                    patch.replace_jar(original, classes, output)
                self.assertFalse(output.exists()); path.write_bytes(raw)
            with zipfile.ZipFile(root/'missing.jar', 'w') as jar:
                for name in sorted(patch.COROUTINE_CLASSES): jar.writestr(name, b'original class')
            with self.assertRaisesRegex(ValueError, 'class-closure'):
                patch.jar_entries(root/'missing.jar')

    def test_real_restored_array_control_uses_exact_erased_fiber_return_before_primitive_load(self):
        text = read_file(ROOT/'sdk/java-guest/fibers/compiler-patch/ArrayTypeCheck.java').decode()
        for required in ('"org.teavm.runtime.Fiber", "popObject"',
                'restore.setInstance(fiber); restore.setReceiver(array)',
                'element(program, array, index, ArrayElementType.INT)',
                'exit.setValueToReturn(scalar)', 'scalarRoot != original',
                'array-control-restored-primitive-type-lost', 'restoredArray(mode);'):
            self.assertIn(required, text)
        original = read_file(ROOT/'sdk/java-guest/fibers/compiler-patch/TypeInferer.java')
        seed_only = original.replace(patch.TYPE_SEED_BEFORE.encode(), patch.TYPE_SEED_AFTER.encode())
        self.assertIn(patch.TYPE_ELEMENT_BEFORE.encode(), seed_only)
        self.assertNotIn(patch.TYPE_ELEMENT_BEFORE.encode(), patch.corrected_type_source(original))
        for kind in ('BYTE', 'SHORT', 'CHAR', 'INT', 'LONG', 'FLOAT', 'DOUBLE', 'OBJECT'):
            self.assertEqual(patch.TYPE_ELEMENT_AFTER.count('case '+kind+':'), 1)


if __name__ == '__main__':
    unittest.main()
