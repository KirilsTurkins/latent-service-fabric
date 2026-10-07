"""Real nested NuGet capture is verified before the maintained compiler owner."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import application_dependencies
from tools.dotnet_guest import build, project
from tools.tests.frontend_dependency_fixture import FrontendFixture


class DotnetFrontendDependencies(unittest.TestCase):
    def setUp(self):
        self.fixture = FrontendFixture(self, 'dotnet', project.create, native_inputs={
            'packages.lock.json': b'{"version":2,"dependencies":{}}',
            'nuget-resolved.lock.json': b'{"fixture":"stops-before-nuget-compiler"}'})

    def invoke(self):
        value = self.fixture
        build.build(value.app, value.output, value.tool, None,
                    'https://example.invalid/reviewed-source', tools=value.tools, offline=True)

    def test_outer_reviewed_capture_is_verified_before_compiler_without_original_source(self):
        value, called = self.fixture, []
        test = self
        def contracts(command, name, executable, wit, derived):
            test.assertEqual(name, 'contracts')
            test.assertTrue(json.loads(Path(wit).read_bytes())['sources'])
            Path(derived).mkdir()
            for filename in ('contracts.json', 'wit-lock.json', 'surface.json'):
                (Path(derived) / filename).write_bytes(b'{"imports":[]}' if filename == 'surface.json' else b'{}')
            return b''
        def verify(owner, language):
            verified = application_dependencies.verify_inputs(owner, language)
            self.assertIsNotNone(verified)
            self.assertEqual(owner, value.owner)
            called.append(owner)
            raise ValueError('intentional-before-language-compiler-boundary')
        with patch.object(build.Commands, 'run', new=contracts), \
                patch.object(build, 'verify_inputs', side_effect=verify), \
                patch.object(build, 'Compiler', side_effect=AssertionError('compiler must not run')) as compiler:
            with self.assertRaisesRegex(ValueError, 'intentional-before-language-compiler-boundary'):
                self.invoke()
        self.assertEqual(called, [value.owner]); compiler.assert_not_called()
        value.assert_observed(self)
        self.assertEqual(json.loads((value.output / 'BUILD-FAILED.json').read_bytes())['stage'], 'compiler-inputs')
        self.assertFalse((value.output / 'application-dependencies.json').exists())

    def test_inner_capture_cannot_bypass_outer_approval(self):
        self.fixture.shadow()
        with patch.object(build, 'Compiler') as compiler:
            with self.assertRaisesRegex(ValueError, 'ambiguous-application-lock'):
                self.invoke()
        compiler.assert_not_called()
        self.assertFalse((self.fixture.output / 'BUILD-COMPLETE.json').exists())

    def test_tampered_outer_cas_is_rejected_before_language_compiler(self):
        self.fixture.tamper()
        with patch.object(build, 'Compiler') as compiler:
            with self.assertRaisesRegex(ValueError, 'artifact-integrity'):
                self.invoke()
        compiler.assert_not_called()
        self.assertFalse((self.fixture.output / 'BUILD-COMPLETE.json').exists())
