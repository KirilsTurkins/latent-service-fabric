import copy
from pathlib import Path
import tempfile
import tomllib
import unittest

from tools import rust_wasi_http_fixture as fixture
from tools import qualify_rust_wasi_http_inputs as control
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_build import validate_project
from tools.rust_capsule_project import canonical, digest, read_json, snapshot, write_json


class RustWasiHttpInputs(unittest.TestCase):
    def test_normal_project_keeps_the_closed_default_profile_and_unchanged_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            app, outside, spec = fixture.prepare(Path(directory) / 'owned', '1234567890abcdef')
            files = snapshot(app)
            project, sdk = validate_project(files)
            self.assertNotIn('runtimeProfile', project)
            self.assertEqual(project['world'], 'examples:greeting/service@1.0.0')
            self.assertEqual(read_json(app / 'sdk-lock.json'), sdk)
            self.assertEqual(set(snapshot(outside)), {'Cargo.toml', 'src/lib.rs'})
            package = tomllib.loads((outside / 'Cargo.toml').read_text())
            self.assertEqual(package['package']['name'], spec['package'])
            self.assertEqual(package['dependencies'], {'waki': '=0.5.1', 'golem-wasi-http': '=0.2.0'})
            self.assertNotIn(spec['package'].encode(), b''.join(raw for name, raw in files.items()
                if name.startswith('vendor/') or name == 'sdk-lock.json'))

    def test_developer_coordinates_vary_without_changing_either_published_client(self):
        first = fixture.specification('0000000000000000')
        second = fixture.specification('abcdef0123456789')
        self.assertNotEqual(first['package'], second['package'])
        self.assertNotEqual(first['version'], second['version'])
        for nonce in (True, None, '../outside', 'A'*16, '0'*15, '0'*17):
            with self.subTest(nonce=nonce), self.assertRaises(WorkflowError):
                fixture.specification(nonce)

    def captured(self):
        return {'artifacts': [{'id': name+'/'+version+'/captured', 'role': 'application',
            'original': {'digest': 'sha256:'+'1'*64, 'size': 123},
            'metadata': {'package': name, 'version': version, 'sdkCompilerInput': False,
                'vendorChecksum': {'package': checksum}, 'features': []}}
            for (name, version), checksum in fixture.CLIENTS.items()]}

    def test_published_source_identity_requires_both_exact_checksums_without_sdk_exemption(self):
        lock = self.captured()
        self.assertEqual([row['package'] for row in fixture.captured_clients(lock)], ['waki', 'golem-wasi-http'])
        mutations = []
        missing = copy.deepcopy(lock); missing['artifacts'].pop(); mutations.append(missing)
        duplicate = copy.deepcopy(lock); duplicate['artifacts'].append(copy.deepcopy(duplicate['artifacts'][0])); mutations.append(duplicate)
        changed = copy.deepcopy(lock); changed['artifacts'][0]['metadata']['vendorChecksum']['package'] = '0'*64; mutations.append(changed)
        exempt = copy.deepcopy(lock); exempt['artifacts'][0]['metadata']['sdkCompilerInput'] = True; mutations.append(exempt)
        role = copy.deepcopy(lock); role['artifacts'][0]['role'] = 'compiler'; mutations.append(role)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                fixture.captured_clients(value)


def integer(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128); value >>= 7
    result.append(value)
    return bytes(result)


def text(value):
    raw = value.encode()
    return integer(len(raw)) + raw


def section(kind, raw):
    return bytes([kind]) + integer(len(raw)) + raw


class ActualImportReader(unittest.TestCase):
    def core(self):
        item = text('wasi:http/types@0.2.2') + text('[constructor]request-options') + b'\0\0'
        return control.CORE + section(1, b'\x01\x60\0\0') + section(2, b'\x01' + item)

    def test_import_reader_binds_exact_original_core_and_nested_component_without_reachability_claim(self):
        core = self.core()
        expected = [{'coreDigest': digest(core), 'coreBytes': len(core), 'imports': [{
            'module': 'wasi:http/types@0.2.2', 'name': '[constructor]request-options', 'kind': 0, 'typeIndex': 0}]}]
        self.assertEqual(control.core_imports(core), expected)
        self.assertEqual(control.core_imports(control.COMPONENT + section(1, core)), expected)
        self.assertEqual(control.core_imports(control.COMPONENT + section(4,
            control.COMPONENT + section(1, core))), expected)
        self.assertEqual(control.core_imports(control.CORE + section(0, text('wasi:http/fake@0.2.2')))[0]['imports'], [])

    def test_truncated_unknown_duplicate_and_excessive_import_encodings_refuse(self):
        import_section = section(2, b'\x01' + text('wasi:http/types@0.2.2') + text('x') + b'\0\0')
        excessive = section(2, integer(4097))
        for raw in (b'not wasm', self.core()[:-1], self.core() + import_section,
                    control.CORE + excessive, control.CORE + section(2, b'\x01'+text('x')+text('y')+b'\xff'),
                    control.COMPONENT + section(13, b'')):
            with self.subTest(raw=raw), self.assertRaises((ValueError, WorkflowError)):
                control.core_imports(raw)


class ExecutableInputBoundary(unittest.TestCase):
    def test_exact_captured_closure_identity_and_isolation_are_required_before_test_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); denied=root/'denied'; app=root/'app'; denied.mkdir(); app.mkdir()
            tool={'id':'ordinary-proc-macro/1.0.0/captured','role':'build-tool'}
            write_json(app/'latent.dependencies.lock.json',{'artifacts':[tool]})
            write_json(denied/'BUILD-FAILED.json',{'stage':'executable-input-approval','commands':[]})
            spec={'executableInputs':[tool],'network':'denied','ambientHome':'absent',
                'credentials':'not-inherited','isolationProfile':'linux-captured-compiler-namespaces-v1'}
            value={'formatVersion':1,'specification':spec,'identity':digest(canonical(spec))}
            target=denied/'executable-input-approval-request.json';write_json(target,value)
            self.assertEqual(control.execution_request(denied,app),value)
            for changed in ({**value,'identity':'sha256:'+'0'*64},
                {'formatVersion':1,'specification':{**spec,'network':'allowed'},
                 'identity':digest(canonical({**spec,'network':'allowed'}))},
                {'formatVersion':1,'specification':{**spec,'executableInputs':[]},
                 'identity':digest(canonical({**spec,'executableInputs':[]}))}):
                target.write_bytes(canonical(changed))
                with self.assertRaises(WorkflowError):control.execution_request(denied,app)
            target.write_bytes(canonical(value))
            (denied/'BUILD-FAILED.json').write_bytes(canonical({'stage':'compile','commands':[{'stage':'compile'}]}))
            with self.assertRaises(WorkflowError):control.execution_request(denied,app)


if __name__ == '__main__':
    unittest.main()
