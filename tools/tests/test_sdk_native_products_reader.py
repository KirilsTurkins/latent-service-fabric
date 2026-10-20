"""Frozen producer data refuses source, stage, artifact and member drift."""
from __future__ import annotations
import copy
import io
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import sdk_native_products_reader as reader
from tools.phase2_operator_process import WorkflowError


class FrozenNativeReader(unittest.TestCase):
    def setUp(self):
        self.artifact = {'id': 1, 'size_in_bytes': 128, 'digest': 'sha256:'+'0'*64}
        identity = {'sha256': 'sha256:'+'1'*64, 'bytes': 1}
        self.receipts = {name: dict(identity) for name in ('native-products.json','source-inputs.json')}
        self.native = {'digest': 'source-fixture'}
        self.materials = {'fixture': dict(identity)}
        self.reader = reader.FrozenNativeProducts(source='2'*40, run=2, job=3,
            artifact=self.artifact, receipts=self.receipts, branch='fixture/native',
            stages=('rust-version','normal-host-build','positive-timer-observer-controls'))
        self.snapshot = {'native':self.native,'materials':self.materials}
        self.record = {'schemaVersion':'latent.sdk.native-products.v1','status':'built',
            'sourceRevision':'2'*40,'source':self.native,'materials':self.materials,
            'compiler':'rustc 1.97.1 (fixture)', 'products':{p:dict(identity) for p in reader.PRODUCTS},
            'commands':[{'stage':s,'exitCode':0,'seconds':1} for s in self.reader.stages],
            'profile':'normal-managed-guest-default-features','signedQualification':False,
            'guestComponentsCompiled':False,'historicalReceiptRewritten':False}

    def test_exact_frozen_record_is_accepted_without_a_guest_claim(self):
        self.reader.validate_record(self.record,self.snapshot,self.native,self.materials)
        self.artifact['id']=999
        self.receipts['native-products.json']['bytes']=999
        self.assertEqual(self.reader.artifact['id'],1)
        self.assertEqual(self.reader.receipts['native-products.json']['bytes'],1)

    def test_foreign_source_material_snapshot_and_product_are_refused(self):
        for key,value in [('sourceRevision','3'*40),('source',{}),('materials',{}),
                          ('products',{}),('signedQualification',True),('guestComponentsCompiled',True),
                          ('historicalReceiptRewritten',True),('profile','different')]:
            with self.subTest(key=key):
                changed=copy.deepcopy(self.record);changed[key]=value
                with self.assertRaises(WorkflowError):self.reader.validate_record(changed,self.snapshot,self.native,self.materials)
        with self.assertRaises(WorkflowError):self.reader.validate_record(self.record,{},self.native,self.materials)

    def test_failed_reordered_missing_and_nonfinite_command_outcomes_are_refused(self):
        variants=[]
        for key,value in [('exitCode',1),('seconds',-1),('seconds',math.nan),('seconds',1321)]:
            row=copy.deepcopy(self.record);row['commands'][0][key]=value;variants.append(row)
        row=copy.deepcopy(self.record);row['commands'].reverse();variants.append(row)
        row=copy.deepcopy(self.record);row['commands'].pop();variants.append(row)
        row=copy.deepcopy(self.record)
        for command in row['commands']:command['seconds']=1000
        variants.append(row)
        for row in variants:
            with self.assertRaises(WorkflowError):self.reader.validate_record(row,self.snapshot,self.native,self.materials)

    def test_moving_source_duplicate_stages_and_unbounded_pins_are_refused(self):
        arguments=dict(source='2'*40,run=2,job=3,artifact=self.artifact,receipts=self.receipts,
            branch='fixture/native',stages=('rust-version',))
        for key,value in [('source','development'),('run',True),('job',0),('stages',('same','same')),
                          ('artifact',{**self.artifact,'size_in_bytes':1024**3+1}),
                          ('receipts',{'native-products.json':self.receipts['native-products.json']})]:
            with self.subTest(key=key),self.assertRaises(WorkflowError):
                reader.FrozenNativeProducts(**{**arguments,key:value})

    def test_only_fixed_regular_members_are_materialized_and_rechecked(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            for name in reader.ALLOWED:archive.writestr(name,b'x')
            archive.writestr('unselected-private-or-foreign',b'foreign')
        with tempfile.TemporaryDirectory() as tmp,zipfile.ZipFile(data) as archive:
            self.assertEqual(set(self.reader.preflight(archive)),set(reader.ALLOWED))
            target=Path(tmp)/'known'
            self.reader.extract(archive,'native-products.json',target)
            self.assertEqual(target.read_bytes(),b'x')
            with self.assertRaises(WorkflowError):self.reader.extract(archive,'unselected-private-or-foreign',Path(tmp)/'foreign')
            with self.assertRaises(FileExistsError):self.reader.extract(archive,'native-products.json',target)

    def test_changed_receipt_preimage_is_refused_before_product_use(self):
        with patch.object(reader,'file_identity',return_value={'sha256':'sha256:'+'f'*64,'bytes':1}):
            with self.assertRaises(WorkflowError):self.reader.receipt_preimages(Path('unexecuted-fixture'))


if __name__ == '__main__':
    unittest.main()
