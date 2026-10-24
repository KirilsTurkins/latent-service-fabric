"""Actual bounded file-retention controls; never compile or execute a component."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools.java_guest import fiber_component_inputs as capture
from tools.rust_capsule_project import ROOT, digest


class NormalFiberComponentInputs(unittest.TestCase):
    def populate(self, root):
        java=(ROOT/'sdk/java-guest/fibers/conformance/Capsule.java').read_bytes()
        wit=(ROOT/'sdk/java-guest/fibers/conformance/service.wit').read_bytes()
        for name, raw in {'src/Capsule.java':java,'build/project/src/main/java/Capsule.java':java,
                'wit/service.wit':wit,'build/wit/service.wit':wit}.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        raw={'core.wasm':b'\0asm\x01\0\0\0explicit-public-core-data',
             'closed-runtime.wasm':b'\0asm\x01\0\0\0explicit-public-adapter-data'}
        for name, value in raw.items():(root/'build'/name).write_bytes(value)
        return raw

    def test_fixed_normal_public_sources_and_only_failed_assembly_pair_are_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();raw=self.populate(root)
            compiler=SimpleNamespace(records=[{'stage':'component-new','exitCode':1}])
            capture.retain(compiler,root)
            target=root/'build/component-inputs';record=json.loads((target/'record.json').read_bytes())
            self.assertEqual(record['schemaVersion'],'latent.java.public-fixture-component-inputs.v1')
            self.assertFalse(record['qualification']);self.assertFalse(record['compilerAcceptanceChanged'])
            self.assertTrue(record['normalPublicFiberOnly']);self.assertTrue(record['publicFixtureOnly'])
            self.assertEqual(record['fixtureSourceDigest'],digest((root/'src/Capsule.java').read_bytes()))
            self.assertEqual(record['fixtureWitDigest'],digest((root/'wit/service.wit').read_bytes()))
            self.assertEqual(record['limits'],{'core.wasm':64*1024*1024,'closed-runtime.wasm':4*1024*1024})
            self.assertEqual(record['logLimitBytesUnchanged'],16*1024*1024)
            self.assertEqual(set(path.name for path in target.iterdir()),{*raw,'record.json'})
            for name,value in raw.items():
                self.assertEqual((target/name).read_bytes(),value)
                self.assertEqual((root/'build'/name).read_bytes(),value)
                self.assertEqual(record['inputs'][name],{'sha256':digest(value),'bytes':len(value)})
            self.assertEqual(compiler.records,[{'stage':'component-new','exitCode':1}])

    def test_other_stages_changed_sources_unsafe_pairs_and_capture_failures_preserve_original_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            with patch.object(capture.paths,'read',side_effect=AssertionError('must not read unselected inputs')):
                for records in ([],[{'stage':'c-to-wasm','exitCode':1}],
                        [{'stage':'component-new','exitCode':0}], [{'stage':'component-new','exitCode':True}]):
                    capture.retain(SimpleNamespace(records=records),root)
            self.assertEqual(list(root.iterdir()),[])
        for kind in ('java','wit','compiled-java','compiled-wit','extra-source','private-classpath',
                     'missing','oversized','magic','hardlink'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary).resolve();self.populate(root)
                if kind in ('java','wit','compiled-java','compiled-wit'):
                    name={'java':'src/Capsule.java','wit':'wit/service.wit',
                          'compiled-java':'build/project/src/main/java/Capsule.java',
                          'compiled-wit':'build/wit/service.wit'}[kind]
                    (root/name).write_bytes(b'unknown-private-input')
                elif kind=='extra-source':(root/'src/Private.java').write_bytes(b'private')
                elif kind=='private-classpath':(root/'build/project/captured-application').mkdir()
                elif kind=='missing':(root/'build/closed-runtime.wasm').unlink()
                elif kind=='oversized':
                    with (root/'build/closed-runtime.wasm').open('wb') as stream:stream.truncate(4*1024*1024+1)
                elif kind=='magic':(root/'build/closed-runtime.wasm').write_bytes(b'not-wasm')
                elif kind=='hardlink':
                    (root/'build/closed-runtime.wasm').unlink()
                    os.link(root/'build/core.wasm',root/'build/closed-runtime.wasm')
                capture.retain(SimpleNamespace(records=[{'stage':'component-new','exitCode':1}]),root)
                target=root/'build/component-inputs'
                self.assertEqual(list(target.glob('*.wasm')),[])
                refused=json.loads((target/'refused.json').read_bytes())
                self.assertFalse(refused['qualification']);self.assertEqual(refused['status'],'unavailable')
        original=RuntimeError('original-normal-assembly-failure')
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeError) as caught:
                try:raise original
                finally:capture.retain(object(),Path(temporary).resolve())
            self.assertIs(caught.exception,original)


if __name__=='__main__':unittest.main()
