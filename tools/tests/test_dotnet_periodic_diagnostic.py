import json
import re
import subprocess
import unittest

from tools import dotnet_periodic_diagnostic as selected
from tools.dotnet_periodic_diagnostic_node import ACTIVATION,decode,frame_size
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT,read_file


class PeriodicDiagnosticTests(unittest.TestCase):
    def test_default_false_diagnostic_restores_every_previous_workflow_body(self):
        import hashlib
        from tools.ci_lane_inventory import workflow_model
        source='.github/workflows/dotnet-published-http.yml'
        # Exact public Git blob from selected.BASE, retained for clean CI where
        # the diagnostic branch is not an ancestor of the squash merge.
        raw=read_file(ROOT/'tools/tests/fixtures/dotnet-periodic-base-workflow.yml')
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'2158598ce9a64b7a6325de2382083608d64c833a5c3b0addf06f5829e5c04978')
        old=workflow_model(raw.decode('utf8'))
        actual=workflow_model((ROOT/source).read_text(encoding='utf8'))
        selector=actual['on']['workflow_dispatch']['inputs'].pop('periodic_diagnostic')
        self.assertEqual(selector['type'],'boolean');self.assertIs(selector['default'],False)
        job=actual['jobs'].pop('periodic-diagnostic')
        self.assertEqual(job['if'],"github.event_name == 'workflow_dispatch' && inputs.periodic_diagnostic && !inputs.owner_capacity && !inputs.mixed_content && !inputs.fresh_component")
        for name,previous in old['jobs'].items():
            self.assertEqual(actual['jobs'][name]['if'],previous['if']+' && !inputs.periodic_diagnostic')
            actual['jobs'][name]['if']=previous['if']
        # #1298 added the actual copied timer-driver control after this frozen
        # diagnostic base. Remove only that exact additive step and its two
        # retained-output paths before comparing every previous workflow field.
        steps=actual['jobs']['owner-capacity']['steps']
        driver=[step for step in steps if step.get('name') ==
            'Check the actual private timer driver against the original two queued slots']
        self.assertEqual(driver,[{'name':'Check the actual private timer driver against the original two queued slots',
            'run':'python3 -B tools/dotnet_managed_work_controls.py --dotnet "$(command -v dotnet)" --timer-driver-tools "$RUNNER_TEMP/capacity-tools" --output "$RUNNER_TEMP/timer-driver-controls"'}])
        steps.remove(driver[0])
        upload=[step for step in steps if step.get('name') ==
            'Retain bounded public capacity source build and actual owner evidence']
        self.assertEqual(len(upload),1)
        extra='${{ runner.temp }}/timer-driver-controls/timer-driver-controls.json\n${{ runner.temp }}/timer-driver-controls/logs/**\n'
        self.assertEqual(upload[0]['with']['path'].count(extra),1)
        upload[0]['with']['path']=upload[0]['with']['path'].replace(extra,'',1)
        self.assertEqual(actual,old)
        self.assertEqual(job['timeout-minutes'],30)
        commands='\n'.join(step.get('run','') for step in job['steps'])
        self.assertIn('tools/dotnet_periodic_diagnostic.py qualify',commands)
        self.assertNotIn('tools/qualify_dotnet_managed_capacity.py',commands)
        self.assertNotIn('cargo build',commands)

    def test_only_closed_actual_source_literals_have_codes(self):
        values=selected.codes()
        source=b'\n'.join(read_file(ROOT/name) for name in (selected.HANDLER,
            'sdk/dotnet-guest/tools/http-errors/ManagedWorkRuntime.cs',
            'sdk/dotnet-guest/tools/http-errors/ManagedWorkTimers.cs','tools/dotnet_guest/async_exports.py'))
        for code in values:self.assertIn(b'"'+code.encode()+b'"',source)
        self.assertEqual(values,sorted(set(values)))
        self.assertEqual(len(values),37)

    def test_exact_frozen_host_log_encoding_identifies_only_one_frame(self):
        import hashlib
        # Exact logging.rs blob at immutable native producer 6fd19eab2c224fc31481d03de5008de4d3e4429e.
        source=read_file(ROOT/'tools/tests/fixtures/dotnet-periodic-host-logging.rs')
        self.assertEqual(hashlib.sha256(source).hexdigest(),'36a08992775520c9e4868f15485080a3fc52dc08d306e1c870e628d6f462fe89')
        body=source.split(b'struct BorrowedLog',1)[1].split(b'\n}',1)[0]
        self.assertEqual(re.findall(rb'^    ([a-z_]+):',body,re.M),[b'activation_id',b'level',b'message',b'fields'])
        self.assertIn(b'normalized.insert("latent.activation_id", &context.activation_id.0);',source)
        self.assertIn(b'normalized.insert("latent.trace_id", &context.trace_id);',source)
        self.assertIn(b'normalized.insert("latent.span_id", &context.span_id);',source)
        sizes=[frame_size(code+1) for code in range(94)]
        self.assertEqual(len(set(sizes)),94)
        for code,size in enumerate(sizes):
            result=decode(size)
            self.assertEqual(result['code'],code)
            self.assertFalse(result['qualification'])
            if code>=38:
                self.assertEqual(result['ownerKind'],(code-38)//7)
                self.assertEqual(result['originalHostU32'],(code-38)%7)
                self.assertEqual(result['reason'],'managed-work-admission-refused')
            else:self.assertEqual(result['reason'],'unknown' if code==0 else selected.codes()[code-1])
        self.assertEqual(decode(0)['status'],'not-observed')
        for size in (-1,True,1025,sizes[0]-1,sizes[-1]+1):
            with self.assertRaises(WorkflowError):decode(size)

    def test_actual_handler_projection_preserves_original_failfast_and_private_scope(self):
        source=read_file(ROOT/selected.SNIPPET)
        self.assertIn(b'diagnosticFailFast.Previous.Previous',source)
        self.assertIn(b'TimerQueue.TimerHandler failed',source)
        self.assertIn(b'diagnosticOriginal',source)
        self.assertIn(b'CatchType=Type("System.Exception")',source)
        self.assertIn(b'branch.OpCode=OpCodes.Leave',source)
        self.assertNotIn(b'OpCodes.Ret',source)
        main=read_file(ROOT/'tools/fixtures/dotnet-managed-capacity/Main.cs')
        from tools.rust_capsule_project import digest
        self.assertEqual(digest(main),'sha256:9ae5d864dd3a49d3dabff9c16e9751cc15f3e094a3e67a80a7b810d03279ae7c')

    def test_reserve_projection_preserves_original_inputs_success_and_refusal(self):
        original=read_file(ROOT/selected.RECIPE)
        actual=selected.reserve_projection(original)
        projection=read_file(ROOT/selected.RESERVE)
        self.assertEqual(actual.replace(projection,selected.REFUSAL),original)
        self.assertNotIn(b'OWNER',projection)
        self.assertIn(b'(kind, result.AsErr) switch',projection)
        self.assertIn(b'catch { }',projection)
        self.assertIn(b'_ => "LSF-PERIODIC-CODE:0000"',projection)
        for source in (original+selected.REFUSAL,original.replace(selected.REFUSAL,b'')):
            with self.assertRaises(WorkflowError):selected.reserve_projection(source)

    def test_owner_and_error_codes_match_the_original_selected_private_bridge(self):
        source=read_file(ROOT/'sdk/dotnet-guest/runtime/http/managed.rs')
        errors=re.findall(rb'runtime::Error::([A-Za-z]+) => (\d),',source)
        self.assertEqual(errors,[(name.encode(),str(i).encode()) for i,name in enumerate(
            ('Unavailable','PermissionDenied','ResourceExhausted','Cancelled','Deadline','InvalidState','InvalidToken'))])
        owners=re.findall(rb'(\d) => runtime::OwnerKind::([A-Za-z]+),',source)
        self.assertEqual(owners,[(str(i).encode(),name.encode()) for i,name in enumerate(
            ('Task','ManagedIdleWorker','Executor','QueuedWork','Wait','Timer','Result','Native'))])
        self.assertIn(b'runtime::register(kind, parent(generation, id)?)',source)


if __name__=='__main__':unittest.main()
