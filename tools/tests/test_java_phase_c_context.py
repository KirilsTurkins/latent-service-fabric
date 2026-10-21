"""Only the observed public phase fixture may retain its failed TimeZone C."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tools.java_guest import c_failure_context as context
from tools.rust_capsule_project import digest


class JavaPhaseCContext(unittest.TestCase):
    def test_failed_public_assembly_retains_only_both_exact_regular_wasm_inputs(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();source = root/'compiled';source.mkdir();output = root/'output';output.mkdir()
            raw = {'core.wasm': b'\0asm\x01\0\0\0public-core',
                'closed-runtime.wasm': b'\0asm\x01\0\0\0closed-adapter'}
            for name, value in raw.items(): (source/name).write_bytes(value)
            (source/'private-neighbour').write_bytes(b'never-capture')
            compiler = SimpleNamespace(records=[{'stage': 'component-new', 'exitCode': 1}])
            context.retain_component_inputs(compiler, source, output, context.PHASE_FIXTURE_SOURCES)
            record = json.loads((output/'component-inputs.json').read_bytes())
            self.assertFalse(record['qualification']);self.assertTrue(record['publicFixtureOnly'])
            self.assertEqual(set(record['inputs']), set(raw))
            for name, value in raw.items():
                self.assertEqual((output/'component-inputs'/name).read_bytes(), value)
                self.assertEqual(record['inputs'][name], {'sha256': digest(value), 'bytes': len(value)})
            self.assertEqual(sorted(path.name for path in (output/'component-inputs').iterdir()), sorted(raw))
            self.assertEqual(record['logLimitBytesUnchanged'], 16*1024*1024)

    def test_default_success_other_stages_and_nonclosed_selections_never_capture_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for selected, stage, code in (((), 'component-new', 1),
                    (context.FIXTURE_SOURCES, 'component-new', 1),
                    (list(context.PHASE_FIXTURE_SOURCES), 'component-new', 1),
                    (context.PHASE_FIXTURE_SOURCES, 'java-to-c', 1),
                    (context.PHASE_FIXTURE_SOURCES, 'component-new', 0)):
                compiler = SimpleNamespace(records=[{'stage': stage, 'exitCode': code}])
                context.retain_component_inputs(compiler, root/'unopened', root, selected)
                self.assertEqual(list(root.iterdir()), [])

    def test_missing_oversized_bad_magic_and_hardlinked_pair_refuse_before_raw_publication(self):
        import os
        for kind in ('missing', 'oversized', 'magic', 'hardlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve();source = root/'compiled';source.mkdir();output = root/'output';output.mkdir()
                (source/'core.wasm').write_bytes(b'\0asm\x01\0\0\0core')
                adapter = source/'closed-runtime.wasm'
                if kind == 'oversized':
                    with adapter.open('wb') as stream: stream.truncate(4*1024*1024+1)
                elif kind == 'magic': adapter.write_bytes(b'not-wasm')
                elif kind == 'hardlink': os.link(source/'core.wasm', adapter)
                compiler = SimpleNamespace(records=[{'stage': 'component-new', 'exitCode': 1}])
                context.retain_component_inputs(compiler, source, output, context.PHASE_FIXTURE_SOURCES)
                self.assertFalse((output/'component-inputs').exists())
                self.assertTrue((output/'component-inputs-refused.json').is_file())

    def test_failed_retention_does_not_mask_the_original_assembly_exception(self):
        original = RuntimeError('original-assembly-failure')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            compiler = SimpleNamespace(records=[{'stage': 'component-new', 'exitCode': 1}])
            with self.assertRaises(RuntimeError) as caught:
                try: raise original
                finally: context.retain_component_inputs(compiler, root/'missing', root, context.PHASE_FIXTURE_SOURCES)
            self.assertIs(caught.exception, original)

    def test_old_selection_refuses_and_phase_selection_retains_actual_declaration_and_uses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); path = root/'c/j/u/TimeZone.c'
            path.parent.mkdir(parents=True)
            raw = (b'void public_zone(void) {\n    int32_t teavm_local_11;\n'
                b'    teavm_local_11 = 0;\n    TEAVM_GC_ROOT(INT32_C(0), teavm_local_11);\n}\n')
            path.write_bytes(raw)
            log = f'{path.as_posix()}:4:5: error: incompatible integer to pointer conversion\n'.encode()
            with self.assertRaisesRegex(ValueError, 'no-selected-error'):
                context.collect(root, log, context.FIXTURE_SOURCES)
            observed = context.collect(root, log, context.PHASE_FIXTURE_SOURCES)
            row = observed['errors'][0]
            self.assertEqual(row['path'], 'c/j/u/TimeZone.c')
            self.assertEqual(row['sourceDigest'], digest(raw))
            self.assertEqual(row['declarations'], [{'line': 2, 'text': '    int32_t teavm_local_11;'}])
            self.assertEqual([entry['line'] for entry in row['references']], [2, 3, 4])
            self.assertLessEqual(len(context.encoded(observed)), 128*1024)

    def test_phase_selection_is_closed_and_never_reads_unselected_source(self):
        self.assertEqual(context.FIXTURE_SOURCES, ('c/d/l/a/Capsule.c', 'c/j/u/z/GZIPInputStream.c'))
        for selected in (list(context.PHASE_FIXTURE_SOURCES),
                (*context.PHASE_FIXTURE_SOURCES, 'c/j/u/Private.c'), ('c/j/u/',),
                (*context.FIXTURE_SOURCES, '../TimeZone.c')):
            compiler = SimpleNamespace(run=Mock())
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                context.run(compiler, Path('unopened'), selected, '-O2')
            compiler.run.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            log = f'{(root/"c/j/u/Private.c").as_posix()}:1:1: error: private\n'.encode()
            with self.assertRaisesRegex(ValueError, 'no-selected-error'):
                context.collect(root, log, context.PHASE_FIXTURE_SOURCES)

    def test_failed_compiler_is_never_replayed_or_accepted_and_all_byte_limits_stay_fixed(self):
        original = RuntimeError('original-clang-failure')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); logs = root/'logs'; logs.mkdir()
            (logs/'0-c-to-wasm.log').write_bytes(b'no selected diagnostic\n')
            compiler = SimpleNamespace(run=Mock(side_effect=original), records=[{'stage': 'c-to-wasm'}],
                directory=logs, retained_bytes=0)
            with self.assertRaises(RuntimeError) as caught:
                context.run(compiler, root, context.PHASE_FIXTURE_SOURCES, '-O2', 'all.c')
            self.assertIs(caught.exception, original)
            compiler.run.assert_called_once_with('c-to-wasm', 'clang', '-O2', 'all.c')
            self.assertTrue((logs/'0-c-to-wasm-context.command.json').is_file())
        self.assertEqual((context.MAX_FILE, context.MAX_CONTEXT), (4*1024*1024, 128*1024))
