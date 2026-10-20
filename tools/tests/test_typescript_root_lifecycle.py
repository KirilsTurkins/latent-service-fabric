"""Refuse false callback/cleanup credit without executing native guests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import typescript_root_lifecycle as cases
from tools import qualify_typescript_root_lifecycle as campaign
from tools.phase2_operator_process import WorkflowError

class RootLifecycleTests(unittest.TestCase):
    def test_callback_failure_requires_accepted_logging_known_reaped_execution_and_the_required_terminal(self):
        row={'exitCode':4,'decoded':None,'processReaped':True,'response':{'outcomeKnown':True,
            'error':{'code':'guest-trap'},'data':{'consumption':{'cpuFuel':'1000000','logBytes':'240',
                'peakMemoryBytes':'10000000','outboundRequests':0,'childCalls':0,'effectCount':0}}}}
        self.assertTrue(cases.require_outcome(row,'guest-trap',21)['callbackReached'])
        for path,value in [(('exitCode',),0),(('decoded',),['callback-throw-must-refuse']),
                (('processReaped',),False),(('response','outcomeKnown'),False),
                (('response','error','code'),'resource-exhausted'),
                (('response','data','consumption','logBytes'),'0'),
                (('response','data','consumption','logBytes'),'1025'),
                (('response','data','consumption','cpuFuel'),'0'),
                (('response','data','consumption','peakMemoryBytes'),'0'),
                *[(('response','data','consumption',key),1) for key in ('outboundRequests','childCalls','effectCount')]]:
            changed=copy.deepcopy(row);parent=changed
            for key in path[:-1]:parent=parent[key]
            parent[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(WorkflowError):cases.require_outcome(changed,'guest-trap',21)
        with self.assertRaises(WorkflowError):cases.require_outcome(row,'deadline-exceeded',0)
        with self.assertRaises(WorkflowError):cases.require_outcome(row,'guest-trap',0)

    def test_compiler_failure_cannot_reach_signing_or_claim_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);model=root/'never-executed';model.write_bytes(b'closed-test-product')
            with patch.object(campaign,'native_inputs',return_value=({'capsule_contracts':model,'package':model},{})), \
                    patch.object(campaign,'build',side_effect=RuntimeError('normal-compiler-failed')), \
                    patch.object(campaign,'execute') as execute,self.assertRaisesRegex(RuntimeError,'normal-compiler-failed'):
                campaign.qualify(root/'inputs',root/'tools',root/'output')
            execute.assert_not_called();self.assertFalse((root/'output/qualification.json').exists())

    def test_source_bound_profile_only_adds_the_declared_log_api_and_narrow_log_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=cases.base.project(root/'original');actual=cases.project(root/'actual')
            old=json.loads((original/'capsule-project.json').read_bytes());new=json.loads((actual/'capsule-project.json').read_bytes())
            self.assertEqual(new['limits']['logBytes'],1024)
            new['limits']['logBytes']=old['limits']['logBytes'];self.assertEqual(old,new)
            old=json.loads((original/'sdk-lock.json').read_bytes());new=json.loads((actual/'sdk-lock.json').read_bytes())
            new['template'].update(sourceDigest=old['template']['sourceDigest'],witDigest=old['template']['witDigest'])
            self.assertEqual(old,new)
            self.assertEqual((actual/'src/main.ts').read_bytes(),(cases.ROOT/cases.SOURCE).read_bytes())
            self.assertEqual((actual/'wit/world.wit').read_text().replace('    import '+cases.LOG+';\n',''),
                (original/'wit/world.wit').read_text())
            self.assertEqual((actual/'wit/deps/log/package.wit').read_bytes(),(cases.ROOT/'wit/platform/log/package.wit').read_bytes())
