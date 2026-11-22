"""Compiler-free source/lifetime controls for the pinned exception-slot repair."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import java_capsule_build, qualify_java_fibers
from tools.java_guest import exception_slots as slots

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / 'tools/tests/fixtures/java-exception-slots/exceptions.h'
REGION = '''    TEAVM_TRY
        callback();
    TEAVM_CATCH
        case 1: { recover(); break; }
    TEAVM_END_TRY
'''


def function(body=REGION + REGION, name='method'):
    return ('void ' + name + '(void) {\n' + body + '}\n').encode()


class ExceptionSlotsTests(unittest.TestCase):
    def test_sequential_regions_share_one_automatic_object_not_one_setjmp(self):
        raw = function(REGION * 160)
        changed, record = slots.transform(raw)
        self.assertEqual(record, {'methods': 1, 'regions': 160, 'slots': 1})
        self.assertEqual(changed.count(b'TeaVM_LongjmpDesc lsf_teavm_jump_slot_0;'), 1)
        self.assertEqual(changed.count(b'LSF_TEAVM_TRY_SLOT(lsf_teavm_jump_slot_0)'), 160)
        self.assertEqual(changed.count(b'TEAVM_CATCH'), 160)
        self.assertEqual(changed.count(b'TEAVM_END_TRY'), 160)
        self.assertEqual(changed.count(b'callback();'), 160)
        # Undo only the intended declaration and marker changes. Every callback,
        # handler, return/goto, restore and generated spill must remain exact.
        restored = changed.replace(b'\n    TeaVM_LongjmpDesc lsf_teavm_jump_slot_0;', b'')
        restored = restored.replace(b'LSF_TEAVM_TRY_SLOT(lsf_teavm_jump_slot_0)', b'TEAVM_TRY')
        self.assertEqual(restored, raw)

    def test_nested_handlers_have_independent_objects_in_each_function(self):
        nested = '    TEAVM_TRY\n' + REGION * 2 + '    TEAVM_CATCH\n        case 2: { break; }\n    TEAVM_END_TRY\n'
        raw = function(nested) + function(nested, 'recursive')
        changed, record = slots.transform(raw)
        self.assertEqual(record, {'methods': 2, 'regions': 6, 'slots': 4})
        self.assertEqual(changed.count(b'TeaVM_LongjmpDesc lsf_teavm_jump_slot_0;'), 2)
        self.assertEqual(changed.count(b'TeaVM_LongjmpDesc lsf_teavm_jump_slot_1;'), 2)
        self.assertNotIn(b'lsf_teavm_jump_slot_0[', changed)
        self.assertNotIn(b'static TeaVM_LongjmpDesc', changed)
        self.assertEqual(changed.count(b'LSF_TEAVM_TRY_SLOT(lsf_teavm_jump_slot_1)'), 4)

    def test_single_and_overlapping_regions_are_byte_identical(self):
        for body in ('    return;\n', REGION,
                     '    TEAVM_TRY\n' + REGION + '    TEAVM_CATCH\n    TEAVM_END_TRY\n'):
            with self.subTest(body=body):
                raw = function(body)
                self.assertEqual(slots.transform(raw), (raw, {'methods': 0, 'regions': 0, 'slots': 0}))

    def test_literals_and_comments_cannot_add_handlers_or_scopes(self):
        prefix = ('    const char *text = "} TEAVM_TRY \\\" {";\n'
                  "    char quote = '\\'';\n"
                  '    /* TEAVM_CATCH } TEAVM_END_TRY */\n'
                  '    // { TEAVM_TRY\n')
        raw = function(prefix + REGION * 2)
        changed, record = slots.transform(raw)
        self.assertEqual(record['slots'], 1)
        self.assertIn(prefix.encode(), changed)

    def test_unproved_shapes_refuse_before_rewriting(self):
        cases = (
            function().replace(b'TEAVM_CATCH', b'', 1),
            function().replace(b'TEAVM_END_TRY', b'', 1),
            function().replace(b'TEAVM_CATCH', b'TEAVM_CATCH\n    TEAVM_CATCH', 1),
            function().replace(b'TEAVM_TRY', b'TEAVM_TRY(extra)', 1),
            function().replace(b'callback();', b'if (condition) {', 1),
            REGION.encode(),
            b'#define TEAVM_TRY other\n' + function(),
            function().replace(b'callback();', b'#if EXTERNAL\ncallback();\n#endif', 1),
            function().replace(b'callback();', b'int lsf_teavm_jump_slot_0;', 1),
            function().replace(b'callback();', b'int teavm_longJmpdesc;', 1),
            function() + b'/* unterminated', function() + b'"unterminated',
            function() + b'\0',
            b'#de\\\nfine TEAVM_TRY other\n' + function(),
        )
        for raw in cases:
            with self.subTest(raw=raw[-80:]), self.assertRaises(ValueError):
                slots.transform(raw)

    def test_pinned_macro_preserves_original_restore_and_rethrow(self):
        original = HEADER.read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), slots.HEADER_SHA256)
        value = slots.header(original)
        self.assertTrue(value.startswith(original))
        added = value[len(original):]
        self.assertIn(b'TEAVM_USE_SETJMP && defined(LSF_JAVA_ACTIVATION_PROFILE)', added)
        self.assertIn(b'setjmp((slot).buffer)', added)
        self.assertIn(b'(slot).previous = teavm_shadowStack.header.jmpTarget;', added)
        self.assertIn(b'teavm_shadowStack.header.jmpTarget = &(slot);', added)
        self.assertNotIn(b'TeaVM_LongjmpDesc', added)
        self.assertNotIn(b'#define TEAVM_CATCH', added)
        with self.assertRaisesRegex(ValueError, 'header-preimage'):
            slots.header(original + b'\n')

    def tree(self, root, first=None, second=None):
        (root / 'exceptions.h').write_bytes(HEADER.read_bytes())
        (root / 'first.c').write_bytes(function() if first is None else first)
        (root / 'second.c').write_bytes(function(REGION) if second is None else second)

    def test_staging_records_source_identities_and_validates_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.tree(root)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            record = slots.stage(root)
            self.assertEqual(record['regions'], 2)
            self.assertEqual(record['slots'], 1)
            self.assertEqual(record['files'][0]['path'], 'first.c')
            self.assertEqual(record['files'][0]['inputSha256'], hashlib.sha256(before['first.c']).hexdigest())
            self.assertEqual(record['files'][0]['outputSha256'], hashlib.sha256((root / 'first.c').read_bytes()).hexdigest())
            self.assertEqual((root / 'second.c').read_bytes(), before['second.c'])
            with self.assertRaisesRegex(ValueError, 'header-preimage'):
                slots.stage(root)
        for bad in (function().replace(b'TEAVM_CATCH', b'', 1),
                    b'#define TEAVM_TRY replacement\n', b'int LSF_TEAVM_TRY_SLOT;\n',
                    b'#de\\\nfine TEAVM_TRY replacement\n'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.tree(root, second=bad)
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                with self.assertRaises(ValueError):
                    slots.stage(root)
                self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_staging_leaves_no_reuse_inputs_exact_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.tree(root, first=function(REGION))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(slots.stage(root)['methods'], 0)
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            (root / 'alias.c').symlink_to(root / 'first.c')
            with self.assertRaisesRegex(ValueError, 'entry-bound'):
                slots.stage(root)

    def test_owner_is_in_source_bound_build_recipe(self):
        name = 'tools/java_guest/exception_slots.py'
        self.assertIn(name, java_capsule_build.RECIPE)
        selected = qualify_java_fibers.ROOT / name
        original = (ROOT / name).read_bytes()
        with patch.object(qualify_java_fibers, 'read_file', side_effect=lambda p: original if p == selected else b'fixture'):
            before = qualify_java_fibers.recipe_inputs()
        with patch.object(qualify_java_fibers, 'read_file', side_effect=lambda p: original + b'\n' if p == selected else b'fixture'):
            after = qualify_java_fibers.recipe_inputs()
        self.assertEqual([key for key in before if before[key] != after[key]], [name])


class ExceptionSlotsLinkTests(unittest.TestCase):
    def test_both_guarded_link_routes_receive_only_post_adaptation_sealed_bytes(self):
        import time
        from types import SimpleNamespace
        from unittest.mock import Mock
        from tools.java_guest import enum_guard, date_link_guard

        for date in (False, True):
            with self.subTest(date=date), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / 'project'
                generated = project / 'build/teavm-c/c'
                generated.mkdir(parents=True)
                (generated / 'exceptions.h').write_bytes(HEADER.read_bytes())
                (generated / 'method.c').write_bytes(function())
                (generated / 'all.c').write_text('#define _XOPEN_SOURCE\n#define __USE_XOPEN\n'
                                                '#define _GNU_SOURCE\n#include "method.c"\n')
                index = project / 'compiler-patch'
                index.mkdir()
                (index / 'enum-index-v1.tsv').write_bytes(b'lsf-teavm-enum-index-v1\n')
                (index / 'date-init-required-v1.txt').write_bytes(b'required\n' if date else b'unused\n')
                output = root / 'out'
                bindings = output / 'bindings'
                bindings.mkdir(parents=True)
                for name in ('bridge.c', 'probe.c', 'probe.h', 'probe_component_type.o'):
                    (bindings / name).write_bytes(b'fixture')
                def preprocess(*_args):
                    self.assertIn(b'LSF_TEAVM_TRY_SLOT', (generated / 'method.c').read_bytes())
                    self.assertEqual((generated / 'exceptions.h').read_bytes(), slots.header(HEADER.read_bytes()))
                    return b'preprocessed fixture'
                compiler = SimpleNamespace(sdk=root / 'sdk', deadline=time.monotonic() + 30,
                                           capture_preprocessed=Mock(side_effect=preprocess))
                receipt = {'dateGuard': {}} if date else {}
                with patch.object(enum_guard, 'seal', return_value=(b'sealed fixture', receipt)) as seal, \
                        patch.object(enum_guard.c_failure_context, 'run', return_value='') as link, \
                        patch.object(date_link_guard, 'run', return_value={'test': 'date'}) as date_link:
                    result = enum_guard.run(compiler, generated, (), output, output / 'core.wasm')
                self.assertEqual(result['exceptionSlots']['slots'], 1)
                self.assertEqual(result['exceptionSlots']['regions'], 2)
                seal.assert_called_once()
                self.assertEqual(seal.call_args.kwargs['source_before'], enum_guard.inventory(generated)[-1])
                if date:
                    link.assert_not_called()
                    self.assertEqual(date_link.call_args.args[-1], b'sealed fixture')
                else:
                    date_link.assert_not_called()
                    self.assertEqual(link.call_args.kwargs['input_bytes'], b'sealed fixture')


if __name__ == '__main__':
    unittest.main()
