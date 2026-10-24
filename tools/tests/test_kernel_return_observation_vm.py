"""Closed source/reader controls only; no compiler, native syscall or VM."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import host_stream_kernel_return_vm as reader
from tools import host_stream_kernel_return_source as source
from tools import host_stream_kernel_retirement_observation as projection
from tools import qualify_host_stream_kernel_return_vm as owner


def observations():
    fields = ('connections','failedCleanup','cleanupJobs','pending','running','workers',
        'metadataBytes','controlFailed','descriptors','observerDescriptors')
    rows = [reader.BOOT]
    for name,values in (
            ('baseline',[0,0,0,0,0,0,100000,0,0,0]),
            ('ready',[1,0,1,0,0,0,1304096,0,1,1]),
            ('root-return-observed-held',[1,1,2,0,0,0,1304096,0,0,0]),
            ('quarantined',[1,1,1,0,0,0,1204096,0,0,0])):
        rows.append(b'LSFRETURN1 state='+name.encode()+b''.join(
            b' '+key.encode()+b'='+str(value).encode() for key,value in zip(fields,values)))
    return rows+[reader.NATIVE_PASS,reader.TERMINAL]


class KernelReturnObservation(unittest.TestCase):
    def test_actual_reader_requires_both_fd_roles_and_independent_kernel_orders(self):
        rows = observations()
        for kernel in ([reader.image.PHYSICAL_MARKER],
                [reader.image.PHYSICAL_MARKER,reader.OUTSIDE],
                [reader.HANDOFF,reader.image.PHYSICAL_MARKER,reader.OUTSIDE]):
            for offset in (0,len(rows)):
                raw = b'\n'.join(rows[:offset]+kernel+rows[offset:])+b'\n'
                value = reader.serial_observation(raw)
                self.assertTrue(value['actualNativeKernelRootReturned'])
                self.assertTrue(value['originalObserverChargeQuarantined'])
                self.assertTrue(value['originalReceiptChargeObserved'])
                self.assertEqual(value['snapshots']['ready']['observerDescriptors'],1)
                self.assertFalse(value['nativeQuotaReleased'])

    def test_success_text_or_missing_observer_never_replaces_typed_return_and_original_quarantine(self):
        rows = observations();raw = b'\n'.join(rows+[reader.image.PHYSICAL_MARKER])+b'\n'
        wrong = [b'\n'.join(rows)+b'\n',raw+reader.image.PHYSICAL_MARKER+b'\n',
            raw.replace(b'LSFRETURN1 ',b'LSFNATIVE1 '),
            raw.replace(b'kernelRootReturned=1',b'closeRequestAccepted=1'),
            raw.replace(b'descriptors=1 observerDescriptors=1',b'descriptors=1 observerDescriptors=0'),
            raw.replace(b'observerDescriptors=0',b'observerDescriptors=1'),
            raw.replace(b'state=quarantined connections=1',b'state=quarantined connections=0'),
            raw.replace(b'state=root-return-observed-held connections=1 failedCleanup=1 cleanupJobs=2',
                b'state=root-return-observed-held connections=1 failedCleanup=1 cleanupJobs=1'),
            raw.replace(b'metadataBytes=1204096',b'metadataBytes=1148576'),
            raw.replace(b'metadataBytes=1204096',b'metadataBytes=1304096'),
            raw.replace(b'controlFailed=0',b'controlFailed=1'),
            raw.replace(b'cleanupJobs=1',b'cleanupJobs=1.0'),
            raw.replace(b'nativeQuotaReleased=0',b'nativeQuotaReleased=1'),
            raw.replace(b'observerClosed=1',b'observerClosed=0'),
            raw+b'BUG:',raw+bytes(reader.image.MAX_SERIAL),
            b'\n'.join(rows+[reader.OUTSIDE,reader.image.PHYSICAL_MARKER])+b'\n',
            b'\n'.join(rows+[reader.HANDOFF,reader.image.PHYSICAL_MARKER])+b'\n']
        for value in wrong:
            with self.subTest(size=len(value)),self.assertRaises(ValueError):reader.serial_observation(value)

    def test_actual_ordinary_function_bodies_reject_each_changed_allocator_or_security_hook(self):
        value = source.fixture()
        compiled = {name:''.join(row['text'] for row in rows.values()).encode()
            for name,rows in value['bodies'].items()}
        result = source.body_identities(compiled)
        self.assertEqual(set(result),set(value['bodies']))
        for name,rows in value['bodies'].items():
            for row in rows.values():
                changed = dict(compiled)
                # Mutate a real authenticated body, not a parallel implementation.
                changed[name] = changed[name].replace(row['text'].encode(),
                    row['text'].replace('\n{\n','\n{\n\t/* changed allocation route */\n',1).encode(),1)
                with self.subTest(name=name),self.assertRaises(ValueError):source.body_identities(changed)

    def test_current_whole_projection_changes_only_three_files_and_retains_old_vfs_lifetimes(self):
        original = projection.original_sources()
        changed,record = source.compose(original,original)
        self.assertEqual(set(record['newDerivedDelta']),{'net/factory.c',
            'net/factory-cleanup-root-final-free.c',projection.FRAGMENT})
        self.assertFalse(record['historicalImageReused'])
        for name,raw in original.items():
            if name not in record['newDerivedDelta']:self.assertEqual(changed[name],raw)
        broken = dict(original);broken['net/factory.c'] += b'\n'
        with self.assertRaises(ValueError):source.compose(broken,broken)

    def test_normal_cargo_inventory_cannot_substitute_old_example_or_changed_source_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve();target=root/'target'
            row = {'reason':'compiler-artifact','manifest_path':str(root/'crates/latent-streams/Cargo.toml'),
                'target':{'name':reader.TARGET_NAME,'kind':['example'],'src_path':str(root/reader.EXAMPLE)},
                'profile':{'test':False,'opt_level':'z','debug_assertions':False},
                'features':['default','development-outbound'],
                'executable':str(target/owner.original.TARGET/'release/examples'/reader.TARGET_NAME)}
            finish = {'reason':'build-finished','success':True}
            def raw(item,end=finish):return (json.dumps(item)+'\n'+json.dumps(end)+'\n').encode()
            self.assertEqual(owner.cargo_product(raw(row),root,target),Path(row['executable']))
            mutations=[]
            for field,value in (('name','kernel_constructor_vm'),('src_path',str(root/'foreign.rs')),
                    ('kind',['bin'])):
                item=copy.deepcopy(row);item['target'][field]=value;mutations.append(raw(item))
            item=copy.deepcopy(row);item['profile']['opt_level']='3';mutations.append(raw(item))
            item=copy.deepcopy(row);item['features']=[];mutations.append(raw(item))
            mutations.extend((raw(row,{'reason':'build-finished','success':False}),raw(row)+raw(row)))
            for value in mutations:
                with self.assertRaises(ValueError):owner.cargo_product(value,root,target)
