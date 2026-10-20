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
        client=SimpleNamespace(deadline=time.monotonic()+10)
        with patch.object(cases,'finish_call',return_value={}),self.assertRaisesRegex(WorkflowError,'pending-gate-required'):
            cases.drive(client,process,peer,release_after=1)
        peer.release.assert_not_called()

    def test_absent_provider_wait_cannot_satisfy_abort_or_timeout_control(self):
        process=SimpleNamespace(owner=SimpleNamespace(exited=lambda:True))
        client=SimpleNamespace(deadline=time.monotonic()+10)
        peer=SimpleNamespace(gates=lambda:())
        with patch.object(cases,'finish_call',return_value={}),self.assertRaisesRegex(WorkflowError,'pending-gate-required'):
            cases.drive(client,process,peer,release_after=.15)

    def test_pending_barrier_refuses_completion_without_a_real_gate(self):
        process=SimpleNamespace(owner=SimpleNamespace(exited=lambda:True))
        client=SimpleNamespace(deadline=time.monotonic()+10)
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
