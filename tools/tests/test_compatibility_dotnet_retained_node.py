"""Pure fixed-reader source/byte boundary controls; no .NET or runtime qualification."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import compatibility_dotnet_retained_node as retained, guest_api_analysis as api
from tools.dev_workflow.common import digest
from tools.rust_capsule_project import inventory
WIT_BYTES = {'wit/world.wit': b'package examples:greeting@1.0.0;\n\ninterface api {\n    greet: func(name: string) -> result<string, string>;\n}\n\nworld service {\n    import latent:clock/monotonic@0.1.0;\n    export api;\n}\n', 'wit/deps/clock/package.wit': b'package latent:clock@0.1.0;\n\ninterface monotonic {\n    now-nanos: func() -> u64;\n}\n\ninterface wall {\n    now-unix-millis: func() -> u64;\n}\n'}

class RetainedDotnetSourceBoundaries(unittest.TestCase):
    def test_inventory_relation_never_accepts_extra_changed_or_cross_typed_capture_rows(self):
        left={f'vendor/library-{n}':{'digest':digest(str(n).encode()),'size':n} for n in range(157)}
        left['src/Main.cs']=copy.deepcopy(retained.MAIN['baseline'])
        right=copy.deepcopy(left);right['src/Main.cs']=copy.deepcopy(retained.MAIN['reached'])
        original=copy.deepcopy((left,right))
        self.assertEqual(retained._inventory_pair(left,right),
            {'rawSourceWorkspaceReconstructed':False,'nonMainRowsUnchanged':157})
        self.assertEqual((left,right),original)
        for mode in ('main','library','path','bool','row'):
            bad=copy.deepcopy(right)
            if mode=='main':bad['src/Main.cs']=copy.deepcopy(retained.MAIN['baseline'])
            if mode=='library':bad['vendor/library-0']['digest']=digest(b'foreign library')
            if mode=='path':bad['extra']={'digest':digest(b'extra'),'size':5}
            if mode=='bool':bad['vendor/library-0']['size']=False
            if mode=='row':bad['vendor/library-0']=None
            with self.subTest(mode=mode),self.assertRaises(ValueError):retained._inventory_pair(left,bad)

    def test_actual_source_layers_are_required_and_normalized_capsule_cannot_replace_original_bytes(self):
        bodies={**WIT_BYTES,'capsule.json':b'original source capsule bytes',
            'component.wasm':b'unit component','compatibility-report.json':b'{}','contracts.json':b'{}',
            'package-source.json':b'{}','wit-lock.json':b'{}'}
        expected={name:{'digest':digest(raw),'size':len(raw)} for name,raw in bodies.items()}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name,raw in bodies.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            retained.verify_package_sources(root,expected)
            (root/'capsule.json').write_bytes(b'normalized package capsule bytes')
            with self.assertRaisesRegex(ValueError,'package-source-changed'):
                retained.verify_package_sources(root,expected)
            (root/'capsule.json').write_bytes(bodies['capsule.json'])
            (root/'wit/world.wit').unlink()
            with self.assertRaises(OSError):retained.verify_package_sources(root,expected)

    def test_ordinary_raw_source_entry_still_rejects_hash_pretence_and_changed_libraries_before_shared_join(self):
        before={'src/Main.cs':b'if (false) { // lsf-api-root-edge\n return 42; }',
                'library.dll':b'original captured bytes'}
        after={**before,'src/Main.cs':before['src/Main.cs'].replace(b'if (false)',b'if (true)',1)}
        left={'compilerDigest':digest(b'compiler'),'recipeDigest':digest(b'recipe'),'graphDigest':digest(b'graph'),
              'componentDigest':digest(b'negative'),'sourceDigest':digest(inventory(before))}
        right={**left,'componentDigest':digest(b'positive'),'sourceDigest':digest(inventory(after))}
        # Isolate existing raw-byte entry from separately validated CIL semantics;
        # this control never treats a mocked common join as qualification.
        with patch('tools.dotnet_guest.reachability.validate'),patch.object(api,'_dotnet_callee_join') as join:
            api.dotnet_retention_pair(left,right,before,after,'src/Main.cs');join.assert_called_once_with(left,right)
            join.reset_mock();bad={**after,'library.dll':b'changed capture'}
            with self.assertRaisesRegex(ValueError,'only-root-edge'):
                api.dotnet_retention_pair(left,right,before,bad,'src/Main.cs')
            join.assert_not_called()
            with self.assertRaisesRegex(ValueError,'pair-inputs'):
                api.dotnet_retention_pair(left,right,{'src/Main.cs':retained.MAIN['baseline']},
                    {'src/Main.cs':retained.MAIN['reached']},'src/Main.cs')
            join.assert_not_called()

if __name__=='__main__':unittest.main()
