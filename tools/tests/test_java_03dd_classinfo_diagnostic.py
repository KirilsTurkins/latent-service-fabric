"""Bounded ClassInfo refusal identification; not a guest qualification."""
import hashlib
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ClassInfoDevelopmentDiagnostic(unittest.TestCase):
    def test_ordinal_output_has_an_exact_inverse_and_no_guest_identity(self):
        source = (ROOT/'tools/java_guest/coroutine_patch.py').read_text(encoding='utf-8')
        old = 'int group = 0, flags = 0, metadata = 0;'
        self.assertEqual(source.count(old), 1)
        original = source.replace(old, 'int group = 0, flags = 0;', 1)
        begin = original.index('            // Fixed public TeaVM ClassInfo names only;')
        end = original.index('            if (method.hasModifier(ElementModifier.NATIVE)) flags |= 1;', begin)
        block = original[begin:end]
        self.assertEqual(re.findall(r'"([A-Za-z]+)"', block), [
            'modifiers', 'primitiveKind', 'name', 'simpleName', 'itemType', 'arrayType',
            'declaringClass', 'enclosingClass', 'isSuperTypeOf', 'parent', 'superinterfaceCount',
            'superinterface', 'enumConstantCount', 'enumConstant', 'newArrayInstance', 'putItem',
            'getItem', 'arrayLength', 'newInstance', 'newProxyInstance', 'initializeNewInstance',
            'initialize', 'reflection', 'rewind', 'next', 'hasNext', 'classObject'])
        self.assertIn('metadata = index + 1', block)
        self.assertNotIn('println(', block)
        original = original[:begin] + original[end:]
        marker = '        if (group == 16) System.err.println("latent.java.progress-class-info.v1 " + metadata);\n'
        self.assertEqual(original.count(marker), 1)
        original = original.replace(marker, '', 1)
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         '48a709f95feda2175cece9f54c0f0b50ce5ad53964142286a121dbdb329f2f91')

    def test_workflow_targets_one_fixed_branch_and_original_public_fixture(self):
        text = (ROOT/'.github/workflows/java-classinfo-fiber-diagnostic.yml').read_text(encoding='utf-8')
        self.assertIn("branches: ['diag/java-development-03dd-classinfo-20261105']", text)
        self.assertEqual(text.count('python3 -B tools/qualify_java_fibers.py'), 1)
        self.assertIn('--wasi-sdk "$LSF_JAVA_CLASSINFO_WASI_SDK"', text)
        self.assertIn('compiler/*-java-to-c.log', text)
        self.assertIn('test_java_03dd_classinfo_diagnostic.py', text)


if __name__ == '__main__':
    unittest.main()
