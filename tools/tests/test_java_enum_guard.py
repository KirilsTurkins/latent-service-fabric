"""Focused controls for the guarded C proof; no guest execution is implied."""
from pathlib import Path
import ast
import hashlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from tools.java_guest import enum_guard
from tools.tests.test_java_exception_slots import HEADER, function
from tools.java_guest.compiler import Compiler
from tools.java_guest.llvm_private_store_consumer import PrivateScalarPublicCompiler
from tools.java_guest.llvm_ssa_consumer import DerivedPublicCompiler
from tools.java_guest.public_wineh import PublicWinEHCompiler


class EnumGuardControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / 'all.c').write_text('#define _XOPEN_SOURCE\n#define __USE_XOPEN\n'
            '#define _GNU_SOURCE\n#include "enum.c"\n', encoding='ascii')
        self.enum = self.root / 'enum.c'
        self.enum.write_text('''void* sfld_E_FIRST;
void* sfld_E_SECOND;
static void* E_Cls_enumConstants[3] = { (void*) (intptr_t) 2, &sfld_E_FIRST, &sfld_E_SECOND };
alignas(8) E_VT E_Cls = {
 .modifiers = 65536,
 .superclass = (TeaVM_Class*) &jl_Enum_Cls,
 .enumValues = E_Cls_enumConstants
};
''', encoding='ascii')
        self.index = b'lsf-teavm-enum-index-v1\nE_Cls\tjl_Enum_Cls\tsfld_E_FIRST\tsfld_E_SECOND\n'
        self.preprocessed = (b'#define SOME_HEADER_MACRO 1\n# 1 "generated.c"\n'
            + enum_guard.OLD_COUNT + b'\n' + enum_guard.OLD_VALUE + b'\n'
            + self.enum.read_bytes().replace(b'alignas(8)', b'_Alignas(8)'))

    def tearDown(self):
        self.temporary.cleanup()

    def test_seals_exact_helpers_with_authenticated_order(self):
        result, receipt = enum_guard.seal(self.preprocessed, self.root, self.index)
        self.assertNotIn(enum_guard.OLD_COUNT, result)
        self.assertNotIn(enum_guard.OLD_VALUE, result)
        self.assertIn(b'if (index == 0) return sfld_E_FIRST;', result)
        self.assertIn(b'if (index == 1) return sfld_E_SECOND;', result)
        self.assertEqual((receipt['classes'], receipt['slots']), (1, 2))

    def test_rejects_drift_and_mixed_or_duplicate_compiler_index(self):
        variants = (self.index.replace(b'sfld_E_FIRST\tsfld_E_SECOND', b'sfld_E_SECOND\tsfld_E_FIRST'),
                    self.index + self.index.split(b'\n', 1)[1],
                    self.index.replace(b'jl_Enum_Cls', b'jl_Object_Cls'))
        for value in variants:
            with self.subTest(index=value), self.assertRaises(ValueError):
                enum_guard.seal(self.preprocessed, self.root, value)
        for old, new in ((b'&sfld_E_FIRST', b'&sfld_E_OTHER'),
                         (b'.enumValues = E_Cls_enumConstants', b'.enumValues = 0'),
                         (enum_guard.OLD_COUNT, enum_guard.OLD_COUNT + enum_guard.OLD_COUNT)):
            with self.subTest(old=old), self.assertRaises(ValueError):
                enum_guard.seal(self.preprocessed.replace(old, new, 1), self.root, self.index)

    def test_rejects_macro_redirects_and_unsupported_preprocessing(self):
        for suffix in (b'\n#define E_Cls jl_Object_Cls\n',
                       b'\n#define teavm_enumConstant fake\n',
                       b'\n#undef sfld_E_FIRST\n',
                       b'\n#pragma weak E_Cls\n',
                       b'\n#include "evil.h"\n',
                       b'\n__asm__("alias");\n',
                       b'\n"unterminated',
                       b'\n/* unprocessed comment */\n',
                       b'\nint bad$token;\n',
                       b'\nint bad\xfftoken;\n'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                enum_guard.seal(self.preprocessed + suffix, self.root, self.index)

    def test_rejects_a_changed_source_snapshot_and_invalid_parent_chains(self):
        with self.assertRaisesRegex(ValueError, 'source-drift'):
            enum_guard.seal(self.preprocessed, self.root, self.index, source_before='0' * 64)
        for parent in ('E_Cls', 'Missing_Cls'):
            self.enum.write_text(self.enum.read_text().replace('jl_Enum_Cls', parent))
            with self.subTest(parent=parent), self.assertRaisesRegex(ValueError, 'parent-chain'):
                enum_guard.seal(self.preprocessed, self.root, self.index)
            self.enum.write_text(self.enum.read_text().replace(parent, 'jl_Enum_Cls'))

    def test_managed_link_reserves_stack_below_data_with_original_memory_ceiling(self):
        generated = self.root / 'project/build/teavm-c'
        generated.mkdir(parents=True)
        (generated / 'all.c').write_bytes((self.root / 'all.c').read_bytes()
                                          + b'#include "lifetime.c"\n')
        (generated / 'enum.c').write_bytes(self.enum.read_bytes())
        (generated / 'exceptions.h').write_bytes(HEADER.read_bytes())
        (generated / 'lifetime.c').write_bytes(function())
        indices = self.root / 'compiler-patch'
        indices.mkdir()
        (indices / 'enum-index-v1.tsv').write_bytes(self.index)
        (indices / 'date-init-required-v1.txt').write_bytes(b'unused\n')
        destination = self.root / 'output'
        bindings = destination / 'bindings'
        bindings.mkdir(parents=True)
        for name in ('bridge.c', 'probe.c', 'probe.h', 'probe_component_type.o'):
            (bindings / name).write_bytes(name.encode())
        compiler = SimpleNamespace(sdk=self.root / 'sdk', deadline=float('inf'),
            capture_preprocessed=Mock(return_value=self.preprocessed), run=Mock(return_value=''))
        receipt = enum_guard.run(compiler, generated, (), destination, destination / 'core.wasm')
        args, kwargs = compiler.run.call_args
        self.assertEqual(args[:2], ('c-to-wasm', 'clang'))
        self.assertIn('-Wl,--stack-first', args)
        self.assertEqual([arg for arg in args if str(arg).startswith('-Wl,-z,stack-size=')],
                         ['-Wl,-z,stack-size=65536'])
        self.assertEqual([arg for arg in args if str(arg).startswith('-Wl,--max-memory=')],
                         ['-Wl,--max-memory=67108864'])
        self.assertEqual(receipt['cStack'], {'bytes': 65536, 'layout': 'stack-first'})
        self.assertEqual(receipt['exceptionSlots']['schemaVersion'], 'latent.java.exception-slots.v1')
        self.assertEqual(receipt['exceptionSlots']['regions'], 2)
        self.assertEqual(receipt['exceptionSlots']['slots'], 1)
        self.assertIn(b'LSF_TEAVM_TRY_SLOT', (generated / 'lifetime.c').read_bytes())
        self.assertEqual(kwargs['input_bytes'], enum_guard.seal(
            self.preprocessed, generated, self.index, date_required=False)[0])
        # A link failure must still abort; a planned reservation is no execution receipt.
        failure = RuntimeError('bounded-link-failed')
        compiler.run.side_effect = failure
        # A new link attempt starts with freshly generated compiler inputs.
        (generated / 'exceptions.h').write_bytes(HEADER.read_bytes())
        (generated / 'lifetime.c').write_bytes(function())
        with self.assertRaises(RuntimeError) as caught:
            enum_guard.run(compiler, generated, (), destination, destination / 'core.wasm')
        self.assertIs(caught.exception, failure)

    def test_managed_link_changes_select_both_signed_qualification_owners(self):
        import json
        from tools import ci_lane_inventory as lanes
        root = Path(__file__).resolve().parents[2]
        for name in ('java-scheduled-library.yml', 'java-scheduled-development.yml'):
            with self.subTest(workflow=name):
                model = lanes.workflow_model((root / '.github/workflows' / name).read_text())
                contract = json.loads((root / 'tools/ci/contracts/workflows' / name / 'workflow.json').read_text())
                self.assertEqual(model['on'], contract['policy']['on'])
                for source in ('tools/java_guest/enum_guard.py', 'tools/java_guest/date_link_guard.py'):
                    self.assertIn(source, model['on']['push']['paths'])

    def test_unmodified_nonfiber_clang_command_and_frozen_diagnostics(self):
        # The non-fiber command retains every flag and positional input from
        # development before this guarded activation-only change.
        tree = ast.parse((Path(__file__).resolve().parents[2] / 'tools/java_guest/compiler.py')
                         .read_text(encoding='utf8'))
        compiler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Compiler')
        method = next(node for node in compiler.body if isinstance(node, ast.FunctionDef) and node.name == 'compile')
        commands = [node for node in ast.walk(method) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == 'c_failure_context' and node.func.attr == 'run']
        self.assertEqual(len(commands), 1)
        self.assertEqual(hashlib.sha256(ast.dump(commands[0], include_attributes=False).encode()).hexdigest(),
                         '7d1958cc4912eb28bbc3d47e1ee4121e07922d18082befd394124ee806cc7190')
        for cls in (PrivateScalarPublicCompiler, DerivedPublicCompiler, PublicWinEHCompiler):
            with self.subTest(variant=cls.__name__), self.assertRaisesRegex(ValueError, 'not qualified'):
                Compiler.compile(object.__new__(cls), self.root, self.root, 'world', self.root / 'out',
                                 activation_profile=True)


if __name__ == '__main__':
    unittest.main()
