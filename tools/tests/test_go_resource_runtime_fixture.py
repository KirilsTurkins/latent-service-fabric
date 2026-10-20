"""Project admission and immutable source controls; no signed execution claim."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import go_resource_runtime_fixture as fixture
from tools.go_capsule_project import create, validate
from tools.rust_capsule_project import snapshot


class GoResourceRuntimeFixture(unittest.TestCase):
    def test_explicit_managed_profile_retains_sdk_and_original_budgets_except_declared_log_bytes(self):
        with tempfile.TemporaryDirectory() as owned:
            root=Path(owned)
            original=create(root/'original','greeting',runtime_profile=fixture.PROFILE)
            app,proof=fixture.project(root/'project',root/'outside')
            descriptor,sdk,_pins=validate(snapshot(app))
            before=json.loads((original/'capsule-project.json').read_bytes())
            self.assertEqual(descriptor['runtimeProfile'],'go-component-activation-v5')
            expected=dict(before['limits']);expected['logBytes']=16384
            self.assertEqual(descriptor['limits'],expected)
            self.assertEqual(sdk['sdk'],json.loads((original/'sdk-lock.json').read_bytes())['sdk'])
            self.assertEqual((app/'wit/world.wit').read_bytes().count(fixture.LOG.encode()),1)
            self.assertIn(b'greet: async func(', (app/'wit/world.wit').read_bytes())
            self.assertNotIn('grants',descriptor)
            self.assertFalse(proof['applicationLoggerOrExecutorHook'])
            self.assertFalse(proof['nativeThreadsQualified'])
            self.assertFalse(proof['compilerExecuted'])
            self.assertEqual(proof['signedExecution'],'pending')

    def test_transitive_module_source_uses_real_embedded_readers_and_ordinary_go_callbacks(self):
        with tempfile.TemporaryDirectory() as owned:
            root=Path(owned);_app,proof=fixture.project(root/'project',root/'outside')
            library=root/'outside/library';data=root/'outside/data'
            self.assertEqual((library/'library.go').read_bytes(),fixture.LIBRARY_SOURCE)
            self.assertEqual((data/'data.go').read_bytes(),fixture.DATA_SOURCE)
            self.assertIn(('require '+fixture.PACKAGES[1]+' v0.0.0').encode(),(library/'go.mod').read_bytes())
            for name,raw in fixture.DATA.items():self.assertEqual((data/name).read_bytes(),raw)
            self.assertIn(b'//go:embed text.txt binary.bin empty.bin',fixture.DATA_SOURCE)
            self.assertIn(b'func Open() fs.File',fixture.DATA_SOURCE)
            self.assertIn(b'go func(label string, input fs.File)',fixture.LIBRARY_SOURCE)
            self.assertIn(b'<-gate',fixture.LIBRARY_SOURCE)
            self.assertIn(b'log.Output(1, value)',fixture.LIBRARY_SOURCE)
            self.assertNotIn(b'latent:',fixture.LIBRARY_SOURCE)
            self.assertNotIn(b'setLogger',fixture.LIBRARY_SOURCE)
            self.assertEqual(proof['outside'],fixture.digest(fixture.inventory(snapshot(root/'outside'))))

    def test_foreign_original_directory_is_rejected_before_any_project_write(self):
        with tempfile.TemporaryDirectory() as owned:
            root=Path(owned);other=root/'other';other.mkdir()
            with self.assertRaisesRegex(RuntimeError,'independent-originals'):
                fixture.project(root/'project',other/'outside')
            self.assertFalse((root/'project').exists())


if __name__=='__main__':unittest.main()
