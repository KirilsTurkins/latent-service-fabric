"""Closed source/authority controls, separate from NativeAOT and signed execution."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools import dotnet_resource_runtime_fixture as fixture
from tools.dotnet_guest.project import create, validate
from tools.dotnet_guest import runtime
from tools.rust_capsule_project import snapshot


class DotnetResourceRuntimeFixture(unittest.TestCase):
    def test_ordinary_task_resource_logging_selection_keeps_original_sdk_and_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=create(root/'original','greeting')
            app,proof=fixture.project(root/'project',root/'outside')
            project,sdk,_pins=validate(snapshot(app));before=json.loads((original/'capsule-project.json').read_bytes())
            expected=dict(before['limits']);expected['logBytes']=16384
            self.assertEqual(project['limits'],expected)
            self.assertEqual(sdk['sdk'],json.loads((original/'sdk-lock.json').read_bytes())['sdk'])
            world=(app/'wit/world.wit').read_bytes()
            self.assertIn(b'greet: async func(',world)
            for declaration in fixture.DECLARATIONS:self.assertEqual(world.count(('import '+declaration+';').encode()),1)
            self.assertNotIn(runtime.HTTP.encode(),world)
            self.assertEqual(runtime.select(list(fixture.DECLARATIONS),['wasi:cli/stdout@0.2.6','wasi:io/poll@0.2.6']),'runtime-logging')
            self.assertNotIn('grants',project)
            self.assertFalse(proof['guestCompiled']);self.assertEqual(proof['signedExecution'],'pending')
            self.assertFalse(proof['applicationSchedulerOrContextShim'])
            self.assertEqual(sdk['template']['sourceDigest'],fixture.digest((app/'src/Main.cs').read_bytes()))
            self.assertEqual(sdk['template']['witDigest'],fixture.digest(world))

    def test_unseen_transitive_library_holds_real_independent_embedded_streams_across_incomplete_callbacks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);_app,proof=fixture.project(root/'project',root/'outside')
            library=root/'outside/library';child=library/'child'
            self.assertEqual((library/'Library.cs').read_bytes(),fixture.LIBRARY_SOURCE.encode())
            self.assertEqual((child/'Resource.cs').read_bytes(),fixture.CHILD_SOURCE.encode())
            for name,raw in fixture.DATA.items():self.assertEqual((child/name).read_bytes(),raw)
            self.assertEqual(fixture.DATA['text.txt'].hex(),fixture.TEXT_HEX)
            self.assertIn(b'ProjectReference Include="child/Child.csproj"',(library/'Library.csproj').read_bytes())
            self.assertIn(b'LogicalName="outside.resource.empty"',(child/'Child.csproj').read_bytes())
            for api in ('Assembly.GetManifestResourceStream','Task.Run','Task.WhenAll','Task.Delay','AsyncLocal',
                        'RandomNumberGenerator.Fill','Stopwatch.GetTimestamp','DateTimeOffset.UtcNow','Console.Out.Flush'):
                self.assertIn(api,fixture.LIBRARY_SOURCE+fixture.CHILD_SOURCE)
            self.assertIn('if (one.IsCompleted || two.IsCompleted || all.IsCompleted)',fixture.LIBRARY_SOURCE)
            self.assertNotIn('SetSynchronizationContext',fixture.LIBRARY_SOURCE)
            self.assertNotIn('Console.SetOut',fixture.LIBRARY_SOURCE)
            self.assertFalse(proof['threadLocalQualified']);self.assertFalse(proof['asyncFlushQueuePresent'])

    def test_pure_package_has_exact_child_dependency_and_no_executable_or_build_payload(self):
        for child in (False,True):
            identity=fixture.PACKAGES[int(child)];raw=fixture.package(identity,b'controlled DLL bytes',child=child)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                self.assertEqual(set(archive.namelist()),{identity+'.nuspec','lib/net10.0/'+identity+'.dll'})
                self.assertEqual(archive.read('lib/net10.0/'+identity+'.dll'),b'controlled DLL bytes')
                metadata=archive.read(identity+'.nuspec').decode()
                if child:self.assertNotIn('<dependencies>',metadata)
                else:self.assertIn('<dependency id="'+fixture.PACKAGES[1]+'" version="[1.0.0]" />',metadata)

    def test_managed_outputs_do_not_hide_original_library_source_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);_app,_proof=fixture.project(root/'project',root/'outside')
            library=root/'outside/library';original=fixture.inventory(fixture.source_files(library))
            output=library/'child/bin/Release';output.mkdir(parents=True)
            (output/'public-controlled.dll').write_bytes(b'controlled build output')
            fixture.unchanged_library(library,original)
            (library/'Library.cs').write_bytes(b'changed source')
            with self.assertRaisesRegex(RuntimeError,'original-library-source-changed'):
                fixture.unchanged_library(library,original)

    def test_foreign_originals_are_rejected_before_project_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);other=root/'other';other.mkdir()
            with self.assertRaisesRegex(RuntimeError,'independent-originals'):
                fixture.project(root/'project',other/'outside')
            self.assertFalse((root/'project').exists())


if __name__=='__main__':unittest.main()
