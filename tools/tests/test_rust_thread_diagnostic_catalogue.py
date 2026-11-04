"""Exact legacy diagnostic origin and fail-closed delta reconstruction."""
import hashlib
import struct
import unittest
from tools import rust_thread_diagnostic_catalogue as legacy
from tools.rust_capsule_project import ROOT, read_file


class RustThreadDiagnosticCatalogueTests(unittest.TestCase):
    def test_each_fixed_cdd_source_reconstructs_the_exact_e3_identity(self):
        self.assertEqual(set(legacy.SPECS), {'body-image', 'normal-component', 'original-core', 'catalogue', 'origin'})
        for name, spec in legacy.SPECS.items():
            with self.subTest(name=name):
                actual = legacy.read_legacy(name)
                self.assertEqual(len(actual), spec[4])
                self.assertEqual(hashlib.sha256(actual).hexdigest(), spec[7])
        for name in ('unknown', '../catalogue', '', None):
            with self.subTest(name=name), self.assertRaises((ValueError, RuntimeError)):
                legacy.read_legacy(name)

    def test_tampered_wrong_source_truncated_and_trailing_are_refused(self):
        for name, spec in legacy.SPECS.items():
            source = read_file(ROOT / spec[0], legacy.MAX_SOURCE)
            patch = read_file(ROOT / spec[1], legacy.MAX_DELTA)
            changed_source = bytes([source[0] ^ 1]) + source[1:]
            changed_patch = patch[:len(patch)//2] + bytes([patch[len(patch)//2] ^ 1]) + patch[len(patch)//2+1:]
            for label, a, b in (('source', changed_source, patch), ('modified', source, changed_patch),
                                ('truncated', source, patch[:-1]), ('trailing', source, patch + b'\0')):
                with self.subTest(name=name, label=label), self.assertRaises((ValueError, RuntimeError)):
                    legacy.reconstruct(a, b, spec)
            wrong = (*spec[:7], '0' * 64)
            with self.subTest(name=name, label='target'), self.assertRaises((ValueError, RuntimeError)):
                legacy.reconstruct(source, patch, wrong)

    def test_decoder_refuses_bad_copy_range_opcode_and_output_bound_even_after_resealing(self):
        for name, spec in legacy.SPECS.items():
            source = read_file(ROOT / spec[0], legacy.MAX_SOURCE)
            patch = bytearray(read_file(ROOT / spec[1], legacy.MAX_DELTA))
            self.assertEqual(patch[13], 0)
            invalid = bytearray(patch); struct.pack_into('<I', invalid, 14, len(source) + 1)
            with self.subTest(name=name, label='range'), self.assertRaises((ValueError, RuntimeError)):
                legacy._decode(source, bytes(invalid), spec[4])
            invalid = bytearray(patch); invalid[13] = 9
            with self.subTest(name=name, label='opcode'), self.assertRaises((ValueError, RuntimeError)):
                legacy._decode(source, bytes(invalid), spec[4])
            with self.subTest(name=name, label='output'), self.assertRaises((ValueError, RuntimeError)):
                legacy._decode(source, bytes(patch), spec[4] - 1)

    def test_e3_and_cdd_components_keep_separate_exact_package_origins(self):
        from tools import rust_thread_diagnostic_package as old, rust_thread_runtime_package as current
        self.assertEqual((old.SOURCE, old.RUN), ('e3f0edf822c10e84bbeede276174ac3217542afc', 41189829966))
        self.assertEqual((current.SOURCE, current.RUN, current.EVENT),
                         ('cddfb5d016a6311ed0db4673e490dc9caad917dd', 41229829427, 'push'))
        old_core = legacy.read_legacy('original-core')
        old_component = legacy.read_legacy('normal-component')
        core_spec, component_spec = legacy.SPECS['original-core'], legacy.SPECS['normal-component']
        new_core = read_file(ROOT / core_spec[0], legacy.MAX_SOURCE)
        new_component = read_file(ROOT / component_spec[0], legacy.MAX_SOURCE)
        for package, core, component in ((old, old_core, old_component), (current, new_core, new_component)):
            wrapped = package.wrap_original(core, component)
            self.assertEqual(len(wrapped), package.WRAPPED['bytes'])
            self.assertEqual('sha256:' + hashlib.sha256(wrapped).hexdigest(), package.WRAPPED['sha256'])
        for package, core, component in ((old, new_core, new_component), (current, old_core, old_component),
                                         (old, old_core, new_component), (current, new_core, old_component)):
            with self.subTest(source=package.SOURCE, core=len(core), component=len(component)), \
                    self.assertRaises((ValueError, RuntimeError)):
                package.wrap_original(core, component)
        programme = (ROOT / 'tools/diagnose_rust_thread_fault.py').read_text()
        self.assertIn("('default-cdd', ())", programme)
        self.assertIn("('diagnostic-e3', ('--features', 'rust-thread-diagnostic-legacy'))", programme)
        self.assertIn("exact_list(stages.run(stage + '-list'", programme)
        self.assertIn("exact_result(stages.run(stage + '-run'", programme)

    def test_retained_package_material_binds_the_exact_e3_component_origin(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from tools import rust_thread_diagnostic_package as package
        from tools.rust_capsule_project import digest
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / 'source-inputs.json').write_bytes(b'source')
            (output / 'qualification-projection.json').write_bytes(b'projection')
            files = {'rust-toolchain.toml': b'toolchain', 'Cargo.lock': b'lock'}
            rows = package.retained_assembly_materials(output, b'recipe', files, b'package', b'compiler')
            self.assertEqual(len(rows), 8)
            origin = legacy.read_legacy('origin')
            expected = {'name': 'normal-component-origin', 'digest': digest(origin), 'size': len(origin)}
            self.assertEqual([row for row in rows if row['name'] == expected['name']], [expected])
            evidence = json.loads(origin)
            component = legacy.read_legacy('normal-component')
            original = legacy.read_legacy('original-core')
            self.assertEqual(evidence['normalComponentEnvelope']['componentDigest'], digest(component))
            self.assertEqual(evidence['normalComponentEnvelope']['componentBytes'], len(component))
            self.assertEqual(evidence['currentSourceObservation']['rawCore'],
                             {'bytes': len(original), 'digest': digest(original)})
            self.assertEqual(digest(component), package.COMPONENT_SHA)
            self.assertEqual(digest(original), 'sha256:' + package.PINS['raw-core.wasm'][1])
            actual_read = legacy.read_file
            origin_delta = ROOT / legacy.SPECS['origin'][1]
            def altered(path, maximum):
                data = actual_read(path, maximum)
                return data[:-1] + bytes([data[-1] ^ 1]) if path == origin_delta else data
            with patch.object(legacy, 'read_file', side_effect=altered):
                with self.assertRaises((ValueError, RuntimeError)):
                    package.retained_assembly_materials(output, b'recipe', files, b'package', b'compiler')

    def test_e3_and_b422_native_readers_keep_distinct_original_control_cohorts(self):
        from tools import rust_thread_diagnostic_native_products as diagnostic, rust_thread_native_products as typescript
        self.assertEqual((diagnostic.SOURCE, diagnostic.RUN, diagnostic.JOB, diagnostic.ARTIFACT['id']),
                         ('e3f0edf822c10e84bbeede276174ac3217542afc', 41190176305, 124505170873, 13038753096))
        self.assertEqual((diagnostic.READER.control_count, diagnostic.READER.command_count), (200, 91))
        self.assertEqual((typescript.SOURCE, typescript.READER.control_count),
                         ('b422af24d86344ac7abb8b8fa56c3782aab63915', 193))
        self.assertEqual(diagnostic.CATALOGUE_PREVIOUS_SOURCE, 'deb654086a6e9ca85c1c96c7e3485babbc6557d9')
        self.assertEqual((diagnostic.CATALOGUE_PREVIOUS_RUN, diagnostic.CATALOGUE_PREVIOUS_ARTIFACT['id']),
                         (41131800734, 13013563430))
        self.assertEqual((diagnostic.PREVIOUS_RUNTIME_SOURCE, diagnostic.PREVIOUS_RUNTIME_RUN),
                         ('9c0097fc4dee24c57e0cffbdf1963e47772b2ffc', 41116286833))
        self.assertEqual((diagnostic.FAILED_RUNTIME_SOURCE, diagnostic.FAILED_RUNTIME_RUN),
                         ('79911762b366381d7dc61da12d1b5e9aba2b3222', 41096399674))
        self.assertNotEqual(diagnostic.ARTIFACT, diagnostic.FAILED_RUNTIME_ARTIFACT)
        workflow = (ROOT / '.github/workflows/rust-thread-fault-diagnostic.yml').read_text()
        self.assertIn('git fetch --no-tags --depth=1 origin ' + diagnostic.SOURCE, workflow)
        self.assertNotIn('git fetch --no-tags --depth=1 origin ' + diagnostic.FAILED_RUNTIME_SOURCE, workflow)
        programme = (ROOT / 'tools/diagnose_rust_thread_fault.py').read_text()
        self.assertIn('original193NodeReused=False, original200NodeReused=False', programme)
        self.assertIn('runtimeQualification=False', programme)

    def test_e3_compiler_rejects_wrong_event_before_archive_or_output(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from tools import rust_thread_diagnostic_compiler_materials as compiler
        from tools.phase2_operator_process import WorkflowError
        for event in ('push', 'pull_request'):
            values = [
                {'id': compiler.RUN, 'head_sha': compiler.SOURCE,
                 'path': '.github/workflows/rust-owned-thread-inputs.yml', 'event': event,
                 'head_branch': 'feat/rust-thread-runtime-20261023', 'status': 'completed', 'conclusion': 'success'},
                {'id': compiler.JOB, 'run_id': compiler.RUN, 'head_sha': compiler.SOURCE,
                 'name': 'Compile exact Rust context utility and owned thread sysroot',
                 'status': 'completed', 'conclusion': 'success'},
            ]
            with self.subTest(event=event), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'uncreated'
                with patch.object(compiler, 'api', side_effect=values) as api:
                    with self.assertRaisesRegex(WorkflowError, 'rust-thread-retained-official-compiler-origin'):
                        compiler.prepare(output)
                    self.assertEqual(api.call_count, 2)
                self.assertFalse(output.exists())
