"""Pinned public Java build reuse rejects foreign source and substituted layers."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import replay_java_resource_runtime as replay
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT,digest,read_json,write_json


class JavaResourceReplay(unittest.TestCase):
    def test_original_failed_job_and_exact_immutable_artifact_are_required(self):
        spec=read_json(ROOT/replay.SPEC)
        run={'id':spec['run'],'head_sha':spec['source'],'path':'.github/workflows/java-resource-runtime.yml',
            'event':spec.get('event','push'),'head_branch':'feat/java-resource-runtime-20261020','conclusion':'failure','status':'completed'}
        job={'id':spec['job'],'run_id':spec['run'],'head_sha':spec['source'],'conclusion':'failure','status':'completed'}
        artifact={**spec['artifact'],'workflow_run':{'id':spec['run'],'head_sha':spec['source']},'expired':False}
        replay.verify_origin(spec,run,job,artifact)
        for change in ('source','job','result','artifact','expired'):
            r,j,a=copy.deepcopy((run,job,artifact))
            if change=='source':r['head_sha']='0'*40
            elif change=='job':j['id']+=1
            elif change=='result':j['conclusion']='success'
            elif change=='artifact':a['digest']='sha256:'+'b'*64
            else:a['expired']=True
            with self.subTest(change=change),self.assertRaises(WorkflowError):replay.verify_origin(spec,r,j,a)

    def test_exact_members_refuse_same_size_substitution_missing_and_foreign_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);rows=[]
            for i in range(105):
                name=str(i)+'.txt';raw=('owned-'+str(i)).encode();(root/name).write_bytes(raw)
                rows.append({'path':name,'sha256':digest(raw),'bytes':len(raw)})
            spec={'members':rows};replay.verify_members(root,spec)
            (root/'0.txt').write_bytes(b'foreign')
            with self.assertRaises(WorkflowError):replay.verify_members(root,spec)
            (root/'0.txt').write_bytes(b'owned-0');(root/'104.txt').unlink()
            with self.assertRaises(WorkflowError):replay.verify_members(root,spec)
            (root/'104.txt').write_bytes(b'owned-104');(root/'foreign.txt').write_bytes(b'extra')
            with self.assertRaises(WorkflowError):replay.verify_members(root,spec)

    def test_only_original_wit_and_resource_layer_bytes_can_be_restored(self):
        for change in ('valid','foreign','tampered'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);files={name:b'original-wit' for name in replay.WIT}
                files.update({'resources/objects/'+digest(raw)[7:]:raw for raw in replay.qualification.fixture.DATA.values()})
                if change=='foreign':files['private/workfile.bin']=b'not-owned'
                for name,raw in files.items():
                    p=root/'package/layers'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
                write_json(root/'package-inputs.json',{name:{'digest':digest(raw),'size':len(raw)} for name,raw in files.items()})
                if change=='tampered':(root/'package/layers/wit/world.wit').write_bytes(b'substituted')
                if change=='valid':
                    restored=replay.restore_original_layers(root);self.assertEqual(set(restored),set(files))
                    for name,raw in files.items():self.assertEqual((root/name).read_bytes(),raw)
                else:
                    with self.assertRaises(WorkflowError):replay.restore_original_layers(root)

    def test_nonreader_current_material_drift_cannot_claim_the_original_build(self):
        spec=read_json(ROOT/replay.SPEC)
        record={'source':spec.get('checkoutSource',spec['source']),'status':'failed','stage':spec.get('stage','one-fresh-offline-fiber-io-component'),
            'errorCategory':'WorkflowError','guestComponentsCompiled':2,'unsignedCompilerControlComponents':1,
            'engineRebuilt':False,'nativeProductsBuilt':0,'materials':{'owned/fixture.py':{'sha256':digest(b'original'),'bytes':8}}}
        with patch.object(replay.qualification,'MATERIALS',('owned/fixture.py',)),patch.object(replay.subprocess,'check_output',return_value=b'original'),patch.object(replay,'file_identity',return_value={'sha256':digest(b'changed!'),'bytes':8}):
            with self.assertRaisesRegex(WorkflowError,'unchanged-exercised-source'):replay.original_materials(record,spec)


if __name__=='__main__':unittest.main()
