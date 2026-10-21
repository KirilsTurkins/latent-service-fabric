"""Private observer controls do not qualify the ordinary HTTP programme."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import diagnose_rust_wasi_http_trap as private
from tools import java_resource_private_observer as observer,rust_http_private_build as build
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT


class RustHttpPrivateTrap(unittest.TestCase):
    def test_original_failed_first_call_cannot_be_replaced_by_another_outcome_or_component(self):
        source=json.loads((ROOT/private.FAILURE).read_bytes())
        private.original_failure(source)
        invalid=[]
        for key,value in [('qualification',True),('outerConclusion','success'),('causeProven',True),('source','0'*40)]:
            row=copy.deepcopy(source);row[key]=value;invalid.append(row)
        for key,value in [('terminalState','succeeded'),('resolvedRevision',{'releaseDigest':'sha256:'+'0'*64})]:
            row=copy.deepcopy(source);row['invocation']['response']['data'][key]=value;invalid.append(row)
        for row in invalid:
            with self.subTest(row=row),self.assertRaises(WorkflowError):private.original_failure(row)

    def test_closed_numeric_observer_and_global_bounds_keep_unknown_text_out(self):
        frame={'functionIndex':41,'functionOffset':24,'moduleOffset':3121}
        def encoded(variant='cannot-block-sync-task',frames=None):
            return observer.PREFIX+json.dumps({'trapVariant':variant,'available':True,
                'truncated':False,'frames':[frame] if frames is None else frames}).encode()+b'\n'
        found=observer.capture(encoded())
        self.assertEqual(found['records'][0]['trapVariant'],'cannot-block-sync-task')
        self.assertFalse(found['qualification']);self.assertFalse(found['rawNodeOutputRetained'])
        for raw in [encoded('arbitrary error'),encoded()*17,b'x'*262145,
                encoded(frames=[{**frame,'functionIndex':'symbol'}])]:
            with self.subTest(raw=raw[:64]),self.assertRaises((WorkflowError,ValueError)):observer.capture(raw)
        found=observer.capture(encoded(frames=[frame]*20)+encoded(frames=[frame]*20))
        self.assertEqual(sum(len(r['frames']) for r in found['records']),32)
        self.assertTrue(found['records'][-1]['truncated'])

    def test_exact_original6fd_lock_and_two_existing_source_overlays(self):
        self.assertTrue(build.locked_registry_inputs(ROOT)['locked'])
        self.assertTrue(all(file_identity(ROOT/name)==expected for name,expected in private.OBSERVER_INPUTS.items()))
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory);sources,overlays=observer.overlay_sources(ROOT,output)
            self.assertEqual(set(sources),set(observer.PREIMAGES));self.assertEqual(len(overlays),2)
            self.assertIn('wasmtime::Trap::CannotBlockSyncTask',(output/'containment.rs').read_text())
            self.assertIn('NonZeroUsize::new(32)',(output/'engine.rs').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=(ROOT/'Cargo.lock').read_bytes();(root/'Cargo.lock').write_bytes(raw+b'\n')
            with self.assertRaisesRegex(WorkflowError,'exact6fd-lock'):build.locked_registry_inputs(root)

    def test_retention_and_cleanup_refusal_cannot_mask_the_primary_failure(self):
        service=type('Service',(),{'buffers':[b'',b'']})()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(private,'stop',side_effect=ValueError('cleanup')), \
                patch.object(private.observer,'capture',side_effect=ValueError('capture')), \
                patch.object(private,'write_json',side_effect=ValueError('write')):
            private.final_observation(None,service,Path(directory),{},primary_failure=True)
            with self.assertRaisesRegex(ValueError,'cleanup'):
                private.final_observation(None,service,Path(directory),{},primary_failure=False)

    def test_outer_owned_peer_and_service_cleanup_preserves_primary_but_refuses_false_success(self):
        def fail():raise ValueError('secondary cleanup')
        record={}
        with self.assertRaisesRegex(RuntimeError,'original primary'):
            with private.owned_cleanup(record) as cleanup:
                cleanup.callback(fail);raise RuntimeError('original primary')
        self.assertTrue(record['cleanupRefused']);self.assertTrue(record['originalFailurePreserved'])
        with self.assertRaisesRegex(ValueError,'secondary cleanup'):
            with private.owned_cleanup({}) as cleanup:cleanup.callback(fail)


if __name__=='__main__':unittest.main()
