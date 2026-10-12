"""Real nested Go inputs fail honestly at the compiler construction boundary."""
import json
import unittest
from unittest.mock import patch

from tools import go_capsule_build as build, go_capsule_project as project
from tools.tests.frontend_dependency_fixture import FrontendFixture


class GoFrontendDependencies(unittest.TestCase):
    def setUp(self):
        self.fixture = FrontendFixture(self, 'go', project.create, native_inputs={
            'go-resolved.lock.json': b'{"fixture":"stops-before-module-compiler"}'})

    def invoke(self):
        value = self.fixture
        build.build(value.app, value.output, value.tool, None,
                    'https://example.invalid/reviewed-source', offline_cache=value.tools)

    def test_outer_reviewed_capture_materializes_before_compiler_without_original_source(self):
        value, called = self.fixture, []
        with patch.object(build, 'prepare', side_effect=value.prepare_boundary(self, called)), \
                patch.object(build, 'Compiler', side_effect=AssertionError('compiler must not run')) as compiler:
            with self.assertRaisesRegex(ValueError, 'intentional-before-language-compiler-boundary'):
                self.invoke()
        self.assertEqual(called, [value.owner]); compiler.assert_not_called()
        value.assert_observed(self)
        self.assertEqual(json.loads((value.output / 'BUILD-FAILED.json').read_bytes())['stage'], 'application-dependencies')

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
