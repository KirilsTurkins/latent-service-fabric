"""Original published declarations and real capture/retention; no TSC or guest."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from tools.application_dependencies import capture, prepare, verify_inputs
from tools.build_snapshot import canonical
from tools.rust_capsule_project import ROOT, read_file
from tools.typescript_application_dependencies import npm_archive_files
from tools.typescript_guest import standard_global_types as types
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

ARCHIVE = ROOT/'tools/tests/fixtures/npm-types-node-26.6.5.tgz'


class StandardGlobalTypes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = ARCHIVE.read_bytes()
        assert len(raw) == 471079
        assert hashlib.sha256(raw).hexdigest() == 'e4e47dac860469aa5aa79043a6b83396299d9cd6ee23b30fcb2074625ac8dbdf'
        assert 'sha512-'+base64.b64encode(hashlib.sha512(raw).digest()).decode() == 'sha512-uMzsv9stDdofIZBx4UGh4Z9ZgXnGC9seRDscilBcTHAeOFk67MZg/k9bWVfO+bk4qZmG+l52hRnLwUiH2LnJTg=='
        cls.original = npm_archive_files(raw)

    def captured(self, root, change=None):
        source = root/'original'; source.mkdir()
        files = {types.PROVIDER+name:data for name,data in self.original.items()}
        if change: change(files)
        for name,data in files.items():
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        owner=root/'owner';owner.mkdir();(owner/'package.json').write_bytes(b'{}')
        manifest={'formatVersion':1,'language':'typescript','selection':{'target':'wasm32-component',
            'runtimeProfile':IMPORT_PROFILE,'conditions':[]},'nativeLocks':['package.json'],'transformations':[],
            'artifacts':[{'id':'npm-selected/declaration-control','role':'application','format':'directory',
                'mount':'dependencies/npm/node_modules','source':{'path':str(source)},'dependencies':[],
                'metadata':{'ecosystem':'npm','assetType':'selected-node-modules'}}]}
        (owner/'latent.dependencies.json').write_bytes(canonical(manifest)+b'\n')
        selected=capture(owner);(owner/'latent.dependencies.lock.json').write_bytes(canonical(selected)+b'\n')
        work=root/'work';out=root/'receipt';work.mkdir();out.mkdir()
        return owner,prepare(owner,work,out,'typescript')

    def test_published_provider_composes_source_bound_types_without_runtime_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner,closure=self.captured(Path(temporary))
            selected=types.select(closure)
            self.assertEqual(types.select(verify_inputs(owner,'typescript')),selected)
            runtime,clock=read_file(ROOT/types.RUNTIME),read_file(ROOT/types.CLOCK)
            derived_runtime,derived_clock,record=types.compose(selected,runtime,clock)
            self.assertTrue(derived_runtime.startswith(b'/// <reference types="node" />'))
            self.assertIn(b'interface AbortController {',derived_runtime)
            self.assertIn(types.node_variable(selected['content']['web-globals/abortcontroller.d.ts'],'AbortSignal').encode(),derived_runtime)
            self.assertIn(b'import("node:perf_hooks").Performance',derived_clock)
            self.assertIn(b'interface Performance {',derived_clock)
            self.assertEqual(record['originals'],{types.RUNTIME:types.identity(runtime),types.CLOCK:types.identity(clock)})
            for name,data in [('activation-runtime-globals.d.ts',derived_runtime),('clock-runtime-globals.d.ts',derived_clock)]:
                self.assertEqual(record['derived'][name],{**types.identity(data),'text':data.decode()})
            self.assertEqual(len(record['providerFiles']),5)
            self.assertIs(record['runtimeApiChange'],False)
            self.assertEqual(record['qualification'],'unknown')
            self.assertEqual(read_file(ROOT/types.CLOCK),clock)

    def test_default_bytes_and_standalone_iterable_contract_are_unchanged(self):
        runtime,clock=read_file(ROOT/types.RUNTIME),read_file(ROOT/types.CLOCK)
        self.assertEqual(types.compose(None,runtime,clock),(runtime,clock,None))
        self.assertIn(b'any(signals: Iterable<AbortSignal>)',runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);compiled=root/'compiled';out=root/'out';compiled.mkdir();out.mkdir()
            self.assertEqual(types.retain(compiled,out,None),((),[]))
            (compiled/types.RECEIPT).write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'unselected-receipt'):types.retain(compiled,out,None)

    def test_partial_multiple_mutated_and_unreviewed_shapes_fail_explicitly(self):
        changes=(lambda files:files.pop(types.PROVIDER+'web-globals/performance.d.ts'),
                 lambda files:files.update({'other/node_modules/'+types.PROVIDER+'package.json':files[types.PROVIDER+'package.json']}))
        for change in changes:
            with tempfile.TemporaryDirectory() as temporary:
                _owner,closure=self.captured(Path(temporary),change)
                with self.assertRaisesRegex(ValueError,'ambiguous-or-incomplete'):types.select(closure)
        with tempfile.TemporaryDirectory() as temporary:
            _owner,closure=self.captured(Path(temporary));selected=types.select(closure)
            path=closure.work/'dependencies/npm/node_modules'/types.PROVIDER/'web-globals/abortcontroller.d.ts'
            path.write_bytes(path.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'provider-mutated'):types.select(closure)
            runtime,clock=read_file(ROOT/types.RUNTIME),read_file(ROOT/types.CLOCK)
            changed=copy.deepcopy(selected);changed['content']['web-globals/abortcontroller.d.ts']+=b'\n    var AbortSignal: duplicate;'
            with self.assertRaisesRegex(ValueError,'ambiguous-provider-variable'):types.compose(changed,runtime,clock)
            with self.assertRaisesRegex(ValueError,'preimage-drift'):types.compose(selected,runtime.replace(b'declare class AbortController',b'declare class Other'),clock)

    def test_normal_retention_rejects_forgery_and_distributed_recipe_contains_helper(self):
        from tools.dev_tool_distribution import recipe
        from tools.qualify_typescript_buffer_commonjs import standard_type_evidence
        from tools.phase2_operator_process import WorkflowError
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);owner,closure=self.captured(root)
            _runtime,_clock,expected=types.compose(types.select(closure),read_file(ROOT/types.RUNTIME),read_file(ROOT/types.CLOCK))
            compiled=root/'compiled';out=root/'out';compiled.mkdir();out.mkdir()
            raw=canonical(expected)+b'\n';(compiled/types.RECEIPT).write_bytes(raw)
            # Failed attempts retain the same unknown selection before promotion.
            (out/types.RECEIPT).write_bytes(raw)
            assets,materials=types.retain(compiled,out,expected)
            self.assertEqual(assets[0][0],types.RECEIPT)
            self.assertEqual(materials,[{'name':'typescript-standard-global-types',**types.identity(raw)}])
            (out/'bindings.json').write_bytes(canonical({'files':[
                {'path':name,'sha256':value['digest'],'bytes':value['size']}
                for name,value in expected['derived'].items()]}))
            (out/'build-observation.json').write_bytes(canonical({'materials':materials}))
            (out/'package-source.json').write_bytes(canonical({'layers':[
                {'path':types.RECEIPT,'source':types.RECEIPT,'role':'asset',
                 'mediaType':'application/vnd.latent.typescript.standard-global-types.v1+json'}]}))
            standard_type_evidence(out,owner)
            bindings=json.loads((out/'bindings.json').read_bytes())
            bindings['files'][0]['bytes']=float(bindings['files'][0]['bytes'])
            (out/'bindings.json').write_bytes(canonical(bindings))
            with self.assertRaisesRegex(WorkflowError,'actual-generated-standard-type-view'):
                standard_type_evidence(out,owner)
            for field,value in [('runtimeApiChange',0),('qualification','passed')]:
                changed=dict(expected,**{field:value});(compiled/types.RECEIPT).write_bytes(canonical(changed))
                with self.subTest(field=field),self.assertRaisesRegex(ValueError,'retained-selection-drift'):
                    types.retain(compiled,out,expected)
            payload=root/'payload';payload.mkdir();recipe(payload,'typescript')
            self.assertEqual((payload/'recipe/tools/typescript_guest/standard_global_types.py').read_bytes(),read_file(ROOT/'tools/typescript_guest/standard_global_types.py'))


if __name__=='__main__':unittest.main()
