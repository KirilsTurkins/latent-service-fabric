"""Host-only refusal controls; synthetic rows are never runtime qualifications."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import warnings
import zipfile
from tools.typescript_guest import borrow_signed_inputs as inputs
from tools.phase2_operator_process import WorkflowError


class BorrowSignedInputTests(unittest.TestCase):
    def test_canonical_digest_is_preserved_and_bare_or_bool_identity_refuses(self):
        identity = {'bytes': 1, 'sha256': 'sha256:' + 'a'*64}
        self.assertIs(inputs.canonical_identity(identity), identity)
        for value in ({'bytes':1,'sha256':'a'*64}, {'bytes':True,'sha256':'sha256:'+'a'*64},
                      {'bytes':64*1024**2+1,'sha256':'sha256:'+'a'*64}):
            with self.assertRaisesRegex(WorkflowError,'canonical-product-identity'):
                inputs.canonical_identity(value)

    def test_unpinned_success_material_refuses_before_api_or_output(self):
        with patch.object(inputs,'ARTIFACT',None), patch.object(inputs,'api',side_effect=AssertionError('API must remain lazy')):
            with self.assertRaisesRegex(WorkflowError,'actual-success-artifact-not-yet-pinned'):
                inputs.prepare(Path('never-created-borrow-signed-output'))

    def test_failed_or_wrong_scope_prerequisite_cannot_be_promoted(self):
        value = {'schemaVersion':'latent.typescript.owned-result-prerequisites.v1',
            'status':'failed','scope':inputs.SCOPE,'sourceCommit':inputs.HEAD,'sourceTree':'a'*40,
            **{name:False for name in inputs.FALSE_SCOPE}}
        for changed in (value,dict(value,status='passed',signedExecution=True),
                        dict(value,status='passed',scope='canonical-qualified')):
            with self.assertRaisesRegex(WorkflowError,'own-receipt-scope'): inputs.receipt(changed)

    def test_archive_duplicates_and_traversal_refuse_before_receipt_parsing(self):
        for names in (('../outside',), ('duplicate','duplicate')):
            data = io.BytesIO()
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                with zipfile.ZipFile(data,'w') as carrier:
                    for name in names: carrier.writestr(name,b'untrusted')
            with zipfile.ZipFile(io.BytesIO(data.getvalue())) as carrier:
                with self.assertRaisesRegex(WorkflowError,'archive-(member|bound)'): inputs.selected(carrier)
