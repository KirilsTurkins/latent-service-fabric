"""Required runtime controls cannot disappear when a compiler/runtime is missing."""
import os
import unittest
from unittest.mock import patch

from tools.tests import test_typescript_event_ownership as events
from tools.tests import test_typescript_record_retirement as records


class RequiredQualificationTools(unittest.TestCase):
    def test_missing_native_compiler_is_an_error_on_each_platform(self):
        for platform in ('posix', 'nt'):
            for control, diagnostic in (
                    (events.EventCallbackFailureControls, 'callback failure controls'),
                    (records.OwnerRetryTests, 'native owner retry controls')):
                with self.subTest(platform=platform, control=control.__name__), \
                        patch.dict(os.environ, {}, clear=True), \
                        patch.object(os, 'name', platform), \
                        patch('shutil.which', return_value=None):
                    with self.assertRaisesRegex(RuntimeError, diagnostic):
                        control.setUpClass()

    def test_wasm_trap_witness_requires_both_clang_and_node(self):
        for missing in ('clang++', 'node', 'both'):
            def which(name):
                return None if missing in (name, 'both') else '/tool/' + name
            with self.subTest(missing=missing), patch.dict(os.environ, {}, clear=True), \
                    patch('shutil.which', side_effect=which):
                control = events.AbortTrapFrameControls(
                    'test_wasm_trap_does_not_fabricate_frame_destruction')
                with self.assertRaisesRegex(RuntimeError, 'Clang with wasm32 and Node'):
                    control.test_wasm_trap_does_not_fabricate_frame_destruction()
