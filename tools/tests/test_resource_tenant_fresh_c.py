"""Fresh C compiler seam and retained Java producer controls, no native execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import resource_tenant_fresh_c as fresh_c
from tools.rust_capsule_project import inventory,snapshot


class ResourceTenantFreshC(unittest.TestCase):
    def test_normal_c_capture_removes_originals_then_one_fresh_build_has_truthful_new_records(self):
        for changed in (False,True):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);binaries={}
                for name in ('zig','wit-bindgen','wasm-tools','examples/package','examples/capsule_contracts'):
                    p=root/name.replace('/','-');p.write_bytes(b'test-owned-regular-input');binaries[name]=p
                seen=[]
                def build(app,output,contracts,packager,repository,**kwargs):
                    self.assertFalse((app.parent/'outside-compiled-resource-library').exists())
                    self.assertEqual(set(kwargs['installed']),{'zig','wit-bindgen','wasm-tools'})
                    self.assertEqual(contracts,binaries['examples/capsule_contracts'])
                    self.assertEqual(packager,binaries['examples/package'])
                    seen.append(app);output.mkdir()
                    (output/'source-inputs.json').write_bytes(b'{}' if changed else inventory(snapshot(app)))
                    for name in ('component.wasm','build-observation.json','BUILD-COMPLETE.json'):
                        (output/name).write_bytes(b'fresh-owned-record')
                    return output
                with patch.object(fresh_c.shutil,'which',side_effect=lambda name:str(binaries[name])), \
                        patch('tools.c_capsule_build.build',side_effect=build), \
                        patch.object(fresh_c,'original_build',return_value={'fresh':True}):
                    if changed:
                        with self.assertRaisesRegex(RuntimeError,'fresh-compile-source-or-closure'):
                            fresh_c.build_component(root/'campaign',binaries)
                    else:
                        artifact,expected,proof=fresh_c.build_component(root/'campaign',binaries)
                        self.assertTrue(artifact.is_dir());self.assertEqual(len(expected),4)
                        self.assertEqual(proof['guestComponentsCompiled'],1)
                        self.assertEqual(proof['nativeProductsBuilt'],0)
                        self.assertFalse(proof['normalBaselineRepeated'])
                        self.assertFalse(proof['oldCompilerObservationBackfilled'])
                        self.assertFalse(proof['historicalFiniteAncestry']['originalCompilerObservationRetained'])
                        self.assertTrue(proof['capture']['originalsRemoved'])
                self.assertEqual(len(seen),1)

    def test_missing_pinned_c_tool_refuses_before_fresh_compile(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(fresh_c.shutil,'which',return_value=None), \
                patch('tools.c_capsule_build.build') as build, \
                self.assertRaisesRegex(RuntimeError,'pinned-tools-required'):
            fresh_c.build_component(Path(temp)/'campaign',{})
        build.assert_not_called()


if __name__ == '__main__':unittest.main()
