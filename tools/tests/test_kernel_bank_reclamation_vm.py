"""Finite provenance/oracle controls; no syscall, compiler or VM execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import host_stream_kernel_bank_inputs as inputs
from tools import host_stream_kernel_bank_vm as reader
from tools import qualify_host_stream_kernel_bank_vm as owner


def rows():
    fields = ('connections','failedCleanup','cleanupJobs','pending','running','workers',
        'metadataBytes','controlFailed','descriptors','observerDescriptors')
    result = [reader.BOOT]
    for name,values in (
            ('baseline',[0,0,0,0,0,0,100000,0,0,0]),
            ('ready',[1,0,1,0,0,0,1350000,0,1,1]),
            ('root-return-observed-held',[1,1,2,0,0,0,900000,0,0,0]),
            ('quarantined',[1,1,1,0,0,0,700000,0,0,0]),
            ('bank-capacity-reused',[1,1,1,0,0,0,1224288,0,0,0]),
            ('bank-capacity-returned',[1,1,1,0,0,0,700000,0,0,0])):
        result.append(b'LSFBANK1 state='+name.encode()+b''.join(
            b' '+key.encode()+b'='+str(value).encode() for key,value in zip(fields,values)))
    return result+[reader.PASS,reader.TERMINAL]


class KernelBankReclamation(unittest.TestCase):
    def test_successful_origin_cannot_be_replaced_by_failed_expired_or_other_image(self):
        run = {'id':inputs.RUN,'run_attempt':1,'head_sha':inputs.SOURCE,'event':'push',
            'head_branch':'feat/kernel-native-return-vm-20261024',
            'path':'.github/workflows/stream-kernel-return-vm.yml',
            'status':'completed','conclusion':'success'}
        job = {'id':inputs.JOB,'run_id':inputs.RUN,'head_sha':inputs.SOURCE,
            'status':'completed','conclusion':'success','steps':[{'conclusion':'success'}]}
        artifact = {'id':inputs.ARTIFACT,'size_in_bytes':inputs.ZIP_BYTES,'expired':False,
            'digest':'sha256:'+inputs.ZIP_SHA,'name':'stream-kernel-return-vm-'+inputs.SOURCE,
            'workflow_run':{'id':inputs.RUN,'head_sha':inputs.SOURCE}}
        inputs.origin(run,job,artifact)
        wrong=[]
        for field,value in (('conclusion','failure'),('event','workflow_dispatch'),
                ('run_attempt',True),('head_sha','0'*40),('id',inputs.RUN-1)):
            item=copy.deepcopy(run);item[field]=value;wrong.append((item,job,artifact))
        for value in ([],[{'conclusion':'failure'}],[{'conclusion':'skipped'}]):
            item=copy.deepcopy(job);item['steps']=value;wrong.append((run,item,artifact))
        for field,value in (('expired',True),('size_in_bytes',float(inputs.ZIP_BYTES)),
                ('digest','sha256:'+'0'*64),('id',inputs.ARTIFACT-1)):
            item=copy.deepcopy(artifact);item[field]=value;wrong.append((run,job,item))
        for value in wrong:
            with self.subTest(value=value),self.assertRaises(ValueError):inputs.origin(*value)

    def test_complete_member_hashes_refuse_missing_added_and_changed_products_before_decode(self):
        public=inputs.public_receipt()
        # Authenticated member identities are enforced before ELF/config/CPIO
        # parsing. Dummy bytes cannot be passed off as a selected image.
        members={name:b'' for name in public['retainedMembers']}
        for value in (members,{},dict(members,extra=b''),
                {name:raw for name,raw in members.items() if name!='kernel/constructor-bzImage'}):
            with self.assertRaises(ValueError):inputs.validate_members(value)

    def test_actual_uart_reader_requires_partial_charge_retention_and_exact_reuse(self):
        user=rows();kernel=[reader.HANDOFF,reader.image.PHYSICAL_MARKER,reader.OUTSIDE]
        for offset in (0,len(user)):
            raw=b'\n'.join(user[:offset]+kernel+user[offset:])+b'\n'
            value=reader.serial_observation(raw)
            self.assertEqual(value['bankReservationReturnedBytes'],524288)
            self.assertTrue(value['actualBankCapacityReused'])
            self.assertTrue(value['originalConnectionQuarantined'])
            self.assertFalse(value['fullNativeQuotaReleased'])
        raw=b'\n'.join(user+kernel)+b'\n'
        wrong=[b'\n'.join(user)+b'\n',raw+reader.image.PHYSICAL_MARKER+b'\n',
            raw.replace(b'LSFBANK1 ',b'LSFRETURN1 '),
            raw.replace(b'kernelRootReturned=1',b'closeRequestAccepted=1'),
            raw.replace(b'descriptors=1 observerDescriptors=1',b'descriptors=1 observerDescriptors=0'),
            raw.replace(b'observerDescriptors=0',b'observerDescriptors=1'),
            raw.replace(b'state=quarantined connections=1',b'state=quarantined connections=0'),
            raw.replace(b'metadataBytes=700000',b'metadataBytes=1200000'),
            raw.replace(b'metadataBytes=700000',b'metadataBytes=104096'),
            raw.replace(b'metadataBytes=1224288',b'metadataBytes=1224289'),
            raw.replace(b'cleanupJobs=2',b'cleanupJobs=1'),
            raw.replace(b'cleanupJobs=1',b'cleanupJobs=1.0'),
            raw.replace(b'controlFailed=0',b'controlFailed=1'),
            raw.replace(b'fullNativeQuotaReleased=0',b'fullNativeQuotaReleased=1'),
            raw+b'BUG:',raw+bytes(reader.image.MAX_SERIAL),
            b'\n'.join(user+[reader.OUTSIDE,reader.image.PHYSICAL_MARKER])+b'\n',
            b'\n'.join(user+[reader.HANDOFF,reader.image.PHYSICAL_MARKER])+b'\n']
        for value in wrong:
            with self.subTest(size=len(value)),self.assertRaises(ValueError):reader.serial_observation(value)

    def test_normal_cargo_inventory_cannot_substitute_old_target_or_relaxed_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();target=root/'target'
            row={'reason':'compiler-artifact','manifest_path':str(root/'crates/latent-streams/Cargo.toml'),
                'target':{'name':reader.TARGET_NAME,'kind':['example'],'src_path':str(root/reader.EXAMPLE)},
                'profile':{'test':False,'opt_level':'z','debug_assertions':False},
                'features':['default','development-outbound'],
                'executable':str(target/owner.original.TARGET/'release/examples'/reader.TARGET_NAME)}
            finish={'reason':'build-finished','success':True}
            def raw(item,end=finish):return (json.dumps(item)+'\n'+json.dumps(end)+'\n').encode()
            self.assertEqual(owner.cargo_product(raw(row),root,target),Path(row['executable']))
            wrong=[]
            for field,value in (('name','kernel_return_observation_vm'),
                    ('src_path',str(root/'foreign.rs')),('kind',['bin'])):
                item=copy.deepcopy(row);item['target'][field]=value;wrong.append(raw(item))
            item=copy.deepcopy(row);item['profile']['opt_level']='3';wrong.append(raw(item))
            item=copy.deepcopy(row);item['features']=[];wrong.append(raw(item))
            wrong.extend((raw(row,{'reason':'build-finished','success':False}),raw(row)+raw(row)))
            for value in wrong:
                with self.assertRaises(ValueError):owner.cargo_product(value,root,target)
