"""Refuse incomplete scheduling evidence without executing native components."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import typescript_runtime_semantics as cases
from tools import qualify_typescript_runtime_semantics as campaign
from tools.phase2_operator_process import WorkflowError


class RuntimeSemanticsTests(unittest.TestCase):
    def test_negative_requires_real_known_reaped_execution_and_exact_fuel(self):
        row={'exitCode':4,'decoded':None,'processReaped':True,'response':{'outcomeKnown':True,
            'error':{'code':'resource-exhausted'},'data':{'consumption':{'cpuFuel':str(cases.FUEL),
                'peakMemoryBytes':'10000000','outboundRequests':0,'childCalls':0,'effectCount':0}}}}
        self.assertEqual(cases.require_negative(row,'resource-exhausted')['terminal'],'resource-exhausted')
        for path,value in [(('exitCode',),0),(('decoded',),['ready|fresh=1']),(('processReaped',),False),
                (('response','outcomeKnown'),False),(('response','error','code'),'deadline-exceeded'),
                (('response','data','consumption','cpuFuel'),'49999999'),
                (('response','data','consumption','peakMemoryBytes'),'0'),
                *[(('response','data','consumption',key),1) for key in ('outboundRequests','childCalls','effectCount')]]:
            changed=copy.deepcopy(row);parent=changed
            for key in path[:-1]:parent=parent[key]
            parent[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(WorkflowError):cases.require_negative(changed,'resource-exhausted')
        row['response']['error']['code']='guest-trap'
        self.assertFalse(cases.require_negative(row,'guest-trap')['callbackOriginProven'])

    def test_compiler_failure_cannot_reach_signing_or_claim_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            model=root/'never-executed';model.write_bytes(b'closed-test-product')
            with patch.object(campaign,'native_inputs',return_value=({'capsule_contracts':model,'package':model},{})), \
                    patch.object(campaign,'build',side_effect=RuntimeError('normal-compiler-failed')), \
                    patch.object(campaign,'execute') as execute, self.assertRaisesRegex(RuntimeError,'normal-compiler-failed'):
                campaign.qualify(root/'inputs',root/'tools',root/'output')
            execute.assert_not_called()
            self.assertFalse((root/'output/qualification.json').exists())

    def test_project_preserves_normal_profile_and_sdk_while_binding_exact_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=cases.base.project(root/'original');actual=cases.project(root/'actual')
            self.assertEqual((original/'capsule-project.json').read_bytes(),(actual/'capsule-project.json').read_bytes())
            self.assertEqual((original/'wit/world.wit').read_bytes(),(actual/'wit/world.wit').read_bytes())
            self.assertEqual((actual/'src/main.ts').read_bytes(),(cases.ROOT/cases.SOURCE).read_bytes())
            old=json.loads((original/'sdk-lock.json').read_bytes());new=json.loads((actual/'sdk-lock.json').read_bytes())
            new['template']['sourceDigest']=old['template']['sourceDigest'];self.assertEqual(old,new)
