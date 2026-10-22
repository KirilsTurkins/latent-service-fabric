"""Fixed-cohort routing and original finite programme invariants; no C execution."""
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import tools
from tools import diagnose_c_thread_minimal as original
from tools import diagnose_c_thread_ready_handoff as selected
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, snapshot


class CThreadReadyHandoff(unittest.TestCase):
    def test_only_fixed_native_route_and_explicit_diagnostic_metadata_change_original_run(self):
        old = inspect.getsource(original.run)
        new = inspect.getsource(selected.run)
        new = new.replace(' from tools import host_codec_funcrefs_native_products as native\n', '', 1)
        new = new.replace("'schemaVersion':'latent.c.ready-handoff.diagnostic.v1'",
            "'schemaVersion':'latent.c.thread-minimal.diagnostic.v1'", 1)
        new = new.replace("\n  'canonicalHandoffCandidate':'thread-yield-then-promote',", '', 1)
        new = new.replace('lsf-c-ready-minimal-', 'lsf-c-minimal-')
        self.assertEqual(new, old)
        self.assertEqual(selected.fixture.MODES,
            ('application-error', 'minimal-c11', 'minimal-pthread', 'c11', 'pthread'))
        self.assertIn("'diagnosticOnly':True,'full17ProgrammeQualified':False", new)
        self.assertIn("'qualification':False", new)

    def test_fixed_source_refusal_precedes_any_normal_guest_compiler_execution(self):
        fixed = SimpleNamespace(SOURCE='fixed-source-test-port')
        with TemporaryDirectory() as directory:
            with patch.object(tools, 'host_codec_funcrefs_native_products', fixed, create=True), \
                    patch.dict('sys.modules', {'tools.host_codec_funcrefs_native_products': fixed}), \
                    patch.object(selected.sys, 'platform', 'linux'), \
                    patch.object(selected.sys, 'version_info', (3, 13, 5)), \
                    patch.object(selected.os, 'geteuid', return_value=1000, create=True), \
                    patch.object(selected, 'source_inputs', return_value={}), \
                    patch.object(selected, 'native_evidence', side_effect=WorkflowError('fixed-source-refused')) as admission, \
                    patch.object(selected.compiler, 'build') as compiler:
                with self.assertRaisesRegex(WorkflowError, 'fixed-source-refused'):
                    selected.run(Path(directory) / 'prepared', Path(directory) / 'output')
                admission.assert_called_once_with(fixed, Path(directory) / 'prepared')
                compiler.assert_not_called()

    def test_executed_fixed_reader_controller_and_workflow_are_source_bound(self):
        before = selected.source_inputs()
        for name in ('tools/host_codec_funcrefs_native_products.py',
                'tools/host_codec_funcrefs_native_products_reader.py',
                'tools/host_codec_native_products_reader.py', 'tools/sdk_native_products_reader.py',
                'tools/java_replay_materials.py', 'tools/build_process_linux.py',
                'tools/build_process_signals.py', 'tools/diagnose_c_thread_ready_handoff.py',
                '.github/workflows/c-thread-ready-handoff.yml'):
            self.assertIn(name, before)
            self.assertGreater(before[name]['bytes'], 0)
        header = (ROOT / 'sdk/c-guest/runtime/thread-abi.h').read_bytes()
        self.assertIn(b'[thread-yield-then-promote]', header)
        with TemporaryDirectory() as directory:
            captured = snapshot(selected.fixture.prepare(Path(directory) / 'application'))
            self.assertEqual([raw for name, raw in captured.items() if name.endswith('/thread-abi.h')], [header])
        self.assertEqual(selected.source_inputs(), before)


if __name__ == '__main__':
    unittest.main()
