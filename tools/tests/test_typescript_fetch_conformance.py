"""Pending-owner and exact-source controls; signed qualification is separate."""
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import typescript_fetch_conformance as cases
from tools import qualify_typescript_fetch_conformance as qualification
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest


class FetchConformanceTests(unittest.TestCase):
    def test_installed_deployment_shutdown_requires_real_reap_and_clean_report_without_new_mutation(self):
        client=SimpleNamespace(call=unittest.mock.Mock(side_effect=AssertionError('teardown performed an unrelated control mutation')))
        node=object()
        for reaped,clean in [(True,True),(False,True),(True,False)]:
            record={'reaped':reaped,'record':{'clean':clean}}
            with self.subTest(reaped=reaped,clean=clean),patch.object(qualification,'stop') as stop, \
                    patch.object(qualification,'stopped_record',return_value=record):
                if reaped and clean:self.assertEqual(qualification.shutdown_owned_node(client,node),record)
                else:
                    with self.assertRaisesRegex(WorkflowError,'clean-shutdown'):
                        qualification.shutdown_owned_node(client,node)
                stop.assert_called_once_with(client,node)
        client.call.assert_not_called()

    def test_broader_fixture_policy_replaces_only_its_verified_first_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            class Client:
                directory=Path(temporary)
                calls=0
                def call(self,*arguments):
                    self.calls+=1
                    if 'get' in arguments:
                        return {'outcomeKnown':True,'category':'success','data':{'policy':{
                            'id':'http-allow','tenant':'examples','recordKind':'policy','revoked':False,
                            'generation':'9','document':{'rules':[{'capability':cases.base.HTTP,
                                'publications':['publication'],'services':[cases.base.SERVICE],
                                'resources':{'kind':'http','origins':[{}],'methods':['GET'],
                                    'paths':['/conformance/json','/conformance/status/404'],'pathPrefixes':[]}}]}}}}
                    expected=arguments[arguments.index('--expected-generation')+1]
                    if expected != 9:raise WorkflowError('stale-policy-generation')
                    document=json.loads(Path(arguments[arguments.index('--file')+1]).read_bytes())
                    self.document=document
                    operation=arguments[arguments.index('--operation-id')+1]
                    return {'outcomeKnown':True,'data':{'receipt':{'operationId':operation,'generation':'10'}}}
            client=Client()
            with patch.object(cases.base,'grants',return_value=(['runtime'],['authorized'])) as original:
                self.assertEqual(cases.grants(client,None,'publication',{'primary':{},'secondary':{}}),(['runtime'],['authorized']))
            original.assert_called_once()
            self.assertEqual(client.calls,2)
            self.assertEqual(client.document['rules'][0]['resources']['pathPrefixes'],[])
            class Foreign(Client):
                def call(self,*arguments):
                    row=super().call(*arguments)
                    if 'get' in arguments:row['data']['policy']['document']['rules'][0]['publications']=['foreign']
                    return row
            foreign=Foreign()
            with patch.object(cases.base,'grants',return_value=(['runtime'],['authorized'])):
                with self.assertRaisesRegex(WorkflowError,'original-policy-document'):
                    cases.grants(foreign,None,'publication',{'primary':{},'secondary':{}})
            self.assertEqual(foreign.calls,1)

    def test_cold_admission_preserves_the_existing_invocation_watchdog(self):
        client=SimpleNamespace(deadline=1000,invocation_timeout_millis=120000)
        process=SimpleNamespace(owner=SimpleNamespace(exited=unittest.mock.Mock(side_effect=[False,True])),drain=lambda:None)
        peer=SimpleNamespace(poll=lambda _:None,gates=lambda:())
        with patch.object(cases.time,'monotonic',side_effect=[0,20]),patch.object(cases,'finish_call',return_value={'finished':True}):
            self.assertEqual(cases.drive(client,process,peer),{'finished':True})

    def test_separate_fixture_preserves_original_budget_and_records_exact_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            old=cases.base.project(root/'original')
            new=cases.project(root/'conformance')
            before=json.loads((old/'capsule-project.json').read_bytes())
            after=json.loads((new/'capsule-project.json').read_bytes())
            self.assertEqual(before['limits']['outboundRequests'],1)
            self.assertEqual(after['limits']['outboundRequests'],2)
            after['limits']['outboundRequests']=1
            self.assertEqual(after,before)
            source=(new/'src/main.ts').read_bytes()
            self.assertEqual(source,(cases.ROOT/cases.SOURCE).read_bytes())
            self.assertEqual(json.loads((new/'sdk-lock.json').read_bytes())['template']['sourceDigest'],digest(source))

    def test_case_plan_keeps_exact_contact_charge_and_distinct_error_semantics(self):
        rows=cases.vectors();mapped={row[0]:row for row in rows}
        self.assertEqual(len(rows),25)
        self.assertEqual(len(mapped),25)
        self.assertEqual(sum(row[4] for row in rows),22)
        self.assertEqual(mapped['denied-target-no-contact'][4],0)
        self.assertEqual(mapped['redirect'][4],2)
        self.assertEqual(mapped['redirect-denied'][4],1)
        self.assertEqual(mapped['uncertain-post-no-replay'][3:5],('uncertain:true',1))
        self.assertTrue(mapped['http404-response'][3].startswith('404:'))
        self.assertTrue(mapped['http500-response'][3].startswith('500:'))
        self.assertEqual({row[0] for row in rows if row[0].startswith('method-')},
            {'method-get','method-head','method-post','method-put','method-patch','method-delete','method-options'})

    def test_early_root_result_cannot_pass_as_drained_pending_work(self):
        owner=SimpleNamespace(exited=unittest.mock.Mock(side_effect=[False,True]))
        process=SimpleNamespace(owner=owner,drain=lambda:None)
        peer=SimpleNamespace(poll=lambda _:None,gates=lambda:(object(),),release=unittest.mock.Mock())
        client=SimpleNamespace(deadline=time.monotonic()+10,invocation_timeout_millis=120000)
        with patch.object(cases,'finish_call',return_value={}),self.assertRaisesRegex(WorkflowError,'pending-gate-required'):
            cases.drive(client,process,peer,release_after=1)
        peer.release.assert_not_called()

    def test_absent_provider_wait_cannot_satisfy_abort_or_timeout_control(self):
        process=SimpleNamespace(owner=SimpleNamespace(exited=lambda:True))
        client=SimpleNamespace(deadline=time.monotonic()+10,invocation_timeout_millis=120000)
        peer=SimpleNamespace(gates=lambda:())
        with patch.object(cases,'finish_call',return_value={}),self.assertRaisesRegex(WorkflowError,'pending-gate-required'):
            cases.drive(client,process,peer,release_after=.15)

    def test_pending_barrier_refuses_completion_without_a_real_gate(self):
        process=SimpleNamespace(owner=SimpleNamespace(exited=lambda:True))
        client=SimpleNamespace(deadline=time.monotonic()+10,invocation_timeout_millis=120000)
        peer=SimpleNamespace(gates=lambda:())
        with self.assertRaisesRegex(WorkflowError,'real-pending-required'):
            cases.wait_gate(client,process,peer)

    def test_compiler_failure_cannot_enter_signing_or_native_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            native={name:root/name for name in cases.base.PRODUCTS}
            for path in native.values():path.write_bytes(b'bounded-test-input')
            with patch.object(qualification,'native_inputs',return_value=(native,{'historical':True})), \
                    patch.object(qualification,'build',side_effect=ValueError('component-build-failed')), \
                    patch.object(qualification,'execute') as execute:
                with self.assertRaisesRegex(ValueError,'component-build-failed'):
                    qualification.qualify(root/'acquired',root/'tools',root/'result')
                execute.assert_not_called()
