"""Actual nested Rust verification stops before compiler namespace construction."""
import json
import unittest
from unittest.mock import patch

from tools import application_dependencies, rust_capsule_build as build, rust_capsule_project as project
from tools.tests.frontend_dependency_fixture import FrontendFixture


class RustFrontendDependencies(unittest.TestCase):
    def setUp(self):
        self.fixture = FrontendFixture(self, 'rust', project.create)

    def invoke(self):
        value = self.fixture
        build.build(value.app, value.output, value.tool, None,
                    'https://example.invalid/reviewed-source', offline=True)

    def test_outer_reviewed_capture_is_verified_before_compiler_without_original_source(self):
        value, called = self.fixture, []
        original = application_dependencies.verify_inputs
        def verify(owner, language, **kwargs):
            verified = original(owner, language, **kwargs)
            self.assertIsNotNone(verified)
            self.assertEqual(owner, value.owner)
            called.append(owner)
            if len(called) == 2:
                raise ValueError('intentional-before-language-compiler-boundary')
            return verified
        with patch.object(build, 'resolve_tools', return_value=(
                {'cargo': value.tool, 'rustc': value.tool, 'wasm-tools': value.tool}, [])), \
                patch.object(build.shutil, 'which', return_value=str(value.tool)), \
                patch.object(application_dependencies, 'verify_inputs', side_effect=verify), \
                patch.object(build.Commands, 'run', side_effect=AssertionError('compiler must not run')) as command:
            with self.assertRaisesRegex(ValueError, 'intentional-before-language-compiler-boundary'):
                self.invoke()
        self.assertEqual(called, [value.owner, value.owner]); command.assert_not_called()
        value.assert_observed(self)
        self.assertEqual(json.loads((value.output / 'BUILD-FAILED.json').read_bytes())['stage'], 'application-dependencies')
        self.assertFalse((value.output / 'application-dependencies.json').exists())

    def test_inner_capture_cannot_bypass_outer_approval(self):
        self.fixture.shadow()
        with patch.object(build, 'resolve_tools') as compiler:
            with self.assertRaisesRegex(ValueError, 'ambiguous-application-lock'):
                self.invoke()
        compiler.assert_not_called()
        self.assertFalse((self.fixture.output / 'BUILD-COMPLETE.json').exists())

    def test_tampered_outer_cas_is_rejected_before_language_compiler(self):
        self.fixture.tamper()
        with patch.object(build, 'resolve_tools') as compiler:
            with self.assertRaisesRegex(ValueError, 'artifact-integrity'):
                self.invoke()
        compiler.assert_not_called()
        self.assertFalse((self.fixture.output / 'BUILD-COMPLETE.json').exists())
