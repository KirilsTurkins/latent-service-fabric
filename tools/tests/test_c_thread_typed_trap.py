"""Actual diagnostic-origin preservation and immutable retained-byte refusals."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import c_thread_minimal_inputs as inputs
from tools.phase2_operator_process import WorkflowError


class TypedTrapOrigin(unittest.TestCase):
    @staticmethod
    def actual():
        return json.loads((Path(__file__).parent/'fixtures/c-thread-minimal-origin.json').read_bytes())

    def test_actual_five_call_diagnostic_origin_is_accepted_without_qualification_claim(self):
        value=self.actual();original=copy.deepcopy(value)
        inputs.origin(value['run'],value['job'],value['artifact'])
        self.assertEqual(value,original)
        self.assertEqual(inputs.MODES,('application-error','minimal-pthread'))

    def test_foreign_or_failed_source_run_job_or_artifact_is_refused(self):
        for section,key,changed in (
            ('run','head_sha','0'*40),('run','head_branch','feat/c-thread-runtime-consumer-20261021'),
            ('run','path','.github/workflows/c-thread-runtime.yml'),('run','conclusion','failure'),
            ('job','run_id',39693423779),('job','head_sha','0'*40),('job','conclusion','failure'),
            ('artifact','id',12389806670),('artifact','expired',True),
            ('artifact','size_in_bytes',1696525),('artifact','digest','sha256:'+'0'*64)):
            with self.subTest(section=section,key=key):
                value=self.actual();value[section][key]=changed
                with self.assertRaises(WorkflowError):inputs.origin(value['run'],value['job'],value['artifact'])
        value=self.actual();value['job']['steps'][0]['conclusion']='failure'
        with self.assertRaises(WorkflowError):inputs.origin(value['run'],value['job'],value['artifact'])

    def test_actual_controller_import_and_all_loaded_runtime_helpers_are_source_bound(self):
        import sys
        from tools import diagnose_c_thread_typed_trap as controller
        from tools.rust_capsule_project import ROOT
        bound=controller.source_inputs()
        actual={Path(module.__file__).relative_to(ROOT).as_posix()
            for name,module in list(sys.modules.items())
            if name.startswith('tools.') and not name.startswith('tools.tests')
            and getattr(module,'__file__',None) and Path(module.__file__).is_relative_to(ROOT)}
        self.assertLessEqual(actual,set(bound))
        self.assertTrue({'tools/host_codec_table_store_native_products.py',
            'tools/host_codec_table_store_native_products_reader.py',
            'tools/build_process_linux.py','tools/build_process_signals.py'}<=set(bound))
        self.assertIn('tools/diagnose_c_thread_typed_trap.py',actual)

    def test_modified_archive_bytes_are_refused_before_any_extraction_or_output(self):
        with tempfile.TemporaryDirectory()as temporary:
            output=Path(temporary)/'contents'
            for raw in (b'',b'PK\x03\x04',bytes(inputs.ARTIFACT['size_in_bytes'])):
                with self.assertRaises(WorkflowError):inputs.extract(raw,output)
                self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
