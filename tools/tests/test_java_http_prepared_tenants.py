"""Current producer/input fences and a source-preserving finite node-only replay."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import qualify_java_http_prepared_tenants as campaign
from tools.phase2_operator_process import WorkflowError


class JavaHttpPreparedTenantTests(unittest.TestCase):
    def current_fixture(self, root):
        materials = {}
        names = [*campaign.NATIVE_MATERIALS, 'schemas/fixture.json',
            'examples/echo-contract/wit/world.wit',
            *(f'wit/f{i}.wit' for i in range(104)), *(f'api/proto/f{i}.proto' for i in range(20))]
        self.assertEqual(len(names), 134)
        for name in names:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixed')
            materials[name]=campaign.file_identity(path)
        prepared=root/'prepared';prepared.mkdir()
        record={'sourceRevision':campaign.native.SOURCE,'source':{'identity':'native'},'materials':materials}
        (prepared/'native-products.json').write_text(json.dumps(record))
        return prepared,record

    def test_current_native_checks_every_physical_protocol_material_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);prepared,record=self.current_fixture(root)
            with patch.object(campaign,'ROOT',root),patch.object(campaign,'source_identity',return_value=record['source']):
                self.assertEqual(campaign.current_native(prepared)['materials'],record['materials'])
                (root/'api/proto/f19.proto').write_bytes(b'tampered')
                with self.assertRaisesRegex(WorkflowError,'protocol-material-drift'):
                    campaign.current_native(prepared)
                (root/'api/proto/f19.proto').unlink()
                with self.assertRaisesRegex(WorkflowError,'protocol-material-drift'):
                    campaign.current_native(prepared)

    def test_foreign_current_native_source_or_tuple_refuses_before_material_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);prepared,record=self.current_fixture(root)
            for key,value in (('sourceRevision','1'*40),('source',{'identity':'foreign'})):
                changed=copy.deepcopy(record);changed[key]=value
                (prepared/'native-products.json').write_text(json.dumps(changed))
                with patch.object(campaign,'ROOT',root),patch.object(campaign,'source_identity',return_value=record['source']), \
                        patch.object(campaign,'inventory') as inventory,self.assertRaisesRegex(WorkflowError,'native-source-drift'):
                    campaign.current_native(prepared)
                inventory.assert_not_called()

    def execute(self, root, *, mutation=False, failure=None):
        prepared=root/'component';prepared.mkdir();(prepared/'build').mkdir()
        (root/'fixture.py').write_text('unchanged')
        compiled={'component':{'digest':'compiled-original'}}
        retrieval={'schemaVersion':'latent.java.http.retained-component.v1',
            'artifact':campaign.component.ARTIFACT,'run':campaign.component.RUN,'job':campaign.component.JOB,
            'originalOutcome':'failed-before-publication','wholeArchiveSha256Verified':True,
            'historicalReceiptRewritten':False,'build':compiled}
        (prepared/'retrieval.json').write_text(json.dumps(retrieval))
        observed={}
        def node(build,products,output,**kwargs):
            self.assertEqual(build,prepared/'build')
            self.assertEqual(set(products),{'latent','latentd','capsule_authoring'})
            observed.update(kwargs)
            self.assertIs(kwargs['prepare_publications'],True)
            self.assertGreater(kwargs['deadline'],time.monotonic()+340)
            self.assertLessEqual(kwargs['deadline'],time.monotonic()+350)
            if failure is not None:raise failure
            output.mkdir();(output/'qualification.json').write_text('{"status":"passed"}')
            if mutation:(root/'fixture.py').write_text('changed during execution')
            return {'status':'passed','invocations':12,'cases':[{}]*12,'httpContacts':10,
                'preparation':{'examples':{},'foreign':{}}}
        with patch.object(campaign,'ROOT',root),patch.object(campaign,'MATERIALS',('fixture.py',)), \
                patch.object(campaign.native,'verify_prepared',return_value={'history':'current-native'}), \
                patch.object(campaign,'current_native',return_value={'proof':'native-and-protocol'}), \
                patch.object(campaign.component,'validate',return_value=compiled), \
                patch.object(campaign.native,'native_products',return_value={k:root/k for k in
                    ('latent','latentd','capsule_authoring','package','capsule_contracts')}), \
                patch.object(campaign,'tenant_controls',side_effect=node), \
                patch.object(campaign.subprocess,'check_output',return_value='2'*40):
            return campaign.run(root/'output',root/'native',prepared),observed

    def test_only_unchanged_twelve_case_prepared_programme_writes_source_attributed_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,observed=self.execute(Path(temporary))
            self.assertEqual(result['tenantProgramme']['invocations'],12)
            self.assertEqual(result['tenantProgramme']['httpContacts'],10)
            self.assertEqual(result['componentSource'],campaign.component.SOURCE)
            self.assertIs(result['nativeRecompiledByConsumer'],False)
            self.assertIs(result['componentRecompiledByConsumer'],False)
            self.assertIs(result['full688Qualified'],False)
            self.assertEqual(set(observed),{'deadline','prepare_publications'})

    def test_execution_failure_identity_and_post_execution_source_refusal_never_become_success(self):
        cause=WorkflowError('original-execution-failure')
        for mutation,failure in ((True,None),(False,cause)):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                with self.assertRaises(WorkflowError) as raised:self.execute(root,mutation=mutation,failure=failure)
                if failure is not None:self.assertIs(raised.exception,cause)
                self.assertFalse((root/'output/qualification.json').exists())
                self.assertEqual(json.loads((root/'output/FAILED.json').read_bytes())['status'],'failed')
