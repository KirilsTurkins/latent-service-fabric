"""Reject false timer successes and changes to the qualified caller profile."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import typescript_timer_races as cases
from tools import qualify_typescript_timer_races as campaign
from tools.phase2_operator_process import WorkflowError


class TimerRaceTests(unittest.TestCase):
    def test_root_deadline_cannot_be_success_cancel_fuel_or_unknown_retirement(self):
        row={'exitCode':4,'decoded':None,'processReaped':True,'response':{'outcomeKnown':True,
            'error':{'code':'deadline-exceeded'},'data':{'terminalState':'deadline_exceeded',
            'consumption':{'cpuFuel':'1000','peakMemoryBytes':'10000000',
                'outboundRequests':0,'childCalls':0,'effectCount':0}}}}
        cases.require_deadline(row)
        changes=[(('exitCode',),0),(('decoded',),['forbidden-timer-elapsed-after-root-deadline']),
            (('processReaped',),False),(('response','outcomeKnown'),False),
            (('response','error','code'),'cancelled'),(('response','error','code'),'resource-exhausted'),
            (('response','data','terminalState'),'completed'),
            (('response','data','consumption','cpuFuel'),'0'),
            (('response','data','consumption','peakMemoryBytes'),'0'),
            *[(('response','data','consumption',key),1) for key in ('outboundRequests','childCalls','effectCount')]]
        for path,value in changes:
            changed=copy.deepcopy(row);parent=changed
            for key in path[:-1]:parent=parent[key]
            parent[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(WorkflowError):cases.require_deadline(changed)

    def test_normal_builder_profile_world_limits_and_captured_sdk_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=cases.base.project(root/'original');actual=cases.project(root/'actual')
            for name in ('capsule-project.json','wit/world.wit','src/default-client.ts'):
                self.assertEqual((original/name).read_bytes(),(actual/name).read_bytes())
            self.assertEqual((actual/'src/main.ts').read_bytes(),(cases.ROOT/cases.SOURCE).read_bytes())
            old=json.loads((original/'sdk-lock.json').read_bytes());new=json.loads((actual/'sdk-lock.json').read_bytes())
            new['template']['sourceDigest']=old['template']['sourceDigest'];self.assertEqual(old,new)

    def test_compilation_failure_cannot_reach_signing_or_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);product=root/'closed-product';product.write_bytes(b'not-executable')
            with patch.object(campaign,'native_inputs',return_value=({'capsule_contracts':product,'package':product},{})), \
                    patch.object(campaign,'build',side_effect=RuntimeError('ordinary-build-refused')), \
                    patch.object(campaign,'execute') as execute, self.assertRaisesRegex(RuntimeError,'ordinary-build-refused'):
                campaign.qualify(root/'inputs',root/'tools',root/'output')
            execute.assert_not_called()
            self.assertFalse((root/'output/qualification.json').exists())
