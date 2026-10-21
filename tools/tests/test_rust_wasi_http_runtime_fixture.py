"""Controlled source/capture fences for the ordinary-client owning campaign."""
import copy
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import rust_wasi_http_runtime_fixture as fixture
from tools.rust_capsule_build import validate_project
from tools.rust_capsule_project import canonical, read_file, read_json, snapshot


class OrdinaryCapturedClients(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.app,self.outside,self.specs=fixture.prepare(self.root/'source','0123456789abcdef')

    def test_two_varied_unregistered_crates_use_the_identical_ordinary_source(self):
        self.assertNotEqual(self.specs,fixture.specification('fedcba9876543210'))
        self.assertEqual(len({s['package'] for s in self.specs}),2)
        for source,spec in zip(self.outside,self.specs):
            manifest=tomllib.loads(read_file(source/'Cargo.toml').decode())
            self.assertEqual(manifest['package']['name'],spec['package'])
            self.assertEqual(manifest['package']['version'],spec['version'])
            self.assertEqual(manifest['dependencies']['waki'],{'version':'=0.5.1','features':['json']})
            self.assertEqual(manifest['dependencies']['golem-wasi-http'],{'version':'=0.2.0','features':['json']})
            self.assertEqual(read_file(source/'src/lib.rs'),fixture.LIBRARY.encode())
        for text in ('waki::Client::new()', 'golem_wasi_http::Client::new()',
            'response.json::<serde_json::Value>()','response.error_for_status_ref()',
            'response.chunk(4)', 'response.read(&mut bytes)', 'response.bytes()', 'response.body()'):
            self.assertIn(text,fixture.LIBRARY)
        for prohibited in ('latent_guest', 'Transport', 'Executor', 'wasip2::', 'bindings::', 'unsafe'):
            self.assertNotIn(prohibited,fixture.LIBRARY)

    def test_original_sync_contract_and_selected_authority_remain_exact(self):
        project,_pins=validate_project(snapshot(self.app))
        self.assertEqual(project['name'],fixture.SERVICE)
        self.assertEqual(project['tenant'],'examples')
        self.assertEqual(project['limits']['memoryBytes'],16777216)
        self.assertEqual(project['limits']['cpuFuel'],1000000000)
        self.assertEqual(project['limits']['wallTimeLimitMillis'],5000)
        self.assertEqual(project['limits']['outboundRequests'],8)
        self.assertEqual(project['limits']['logBytes'],0)
        # The normal, unselected template remains synchronous. The separately
        # selected HTTP fixture now declares its blocking effect explicitly.
        normal=fixture.create(self.root/'unselected','greeting')
        world=read_file(normal/'wit/world.wit').decode()
        self.assertIn('greet: func(name: string) -> result<string, string>;',world)
        self.assertNotIn('async func',world)
        selected_world=read_file(self.app/'wit/world.wit').decode()
        declarations=[line.strip().removeprefix('import ').removesuffix(';') for line in selected_world.splitlines()
            if line.strip().startswith('import ')]
        self.assertEqual(set(declarations),fixture.AUTHORITY)
        self.assertEqual(len(declarations),3)
        self.assertNotIn('http-runtime',read_file(self.app/'sdk-lock.json').decode())
        code=read_file(self.app/'src/lib.rs').decode()
        original='wit_bindgen::generate!({path: "wit", world: "service"});'
        self.assertNotIn(original,code)
        self.assertEqual(code.count('with: {'),1)
        for capability in declarations:
            self.assertEqual(code.count('"'+capability+'": generate'),1)
        self.assertNotIn('generate_all',code)

    def test_explicit_async_effect_keeps_ordinary_sync_rust_and_exact_macro_override(self):
        world=read_file(self.app/'wit/world.wit').decode()
        self.assertEqual(world.count('greet: async func(name: string) -> result<string, string>;'),1)
        code=read_file(self.app/'src/lib.rs').decode()
        self.assertIn('world: "service", async: false, with:',code)
        self.assertIn('fn greet(',code)
        self.assertNotIn('async fn',code)
        self.assertNotIn('.await',code)
        self.assertEqual(len(self.specs),2)
        for library in self.outside:
            self.assertEqual(read_file(library/'src/lib.rs'),fixture.LIBRARY.encode())

    def test_nonce_rejects_unbounded_or_path_like_coordinates_before_output(self):
        for value in ('../other','0'*15,'0'*17,'A'*16,True,None):
            with self.subTest(value=value),self.assertRaises(Exception):
                fixture.prepare(self.root/'must-not-exist',value)
            self.assertFalse((self.root/'must-not-exist').exists())

    def lock(self):
        rows=[{'id':'outside-'+s['alias'],'role':'application','metadata':{
            'package':s['package'],'version':s['version']}} for s in self.specs]
        for (package,version),checksum in fixture.original.CLIENTS.items():
            rows.append({'id':package,'role':'application','original':{'kind':'controlled'},'metadata':{
                'package':package,'version':version,'vendorChecksum':{'package':checksum},
                'sdkCompilerInput':False,'features':['json']}})
        rows += [{'id':str(i),'role':'build-tool','metadata':{
            'package':'waki-macros' if i==0 else 'public-build-'+str(i)}} for i in range(15)]
        return {'artifacts':rows}

    def captured(self,lock):
        def resolve(app,candidate,**_kwargs):
            candidate.write_bytes(canonical(lock));return lock
        def reviewed(app,candidate,_identity):
            (app/fixture.LOCK).write_bytes(read_file(candidate))
        with patch.object(fixture.authoring,'author'),patch.object(fixture.native,'resolve',side_effect=resolve), \
            patch.object(fixture.review,'review',side_effect=reviewed), \
            patch.object(fixture.review,'status',return_value={'status':'verified'}):
            return fixture.capture(self.app,self.outside,self.specs,Path('controlled-cargo'))

    def test_capture_preserves_exact_published_code_review_and_removes_originals(self):
        lock=self.lock()
        lock['artifacts'][4]['metadata']['executableKinds']=[['proc-macro']]
        lock['artifacts'].append({'id':'json-build-script','role':'build-tool','metadata':{
            'package':'serde_json','version':'1.0.149','executableKinds':[['custom-build']],
            'vendorChecksum':{'package':'83fc039473c5595ace860d8c4fafa220ff474b3fc6bfdb4293327f1a37e94d86'}}})
        # The previous fifteen-row non-JSON fixture must now be RED before any
        # source removal. The sixteen-row ordinary JSON graph alone proceeds.
        previous=copy.deepcopy(lock);previous['artifacts'].pop()
        with self.assertRaisesRegex(Exception,'exact-captured-executable-closure'):
            self.captured(previous)
        self.assertTrue(all(p.exists() for p in self.outside))
        result=self.captured(lock)
        self.assertTrue(result['originalLibrariesRemoved'])
        self.assertFalse(result['implicitExecutableApproval'])
        self.assertFalse(result['applicationTransportInjected'])
        self.assertFalse(result['libraryCodePatched'])
        self.assertEqual(len(result['executableInputs']),16)
        self.assertEqual(result['developerCrates'],self.specs)
        self.assertEqual(read_json(self.app/fixture.LOCK),lock)
        self.assertFalse(any(p.exists() for p in self.outside))

    def test_substituted_published_bytes_features_or_executable_closure_refuse_before_removal(self):
        for choice in ('checksum','json-feature','executable','unseen'):
            with self.subTest(choice=choice):
                lock=copy.deepcopy(self.lock())
                lock['artifacts'][4]['metadata']['executableKinds']=[['proc-macro']]
                lock['artifacts'].append({'id':'json-build-script','role':'build-tool','metadata':{
                    'package':'serde_json','version':'1.0.149','executableKinds':[['custom-build']]}})
                if choice=='checksum':lock['artifacts'][2]['metadata']['vendorChecksum']['package']='0'*64
                if choice=='json-feature':lock['artifacts'][2]['metadata']['features']=[]
                if choice=='executable':lock['artifacts'].pop()
                if choice=='unseen':lock['artifacts'].pop(0)
                with self.assertRaises(Exception):self.captured(lock)
                self.assertTrue(all(p.exists() for p in self.outside))


if __name__=='__main__':unittest.main()
