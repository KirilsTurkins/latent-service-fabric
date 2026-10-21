"""Setup ownership and unchanged execution limits; no native execution claim."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import java_http_release_preparation as preparation
from tools.phase2_operator_process import WorkflowError

PUBLICATION = 'publication:sha256:'+'a'*64
COMPONENT = 'sha256:'+'b'*64


class JavaHttpReleasePreparationTests(unittest.TestCase):
    def fixture(self, root):
        lifecycle = {'outcomeKnown': True, 'data': {'status': {
            'eligibility': 'RELEASE_LIVE_ELIGIBILITY_ELIGIBLE', 'record': {
                'publication': {'id': PUBLICATION, 'tenant': 'examples'}, 'tenant': 'examples',
                'componentDigest': COMPONENT, 'state': 'RELEASE_LIFECYCLE_STATE_ADMITTED',
                'generation': str(2**64-1)}}}}
        response = {'schemaVersion': 'latent.cli.result.v1', 'category': 'success',
            'command': 'release prepare', 'outcomeKnown': True, 'error': None, 'data': {
                'publication': {'id': PUBLICATION, 'tenant': 'examples'},
                'lifecycleGeneration': str(2**64-1), 'componentDigest': COMPONENT,
                'prepared': True, 'executionAuthorized': False}}
        client = SimpleNamespace(call=Mock(return_value=lifecycle), calls=2, retained=0,
            invocation_timeout_millis=120000, control_timeout_millis=15000, deadline=120.0,
            cancellation=SimpleNamespace(check=Mock()), node=None, config=root/'operator.json',
            executable='owned-latent', directory=root, environment={'PATH': 'fixed'},
            last_exit_status=None, failed_call=None)
        return client, lifecycle, response

    def execute(self, client, response, root, code=0):
        process = SimpleNamespace(complete=Mock(return_value=SimpleNamespace(returncode=code,
            stdout=json.dumps(response).encode(), stderr=b'')), close=Mock())
        with patch('tools.phase2_operator_process.Process', return_value=process) as spawn, \
                patch('tools.phase2_operator_process.time.monotonic', return_value=100.0):
            result = preparation.prepare(client, PUBLICATION, 'examples', COMPONENT, root)
        return result, process, spawn

    def test_exact_current_lifecycle_setup_is_clipped_to_original_campaign_and_preserves_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);client,lifecycle,response=self.fixture(root)
            result,process,spawn=self.execute(client,response,root)
            client.call.assert_called_once_with('release','lifecycle','--publication',PUBLICATION)
            process.complete.assert_called_once_with(120.0)
            process.close.assert_called_once_with()
            argv=spawn.call_args.args[0]
            self.assertEqual(argv, ['owned-latent','--output','json','--config',str(root/'operator.json'),
                '--profile','operator','--rpc-timeout-ms','300000','release','prepare','--publication',PUBLICATION,
                '--lifecycle-generation',str(2**64-1),'--maximum-wait-ms','300000'])
            self.assertEqual(client.calls,3)
            self.assertEqual((client.deadline,client.invocation_timeout_millis,client.control_timeout_millis),
                (120.0,120000,15000))
            record=json.loads((root/result['path']).read_bytes())
            self.assertFalse(record['qualification'])
            self.assertFalse(record['response']['data']['executionAuthorized'])
            self.assertEqual(record['setupProcessTimeoutMillis'],305000)
            self.assertEqual(record['response'],response)

    def test_stale_foreign_missing_or_non_admitted_lifecycle_never_starts_preparation(self):
        for field,value in (('tenant','foreign'),('publication',{'id':PUBLICATION,'tenant':'foreign'}),
                ('componentDigest','sha256:'+'c'*64),('state','RELEASE_LIFECYCLE_STATE_REVOKED')):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);client,lifecycle,_=self.fixture(root)
                lifecycle['data']['status']['record'][field]=value
                with patch('tools.phase2_operator_process.Process') as spawn,self.assertRaises(WorkflowError):
                    preparation.prepare(client,PUBLICATION,'examples',COMPONENT,root)
                spawn.assert_not_called()
        for value in (None,{},'unavailable'):
            with self.subTest(status=value),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);client,lifecycle,_=self.fixture(root);lifecycle['data']['status']=value
                with patch('tools.phase2_operator_process.Process') as spawn,self.assertRaises(WorkflowError):
                    preparation.prepare(client,PUBLICATION,'examples',COMPONENT,root)
                spawn.assert_not_called()

    def test_generation_is_exact_positive_decimal_u64_before_starting_setup(self):
        for generation in (None,True,1,'0','01','-1',str(2**64),'١'):
            with self.subTest(generation=generation),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);client,lifecycle,_=self.fixture(root)
                lifecycle['data']['status']['record']['generation']=generation
                with patch('tools.phase2_operator_process.Process') as spawn,self.assertRaises(WorkflowError):
                    preparation.prepare(client,PUBLICATION,'examples',COMPONENT,root)
                spawn.assert_not_called()

    def test_preparation_failure_is_retained_once_and_never_becomes_ready_or_invocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);client,_,response=self.fixture(root)
            response.update(category='platform-failure',outcomeKnown=False,
                error={'code':'deadline-exceeded'},data={})
            with self.assertRaisesRegex(WorkflowError,'exact-ready-result'):
                self.execute(client,response,root,4)
            record=json.loads((root/'examples-preparation.json').read_bytes())
            self.assertEqual(record['response'],response)
            self.assertFalse(record['qualification'])
            self.assertEqual(client.calls,3)
            client.call.assert_called_once()

    def test_mismatched_ready_selection_or_authority_and_extra_fields_are_refused_after_retention(self):
        for field,value in (('publication',{'id':PUBLICATION,'tenant':'foreign'}),
                ('lifecycleGeneration','1'),('componentDigest','sha256:'+'c'*64),
                ('prepared',False),('prepared',1),('executionAuthorized',True),
                ('executionAuthorized',0),('unexpected','extra')):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);client,_,response=self.fixture(root);response['data'][field]=value
                with self.assertRaisesRegex(WorkflowError,'exact-ready-result'):
                    self.execute(client,response,root)
                self.assertEqual(json.loads((root/'examples-preparation.json').read_bytes())['response'],response)

    def test_unknown_lifecycle_or_changed_execution_profile_is_refused_before_setup(self):
        for field,value in (('invocation_timeout_millis',300000),('control_timeout_millis',125000)):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);client,_,_=self.fixture(root);setattr(client,field,value)
                with patch('tools.phase2_operator_process.Process') as spawn,self.assertRaises(WorkflowError):
                    preparation.prepare(client,PUBLICATION,'examples',COMPONENT,root)
                spawn.assert_not_called();client.call.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);client,lifecycle,_=self.fixture(root);lifecycle['outcomeKnown']=False
            with patch('tools.phase2_operator_process.Process') as spawn,self.assertRaises(WorkflowError):
                preparation.prepare(client,PUBLICATION,'examples',COMPONENT,root)
            spawn.assert_not_called()

    def test_tenant_preparation_is_explicit_and_non_boolean_selection_is_rejected_before_output(self):
        from tools import java_http_tenant_node as tenants
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for selected in (None,0,1,'true'):
                with self.subTest(selected=selected),self.assertRaisesRegex(WorkflowError,'preparation-selection'):
                    tenants.run(root,{},root/'output',deadline=10**12,prepare_publications=selected)
                self.assertFalse((root/'output').exists())
