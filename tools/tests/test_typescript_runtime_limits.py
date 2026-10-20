"""Adversarial controls for independent ordinary-JavaScript limit evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from tools import typescript_runtime_limits as limits
from tools.phase2_operator_process import WorkflowError


def row(decoded=None, *, failure=None, peak=60000000):
    return {'exitCode':4 if failure else 0,'decoded':decoded,'processReaped':True,
        'response':{'outcomeKnown':True,'error':{'code':failure},'data':{'consumption':{
            'outboundRequests':0,'childCalls':0,'effectCount':0,'peakMemoryBytes':str(peak)}}}}


class RuntimeLimitTests(unittest.TestCase):
    def test_refusal_must_identify_the_selected_owner_and_real_admission(self):
        selected=limits.PROFILES[0];label=selected[3]
        self.assertEqual(limits.require_refusal(row([label+'|count=13|fresh=1']),selected,None)['admitted'],13)
        for invalid in (limits.PROFILES[1][3]+'|count=13|fresh=1',label+'|count=0|fresh=1',
                label+'|count=128|fresh=1',label+'|count=13|fresh=2','generic-resource-exhausted'):
            with self.subTest(invalid=invalid),self.assertRaises(WorkflowError):
                limits.require_refusal(row([invalid]),selected,None)
        for field in ('processReaped',):
            invalid=row([label+'|count=13|fresh=1']);invalid[field]=False
            with self.assertRaises(WorkflowError):limits.require_refusal(invalid,selected,None)

    def test_timer_cannot_pass_using_another_capacity_or_early_refusal(self):
        selected=limits.PROFILES[3];label=selected[3]
        self.assertEqual(limits.require_refusal(row([label+'|count=8|fresh=1']),selected,None)['admitted'],8)
        with self.assertRaises(WorkflowError):
            limits.require_refusal(row([label+'|count=7|fresh=1']),selected,None)

    def test_memory_requires_growth_over_same_budget_bootstrap_and_closed_terminal(self):
        selected=limits.PROFILES[4];bootstrap=row(['ready|fresh=1'],peak=9508080)
        for terminal in ('guest-trap','resource-exhausted'):
            self.assertEqual(limits.require_refusal(row(failure=terminal),selected,bootstrap)['memoryBudget'],67108864)
        for terminal in ('deadline-exceeded','cpu-fuel-exhausted','guest-runtime-error',None):
            with self.subTest(terminal=terminal),self.assertRaises(WorkflowError):
                limits.require_refusal(row(failure=terminal),selected,bootstrap)
        for peak in (9508080,10000000,67108865):
            with self.subTest(peak=peak),self.assertRaises(WorkflowError):
                limits.require_refusal(row(failure='guest-trap',peak=peak),selected,bootstrap)

    def test_memory_cannot_hide_side_effects_unknown_outcome_or_unreaped_process(self):
        selected=limits.PROFILES[4];bootstrap=row(peak=9508080)
        original=row(failure='guest-trap')
        mutations=[('processReaped',),('response','outcomeKnown'),
            *[('response','data','consumption',key) for key in ('outboundRequests','childCalls','effectCount')]]
        for path in mutations:
            invalid=copy.deepcopy(original);parent=invalid
            for key in path[:-1]:parent=parent[key]
            parent[path[-1]]=False if len(path)<3 else 1
            with self.subTest(path=path),self.assertRaises(WorkflowError):
                limits.require_refusal(invalid,selected,bootstrap)

    def test_fixed_profiles_preserve_unselected_limits_and_normal_manifest(self):
        for profile in limits.PROFILES:
            actual=limits.limits(profile)
            self.assertEqual({key:value for key,value in actual.items() if key not in profile[2]},
                {key:value for key,value in limits.base.OWNER_LIMITS.items() if key not in profile[2]})
        with self.assertRaises(WorkflowError):limits.limits(('arbitrary',1,{},None))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=limits.base.project(root/'original');actual=limits.project(root/'actual')
            self.assertEqual((actual/'capsule-project.json').read_bytes(),(original/'capsule-project.json').read_bytes())
            self.assertEqual((actual/'src/main.ts').read_bytes(),(limits.ROOT/limits.SOURCE).read_bytes())
            self.assertEqual(json.loads((actual/'sdk-lock.json').read_bytes())['template']['sourceDigest'],
                limits.digest((actual/'src/main.ts').read_bytes()))


if __name__=='__main__':unittest.main()
