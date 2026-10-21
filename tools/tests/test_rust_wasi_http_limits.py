"""Failure-injection and data models only; never new limit qualification."""
import copy
import json
from pathlib import Path
import unittest

from tools import qualify_rust_wasi_http_limits as qualifier
from tools import rust_wasi_http_limit_node as node
from tools.dotnet_guest.internal_io import encoded_integer


INPUTS = json.loads((Path(__file__).parent/'fixtures/rust-http-limit-model-inputs.json').read_bytes())


class RustHttpLimitControls(unittest.TestCase):
    def test_only_the_named_owner_ceiling_changes_and_defaults_are_preserved(self):
        value={'providers':{'activationRuntime':{'limits':dict(node.original.RUNTIME_LIMITS)},
            'httpStreaming':{'unmodified':'provider'}},'cells':[{'capacity':1,'queueCapacity':2}],
            'engine':{'activationStackAccounting':'activation-owned-v1'}}
        for phase in node.PHASES:
            selected=node.limits_configuration(value,phase)
            self.assertEqual(value['providers']['activationRuntime']['limits'],node.original.RUNTIME_LIMITS)
            self.assertEqual(selected['cells'],value['cells'])
            self.assertEqual(selected['engine'],value['engine'])
            changed={k for k in node.original.RUNTIME_LIMITS
                if selected['providers']['activationRuntime']['limits'][k]!=node.original.RUNTIME_LIMITS[k]}
            self.assertEqual(changed,{'tasks'} if phase=='task-one' else {'timers'} if phase=='timer-one' else set())
        for bad in (None,True,'tasks','timer-zero','memory','unknown'):
            with self.subTest(bad=bad),self.assertRaises(RuntimeError):node.limits_configuration(value,bad)
        stale=copy.deepcopy(value);stale['providers']['activationRuntime']['limits']['waits']=8
        with self.assertRaises(RuntimeError):node.limits_configuration(stale,'task-one')

    def test_task_one_requires_one_actual_response_and_the_exact_original_error(self):
        actual=INPUTS['waki'];row=copy.deepcopy(actual['invocation'])
        with self.assertRaisesRegex(RuntimeError,'one-retained-task'):
            node.task_outcome(row,actual['selectedRevision'],actual['budget'])
        self.assertIn(':capacity:8:',row['decoded'][0]['ok'])
        row['decoded'][0]['ok']=row['decoded'][0]['ok'].replace(':capacity:8:',':capacity:1:')
        row['response']['data']['consumption']['outboundRequests']=1
        result=node.task_outcome(row,actual['selectedRevision'],actual['budget'])
        self.assertEqual(result['acceptedResponses'],1)
        self.assertFalse(result['publicErrorAloneProvesOwnerKind'])
        for change in ('accepted-zero','outbound','error-kind','stale-revision'):
            bad=copy.deepcopy(row);revision=copy.deepcopy(actual['selectedRevision'])
            if change=='accepted-zero':bad['decoded'][0]['ok']=bad['decoded'][0]['ok'].replace(':capacity:1:',':capacity:0:')
            elif change=='outbound':bad['response']['data']['consumption']['outboundRequests']=2
            elif change=='error-kind':bad['decoded'][0]['ok']=bad['decoded'][0]['ok'].replace('latent-runtime-resource-exhausted','latent-runtime-permission-denied')
            else:revision['routeGeneration']='999'
            with self.subTest(change=change),self.assertRaises(RuntimeError):
                node.task_outcome(bad,revision,actual['budget'])

    def test_timer_one_requires_its_real_pending_count_second_start_and_precise_trap(self):
        actual=INPUTS['golem'];row=copy.deepcopy(actual['invocation'])
        positive={'transitiveTimer':{'waitPending':copy.deepcopy(INPUTS['pendingTimer'])}}
        with self.assertRaisesRegex(RuntimeError,'one-live-timer'):
            node.timer_outcome(row,actual['selectedRevision'],actual['budget'],positive)
        row['response']['data']['consumption']['outboundRequests']=2
        result=node.timer_outcome(row,actual['selectedRevision'],actual['budget'],positive)
        self.assertFalse(result['trapInstructionProved'])
        self.assertFalse(result['genericTrapAloneProvesOwnerKind'])
        for kind in ('zero-timer','bool-timer','different-trap','deadline','zero-fuel','wrong-outbound'):
            bad=copy.deepcopy(row);witness=copy.deepcopy(positive)
            if kind=='zero-timer':witness['transitiveTimer']['waitPending']['timers']=0
            elif kind=='bool-timer':witness['transitiveTimer']['waitPending']['timers']=True
            elif kind=='different-trap':bad['response']['error']['details'][1]['fields']['kind']='out-of-bounds-memory'
            elif kind=='deadline':bad['response']['error']['code']='deadline-exceeded'
            elif kind=='zero-fuel':bad['response']['data']['consumption']['cpuFuel']='0'
            else:bad['response']['data']['consumption']['outboundRequests']=1
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):
                node.timer_outcome(bad,actual['selectedRevision'],actual['budget'],witness)

    def test_memory_requires_the_typed_producer_detail_and_no_effect(self):
        actual=INPUTS['golem'];row=copy.deepcopy(actual['invocation']);budget=copy.deepcopy(actual['budget'])
        budget['memoryBytes']=3*1024**2
        row['response']['error']={'code':'resource-exhausted','details':[
            {'kind':'activation.memory-exhausted','fields':{'cell_id':'original-cell'}}]}
        row['response']['data']['terminalState']='resource_exhausted'
        row['response']['data']['consumption'].update(outboundRequests=0,cpuFuel='0',peakMemoryBytes='0')
        self.assertFalse(node.memory_outcome(row,actual['selectedRevision'],budget)['genericResourceErrorAccepted'])
        for change in ('generic-capacity','fuel-detail','duplicate-memory','peer-start','bool-start','over-budget','wrong-terminal'):
            bad=copy.deepcopy(row)
            if change=='generic-capacity':bad['response']['error']['details']=[]
            elif change=='fuel-detail':bad['response']['error']['details'][0]['kind']='activation.fuel-exhausted'
            elif change=='duplicate-memory':bad['response']['error']['details']*=2
            elif change=='peer-start':bad['response']['data']['consumption']['outboundRequests']=1
            elif change=='bool-start':bad['response']['data']['consumption']['outboundRequests']=False
            elif change=='over-budget':bad['response']['data']['consumption']['peakMemoryBytes']=str(budget['memoryBytes']+1)
            else:bad['response']['data']['terminalState']='guest_trap'
            with self.subTest(change=change),self.assertRaises(RuntimeError):
                node.memory_outcome(bad,actual['selectedRevision'],budget)

    def test_fixed_memory_shape_checks_count_flags_and_all_original_minima(self):
        def model(changed=None):
            component=bytearray(b'\0asm\x0d\0\x01\0')
            for index in range(9):
                core=bytearray(b'\0asm\x01\0\0\0')
                if index in (0,3,6):
                    pages=19 if index==3 else 17
                    if changed==index:pages+=1
                    payload=b'\x01\x00'+encoded_integer(pages)
                    core+=b'\x05'+encoded_integer(len(payload))+payload
                component+=b'\x01'+encoded_integer(len(core))+core
            return bytes(component)
        shape=qualifier.memory_shape(model())
        self.assertEqual(shape['definedMinimumBytes'],3473408)
        self.assertTrue(shape['actualTypedMemoryTerminalStillRequired'])
        self.assertGreater(shape['definedMinimumBytes'],shape['lowerRequestedBytes'])
        for index in (0,3,6):
            with self.subTest(index=index),self.assertRaises(RuntimeError):qualifier.memory_shape(model(index))
        with self.assertRaises(ValueError):qualifier.memory_shape(b'not-the-authenticated-component')

    def test_cleanup_keeps_the_primary_and_still_refuses_on_success(self):
        observations=[];secondary=OSError('controlled cleanup refusal')
        def broken():raise secondary
        cleanup=node.owned_cleanup(broken,'node',observations)
        primary=RuntimeError('original failure')
        try:
            raise primary
        except RuntimeError as observed:
            cleanup();self.assertIs(observed,primary)
        self.assertEqual(observations,[{'owner':'node','cleanupRefused':True,'primaryPreserved':True}])
        with self.assertRaises(OSError) as caught:cleanup()
        self.assertIs(caught.exception,secondary)


if __name__=='__main__':unittest.main()
