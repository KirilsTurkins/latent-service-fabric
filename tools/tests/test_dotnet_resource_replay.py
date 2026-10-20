"""Exact retained AOT inputs remain distinct from the repaired controller."""
import copy
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools import replay_dotnet_resource_runtime as replay
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest,write_json


class ManagedResourceReplay(unittest.TestCase):
    def test_only_the_exact_failed_build_producer_can_supply_the_fresh_component(self):
        metadata={**replay.ARTIFACT,'expired':False,'workflow_run':{'id':replay.RUN,'head_sha':replay.SOURCE}}
        job={'id':replay.JOB,'run_id':replay.RUN,'head_sha':replay.SOURCE,'status':'completed','conclusion':'failure'}
        replay.validate_origin(metadata,job)
        for change in ('size','digest','expired','source','run','job','conclusion'):
            m,j=copy.deepcopy((metadata,job))
            if change=='size':m['size_in_bytes']+=1
            elif change=='digest':m['digest']='sha256:'+'0'*64
            elif change=='expired':m['expired']=True
            elif change=='source':m['workflow_run']['head_sha']='0'*40
            elif change=='run':j['run_id']+=1
            elif change=='job':j['id']+=1
            else:j['conclusion']='success'
            with self.subTest(change=change),self.assertRaisesRegex(WorkflowError,'exact-failed-producer'):
                replay.validate_origin(m,j)

    def test_original_compiler_native_ancestry_cannot_be_relabelled_as_a_new_replay_host(self):
        from unittest.mock import patch
        products=replay.products
        identity={'sha256':'sha256:'+'a'*64,'bytes':1}
        native={'schemaVersion':'latent.sdk.phase-native-products.v1','compiledSource':products.SOURCE,
            'compiledTree':'original-tree','producerRun':products.RUN,'producerJob':products.JOB,
            'producerReceipt':products.RECEIPTS['native-products.json'],
            'sourceSnapshot':products.RECEIPTS['source-inputs.json'],
            'origin':{'artifact':products.ARTIFACT['id'],'archiveDigest':products.ARTIFACT['digest']},
            'signedQualification':False,'guestComponentsCompiledByProducer':False,
            'historicalNormalReceiptCreated':False,'products':{name:dict(identity) for name in products.PRODUCTS}}
        original={'compiledNative':native,'consumerNativeSource':{'original':'consumer'}}
        with patch.object(replay.subprocess,'check_output',return_value=b'original-tree\n'), \
             patch.object(replay,'git_source_identity',return_value={'original':'consumer'}):
            self.assertEqual(replay.original_native_ancestry(original),native)
            for key,value in [('compiledSource','f'*40),('producerJob',1),('producerReceipt',identity),
                              ('signedQualification',True),('products',{})]:
                changed=copy.deepcopy(original);changed['compiledNative'][key]=value
                with self.subTest(key=key),self.assertRaisesRegex(WorkflowError,'original-compiler-native-ancestry'):
                    replay.original_native_ancestry(changed)
            changed=copy.deepcopy(original);changed['consumerNativeSource']={}
            with self.assertRaisesRegex(WorkflowError,'original-compiler-native-ancestry'):
                replay.original_native_ancestry(changed)

    def test_wit_is_copied_verbatim_from_the_normal_package_with_its_original_observed_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);name=replay.WIT[0];raw=b'original exact observed WIT\n'
            layer=root/'package/layers'/name;layer.parent.mkdir(parents=True);layer.write_bytes(raw)
            write_json(root/'package-inputs.json',{name:{'digest':digest(raw),'size':len(raw)}})
            self.assertEqual(replay.restore_layers(root),[name])
            self.assertEqual((root/name).read_bytes(),raw)
            self.assertEqual(replay.restore_layers(root),[])
            (root/name).unlink();layer.write_bytes(b'changed')
            with self.assertRaisesRegex(WorkflowError,'original-wit-layer-bytes'):replay.restore_layers(root)

    def test_missing_component_or_arbitrary_layer_cannot_be_reconstructed(self):
        for name in ('component.wasm','other.wit','../outside','wit/../outside.wit'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                write_json(root/'package-inputs.json',{name:{'digest':digest(b'controlled'),'size':10}})
                with self.assertRaises(WorkflowError):replay.restore_layers(root)

    def test_archive_rejects_traversal_and_corrupt_members_before_replay(self):
        def archive(name,raw):
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w') as z:z.writestr(name,raw)
            return output.getvalue()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            raw=archive(replay.PREFIX+'build/observed.json',b'{}')
            self.assertEqual(replay.unpack(raw,root)['crcCheckedMembers'],1)
            self.assertEqual((root/replay.PREFIX/'build/observed.json').read_bytes(),b'{}')
            for name in ('../escape','/absolute','a\\b','C:/absolute'):
                # Windows ZipInfo normalizes separator bytes during writing;
                # put the actual forbidden bytes into both ZIP headers.
                portable=name.replace('\\','/')
                malformed=archive(portable,b'{}').replace(portable.encode(),name.encode())
                with self.subTest(name=name),self.assertRaises(WorkflowError):replay.unpack(malformed,root)
            corrupted=raw.replace(b'{}',b'[]',1)
            with self.assertRaises(zipfile.BadZipFile):replay.unpack(corrupted,root)
