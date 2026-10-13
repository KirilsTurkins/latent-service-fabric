"""Explicit toolkit candidate selection cannot invent support or inputs."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from tools.dev_managed_distribution import pack
from tools.dev_managed_tools import unpack
from tools.typescript_guest import runtime_bundle as bundle
from tools.typescript_guest import runtime_profile as runtime


class TypeScriptRuntimeBundleTests(unittest.TestCase):
    def project(self,root,profile=None):
        value={}if profile is None else {'runtimeProfile':profile}
        project=root/'project';project.mkdir()
        (project/'capsule-project.json').write_text(json.dumps(value),encoding='utf-8')
        return project

    def tools(self,root,profile=runtime.ASYNC_PROFILE):
        selected=root/'typescript-runtime';selected.mkdir()
        (selected/'licenses').mkdir();(selected/'licenses/LICENSE').write_bytes(b'original notice')
        (selected/'engine.wasm').write_bytes(b'\0asm\1\0\0\0actual')
        (selected/'engine-input.json').write_bytes(b'{}')
        rows=[{'path':path.relative_to(selected).as_posix(),'digest':runtime.digest(path.read_bytes()),'size':path.stat().st_size}
              for path in sorted(selected.rglob('*'))if path.is_file()]
        value={'schemaVersion':bundle.SCHEMA,'profile':profile,'files':rows,
               'qualification':'unknown','apiSupport':'not-evaluated'}
        (selected/bundle.MANIFEST).write_text(json.dumps(value),encoding='utf-8')
        return selected,value

    def test_default_synchronous_project_ignores_absent_candidate_payload(self):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name)
            self.assertEqual(bundle.compiler_options(root,self.project(root)),{})

    def test_explicit_candidate_requires_actual_bundle(self):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name)
            with self.assertRaisesRegex(ValueError,'bundle-directory-required'):
                bundle.compiler_options(root,self.project(root,runtime.ASYNC_PROFILE))

    def test_project_and_payload_profile_must_agree(self):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name);project=self.project(root,runtime.ASYNC_PROFILE)
            with patch.object(bundle,'validate',return_value={'profile':runtime.CLOCK_PROFILE}):
                with self.assertRaisesRegex(ValueError,'project-profile-mismatch'):
                    bundle.compiler_options(root,project)

    def test_exact_import_selection_passes_only_bound_file_paths(self):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name);project=self.project(root,runtime.IMPORT_PROFILE)
            with patch.object(bundle,'validate',return_value={'profile':runtime.IMPORT_PROFILE}):
                value=bundle.compiler_options(root,project)
            selected=root/'typescript-runtime'
            self.assertEqual(value,{'runtime_engine':selected/'engine.wasm',
                'runtime_engine_receipt':selected/'engine-input.json',
                'runtime_splicer':selected/'splicer','runtime_splicer_receipt':selected/'splicer-input.json'})

    def test_changed_payload_byte_is_rejected_before_engine_validation(self):
        with tempfile.TemporaryDirectory()as name:
            selected,_=self.tools(Path(name))
            (selected/'engine.wasm').write_bytes(b'changed')
            with patch.object(runtime,'validate_engine')as validate:
                with self.assertRaisesRegex(ValueError,'byte-identity'):
                    bundle.validate(selected)
                validate.assert_not_called()

    def test_declared_support_is_rejected_before_engine_validation(self):
        with tempfile.TemporaryDirectory()as name:
            selected,value=self.tools(Path(name));value['qualification']='passed'
            (selected/bundle.MANIFEST).write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'profile-or-schema'):
                bundle.validate(selected)

    def test_unknown_bundle_field_is_rejected(self):
        with tempfile.TemporaryDirectory()as name:
            selected,value=self.tools(Path(name));value['authority']='automatic'
            (selected/bundle.MANIFEST).write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'profile-or-schema'):
                bundle.validate(selected)

    def test_original_notices_and_inputs_survive_actual_managed_pack_unpack(self):
        with tempfile.TemporaryDirectory()as name:
            root=Path(name);selected,_=self.tools(root)
            sdk=root/'sdk';sdk.mkdir()
            source=bundle.regular_files(selected)
            pack({'typescript-runtime':selected},sdk)
            staged=unpack(sdk,root/'staged',lambda:None)
            self.assertEqual(bundle.regular_files(staged/'typescript-runtime'),source)

    def test_maintained_recipe_passes_exact_selected_inputs_to_builder(self):
        from tools.dev_guest_recipe import compile_managed
        with tempfile.TemporaryDirectory()as name:
            root=Path(name);project=self.project(root,runtime.IMPORT_PROFILE)
            (root/'build-cache').mkdir()
            options={'runtime_engine':root/'selected-engine',
                     'runtime_engine_receipt':root/'selected-receipt',
                     'runtime_splicer':root/'selected-splicer',
                     'runtime_splicer_receipt':root/'selected-splicer-receipt'}
            with patch('tools.dev_guest_recipe.sys.platform','linux'), \
                 patch('tools.dev_guest_recipe.platform.machine',return_value='x86_64'), \
                 patch('tools.dev_managed_tools.unpack',return_value=root/'staged'), \
                 patch.object(bundle,'compiler_options',return_value=options)as select, \
                 patch('tools.typescript_guest.build.build')as build, \
                 patch.dict(os.environ,{},clear=False):
                compile_managed(root/'payload',project,root/'output',lambda:None,'typescript')
            select.assert_called_once_with(root/'staged',project)
            self.assertEqual(build.call_args.kwargs,{'tools':root/'staged/tools',**options})


if __name__=='__main__':unittest.main()
