"""Fail closed on the explicit current-native checkpoint route."""
import unittest
from unittest.mock import patch
from tools.phase2_operator_process import WorkflowError


class JavaCheckpointGcCurrentTests(unittest.TestCase):
    def test_current_native_reader_is_explicit_and_historical_default_is_unchanged(self):
        from tools import qualify_java_checkpoint_gc as owner, wasmtime_48_0_8_678b_native_products as current
        self.assertEqual(owner.native_materials(owner.products), owner.MATERIALS)
        chosen=owner.native_materials(current)
        self.assertTrue(set(owner.MATERIALS)<set(chosen))
        for name in ('tools/qualify_java_checkpoint_gc_current.py',
                'tools/wasmtime_48_0_8_678b_native_products.py',
                '.github/workflows/java-checkpoint-current.yml',
                'tools/tests/test_java_progress_workflow.py',
                'tools/tests/test_java_progress_current_workflow.py',
                'tools/tests/test_java_checkpoint_gc.py',
                'tools/tests/test_java_checkpoint_gc_current.py'):
            self.assertIn(name,chosen)
        with self.assertRaises(WorkflowError):owner.native_materials(object())
        with patch.object(current,'SOURCE','different-source'),self.assertRaises(WorkflowError):
            owner.native_materials(current)

    def test_current_native_source_must_match_while_historical_route_is_unchanged(self):
        from tools import qualify_java_checkpoint_gc as owner, wasmtime_48_0_8_678b_native_products as current
        historical={'sha256':'historical'};actual={'sha256':'current'}
        with patch('tools.java_replay_materials.git_source_identity',return_value=actual) as identity:
            owner.require_current_native_source(owner.products,historical)
            identity.assert_not_called()
            owner.require_current_native_source(current,actual)
            identity.assert_called_once_with(owner.CURRENT_NATIVE_SOURCE)
            with self.assertRaises(WorkflowError):owner.require_current_native_source(current,historical)
        from tools import qualify_java_checkpoint_gc_current as bridge
        with patch.object(owner,'source_identity',return_value=actual), \
                patch('tools.java_replay_materials.git_source_identity',return_value=actual):
            bridge.check_source_only()
        with patch.object(owner,'source_identity',return_value=historical), \
                patch('tools.java_replay_materials.git_source_identity',return_value=actual), \
                self.assertRaises(WorkflowError):
            bridge.check_source_only()

