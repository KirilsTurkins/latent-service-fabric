"""Prepared artifact fences; no compiler, network, or component execution."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import rust_wasi_http_inputs as inputs


STAGES = ('runtime-rustc-version', 'runtime-cargo-version', 'runtime-wasm-tools-version',
    'component-composer-version', 'standard-http-runtime-compile',
    'standard-http-runtime-component', 'standard-http-runtime-validate',
    'standard-http-reference-wit', 'standard-http-adapter-wit')


class PreparedArtifactFences(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.rustc, self.wasm, self.cargo = (self.directory / name
            for name in ('rustc', 'wasm-tools', 'cargo'))
        for path in (self.rustc, self.wasm, self.cargo):
            path.write_bytes(path.name.encode())
        self.composer = self.directory / 'component-composer/wac'
        self.composer.parent.mkdir()
        self.composer.write_bytes(b'pinned-verifier-test-seam')
        self.raw = b'\0asm\x01\0\0\0'
        self.adapter = b'\0asm\x0d\0\x01\0' + b'\x01\x08' + self.raw
        for name, body in {'raw-runtime.wasm': self.raw, inputs.ADAPTER: self.adapter,
                'reference.wit.json': b'{}', 'adapter.wit.json': b'{}'}.items():
            (self.directory / name).write_bytes(body)
        self.source = {'controlled-source.rs': b'original source'}
        source = inputs.inventory(self.source)
        (self.directory / 'source-inputs.json').write_bytes(source)
        self.graph = {'imports': sorted(inputs.profile.AUTHORITY),
            'exports': sorted(inputs.profile.EXTERNAL | {inputs.profile.RETIREMENT}),
            'wholeOriginalTypesCompared': True, 'exactCallingConventions': True}
        self.value = {'schemaVersion': inputs.SCHEMA, 'profile': inputs.profile.PROFILE,
            'target': inputs.TARGET, 'rust': inputs.RUST, 'rustCommit': inputs.RUST_COMMIT,
            'wasmTools': '1.254.0', 'sourceDigest': inputs.digest(source), 'sourceRows': 1,
            'tools': {name: inputs._identity(path, name) for name, path in (
                ('rustc', self.rustc), ('cargo', self.cargo), ('wasm-tools', self.wasm),
                ('component-composer', self.composer))},
            'files': {name: inputs._identity(self.directory / name, name) for name in inputs.FILES},
            'composerSelection': {'pinned-asset-verifier': 'separate-boundary'},
            'graphValidation': self.graph,
            'cores': [{'digest': inputs.digest(self.raw), 'size': len(self.raw)}],
            'commands': [{'stage': stage, 'exitCode': 0, 'seconds': 0.01} for stage in STAGES],
            'qualification': 'compiled-adapter-only', 'authority': 'none',
            'signedQualification': False, 'publisherAuthentication': False, 'hermetic': False}
        self.write_receipt()
        # Existing pinned-composer and full WIT validators have separate real
        # controls. Here their verified outputs isolate mutable receipt fences.
        for target, options in (
                ('source_files', {'return_value': self.source}),
                ('composer.observed', {'return_value': self.composer}),
                ('composer.selection', {'return_value': self.value['composerSelection']}),
                ('profile.validate_adapter', {'return_value': self.graph})):
            mocked = patch('tools.rust_wasi_http_inputs.' + target, **options)
            self.addCleanup(mocked.stop)
            mocked.start()

    def write_receipt(self):
        value = {key: item for key, item in self.value.items() if key != 'identity'}
        value['identity'] = inputs.digest(inputs.canonical(value))
        self.value = value
        self.receipt = inputs.canonical(value)
        (self.directory / inputs.RECEIPT).write_bytes(self.receipt)

    def prepared(self):
        return inputs.Prepared(self.directory, self.rustc, self.wasm)

    def test_prepared_material_is_the_original_receipt_and_never_authority(self):
        value = self.prepared()
        self.assertEqual(value.material(), self.receipt)
        self.assertEqual(value.adapter, self.directory / inputs.ADAPTER)
        self.assertEqual(value.composer, self.composer)
        self.assertFalse(value.value['signedQualification'])
        self.assertFalse(value.value['publisherAuthentication'])
        self.assertEqual(value.value['authority'], 'none')

    def test_changed_component_or_selected_tool_is_rejected(self):
        for path in (self.directory / inputs.ADAPTER, self.rustc, self.wasm):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                with self.assertRaisesRegex(ValueError, 'prepared-(?:tool|file)-drift'):
                    self.prepared()
                path.write_bytes(original)

    def test_source_or_wit_inspection_swap_is_rejected(self):
        with patch.object(inputs, 'source_files', return_value={'controlled-source.rs': b'changed'}):
            with self.assertRaisesRegex(ValueError, 'prepared-source-drift'):
                self.prepared()
        (self.directory / 'adapter.wit.json').write_bytes(b'{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'prepared-file-drift'):
            self.prepared()

    def test_rehashed_wrong_flags_commands_or_receipt_fields_do_not_qualify(self):
        original = copy.deepcopy(self.value)
        mutations = [lambda d: d.update(signedQualification=True),
            lambda d: d.update(publisherAuthentication=True),
            lambda d: d.update(hermetic=True), lambda d: d.update(sourceRows=True),
            lambda d: d.update(extra='unreviewed'),
            lambda d: d['commands'].__setitem__(0, {}),
            lambda d: d['commands'][0].update(exitCode=False),
            lambda d: d['commands'].reverse()]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.value = copy.deepcopy(original)
                mutate(self.value)
                self.write_receipt()
                with self.assertRaises(ValueError):
                    self.prepared()

    def test_altered_receipt_after_selection_and_failed_install_remain_refused(self):
        selected = self.prepared()
        self.value['commands'][0]['seconds'] = 0.02
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, 'prepared-receipt-mutated'):
            selected.check()
        (self.directory / 'INSTALL-FAILED.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'prepared-directory'):
            self.prepared()

    def test_rehashed_altered_core_cannot_borrow_the_original_core_receipt(self):
        changed = b'\0asm\x01\0\0\0\0\x01\0'
        (self.directory / inputs.ADAPTER).write_bytes(
            b'\0asm\x0d\0\x01\0' + b'\x01' + bytes([len(changed)]) + changed)
        self.value['files'][inputs.ADAPTER] = inputs._identity(self.directory / inputs.ADAPTER, inputs.ADAPTER)
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, 'prepared-core-drift'):
            self.prepared()


class InstallerPlatformBoundary(unittest.TestCase):
    def test_selected_source_closure_captures_runtime_shared_owners_and_producer(self):
        files = inputs.source_files()
        required = {*inputs.SHARED, *inputs.RECIPE,
            'sdk/wasi-http-runtime/request_options.rs', 'sdk/wasi-http-runtime/fields.rs',
            'sdk/wasi-http-runtime/io.rs', 'sdk/wasi-http-runtime/state.rs',
            'sdk/wasi-http-runtime/wit/deps/http.wit',
            'sdk/wasi-http-runtime/upstream-source.json'}
        self.assertTrue(required <= files.keys())
        self.assertEqual(len(inputs.profile.validate_assets()), 12)
        self.assertLessEqual(sum(map(len, files.values())), inputs.MAX_SOURCE)

    def test_consumer_only_change_is_bound_by_guest_recipe_not_adapter_producer(self):
        files = inputs.consumer_files()
        producer = inputs.source_files()
        self.assertEqual(set(files) - set(producer), set(inputs.CONSUMER_RECIPE))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, body in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            composition = root / 'tools/rust_wasi_http_compose.py'
            composition.write_bytes(composition.read_bytes() + b'\n# controlled consumer delta\n')
            self.assertEqual(inputs.source_files(root), producer)
            self.assertNotEqual(inputs.consumer_files(root), files)
            self.assertFalse(set(inputs.CONSUMER_RECIPE) & set(producer))

    def test_non_linux_refuses_before_creating_output_or_running_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'must-remain-absent'
            with patch.object(inputs.sys, 'platform', 'win32'), patch.object(inputs, 'source_files') as source:
                with self.assertRaisesRegex(ValueError, 'installer-linux'):
                    inputs.install(output)
                source.assert_not_called()
            self.assertFalse(output.exists())

    def test_exact_compiler_commit_and_recognized_versions_are_required(self):
        rust = ('rustc 1.97.1 (' + inputs.RUST_COMMIT[:9] + ' 2026-10-10)\n'
            'binary: rustc\ncommit-hash: ' + inputs.RUST_COMMIT
            + '\nhost: x86_64-unknown-linux-gnu\nrelease: 1.97.1\n').encode()
        tools = {name: Path(name) for name in ('rustc', 'cargo', 'wasm-tools')}
        for cargo in (b'cargo 1.97.1', b'cargo 1.97.1 (123456789 2026-10-10)'):
            for wasm in inputs.WASM_REPORTS:
                inputs._versions(Mock(run=Mock(side_effect=[rust, cargo, wasm])), tools)
        cases = [(rust.replace(inputs.RUST_COMMIT.encode(), b'0' * 40), b'cargo 1.97.1', b'wasm-tools 1.254.0'),
            (rust + b'release: 1.97.1\n', b'cargo 1.97.1', b'wasm-tools 1.254.0'),
            (rust, b'cargo 1.97.1 arbitrary', b'wasm-tools 1.254.0'),
            (rust, b'cargo 1.97.1', b'wasm-tools 1.254.0 arbitrary'),
            (rust, b'cargo 1.97.1', b'wasm-tools 1.254.0 (bad000000 2026-07-20)'),
            (rust, b'cargo 1.97.1', b'wasm-tools 1.255.0 (bb58fdf91 2026-07-20)')]
        for versions in cases:
            with self.subTest(versions=versions), self.assertRaises(ValueError):
                inputs._versions(Mock(run=Mock(side_effect=versions)), tools)


if __name__ == '__main__':
    unittest.main()
