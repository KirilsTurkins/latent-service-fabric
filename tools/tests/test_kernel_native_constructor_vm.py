"""Closed source/image/observation refusal controls; no build or VM execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import host_stream_kernel_native_vm as owner
from tools import host_stream_kernel_native_vm_inputs as inputs
from tools import qualify_host_stream_kernel_native_vm as programme
from tools.tests.test_host_stream_kernel_vm_image import static_image
from tools.tests.test_kernel_vm_numeric import fixture as original_cpio


def observations():
    fields = ('connections','failedCleanup','cleanupJobs','pending','running','workers',
              'metadataBytes','controlFailed','descriptors')
    rows = [owner.BOOT]
    for name, values in (
            ('baseline',[0,0,0,0,0,0,100000,0,0]),
            ('ready',[1,0,1,0,0,0,1300000,0,1]),
            ('quarantined',[1,1,1,0,0,0,1200000,0,0])):
        rows.append(b'LSFNATIVE1 state='+name.encode()+b''.join(
            b' '+key.encode()+b'='+str(value).encode() for key,value in zip(fields,values)))
    return rows+[owner.NATIVE_PASS,owner.TERMINAL]


class NativeConstructorKernelJoin(unittest.TestCase):
    def test_fixed_successful_kernel_origin_cannot_select_failed_expired_or_changed_artifacts(self):
        run = dict(run_attempt=1,id=inputs.RUN,head_sha=inputs.SOURCE,event='push',
            head_branch='feat/kernel-no-begin-root-final-free-20261024',
            path='.github/workflows/stream-kernel-constructor-vm.yml',status='completed',conclusion='success')
        job = dict(id=inputs.JOB,run_id=inputs.RUN,head_sha=inputs.SOURCE,status='completed',
            conclusion='success',steps=[{'conclusion':'success'}])
        artifact = dict(id=inputs.ARTIFACT,size_in_bytes=inputs.ZIP_BYTES,digest='sha256:'+inputs.ZIP_SHA,
            expired=False,name='stream-kernel-constructor-vm-'+inputs.SOURCE,
            workflow_run={'id':inputs.RUN,'head_sha':inputs.SOURCE})
        inputs.origin(run,job,artifact)
        for container, changes in ((run,{'conclusion':'failure'}),(run,{'run_attempt':True}),
                (run,{'head_branch':'development'}),(job,{'conclusion':'failure'}),
                (artifact,{'expired':True}),(artifact,{'expired':0}),
                (artifact,{'digest':'sha256:'+'0'*64}),(artifact,{'size_in_bytes':inputs.ZIP_BYTES+1})):
            changed = copy.deepcopy(container);changed.update(changes)
            args = [changed if item is container else item for item in (run,job,artifact)]
            with self.subTest(changes=changes),self.assertRaises(ValueError):inputs.origin(*args)
        raw = (inputs.ROOT/inputs.PUBLIC).read_bytes().replace(b'\r\n',b'\n')
        self.assertEqual(inputs.public_receipt()['status'],'passed')
        with patch.object(inputs,'read_file',return_value=raw+b' '),self.assertRaises(ValueError):
            inputs.public_receipt()

    def test_actual_reader_accepts_independent_uart_orders_without_inventing_close_race(self):
        rows = observations()
        for kernel in ([owner.image.PHYSICAL_MARKER],
                [owner.image.PHYSICAL_MARKER,owner.OUTSIDE],
                [owner.HANDOFF,owner.image.PHYSICAL_MARKER,owner.OUTSIDE]):
            for offset in (0,len(rows)):
                raw = b'\n'.join(rows[:offset]+kernel+rows[offset:])+b'\n'
                result = owner.serial_observation(raw)
                self.assertTrue(result['actualNativeConstructorReady'])
                self.assertTrue(result['originalNodeCapacityQuarantined'])
                self.assertFalse(result['nativeQuotaReleased'])
                self.assertEqual(result['observedPendingFdHandoff'],owner.HANDOFF in kernel)

    def test_success_words_or_zero_counters_never_replace_original_retention_and_kernel_return(self):
        rows = observations();raw = b'\n'.join(rows+[owner.image.PHYSICAL_MARKER])+b'\n'
        bad = [b'\n'.join(rows)+b'\n',raw+owner.image.PHYSICAL_MARKER+b'\n',
            raw.replace(b'nativeQuotaReleased=0',b'nativeQuotaReleased=1'),
            raw.replace(b'state=ready connections=1',b'state=ready connections=0'),
            raw.replace(b'state=quarantined connections=1',b'state=quarantined connections=0'),
            raw.replace(b'metadataBytes=1200000',b'metadataBytes=0'),
            raw.replace(b'metadataBytes=1200000',b'metadataBytes=1200000.0'),
            raw.replace(b'descriptors=0\nLSFNATIVE1 result',b'descriptors=1\nLSFNATIVE1 result'),
            raw+b'Kernel panic',raw+bytes(owner.image.MAX_SERIAL),
            b'\n'.join(rows+[owner.OUTSIDE,owner.image.PHYSICAL_MARKER])+b'\n',
            b'\n'.join(rows+[owner.HANDOFF,owner.image.PHYSICAL_MARKER])+b'\n',
            b'\n'.join(rows[:-1]+[owner.image.PHYSICAL_MARKER])+b'\n']
        for value in bad:
            with self.subTest(size=len(value)),self.assertRaises(ValueError):owner.serial_observation(value)

    def test_fixed_cpio_preserves_console_entries_and_contains_exact_two_native_programs(self):
        old = static_image();supervisor = old+b'supervisor';native = old+b'native'
        original = original_cpio(old)
        result = owner.native_initramfs(original,old,supervisor,native)
        entries,position = {},0
        while True:
            self.assertEqual(result[position:position+6],b'070701')
            fields = [int(result[position+6+i*8:position+14+i*8],16) for i in range(13)]
            position += 110;name = result[position:position+fields[11]-1].decode()
            position = (position+fields[11]+3)&~3
            entries[name] = (fields[1],result[position:position+fields[6]])
            position = (position+fields[6]+3)&~3
            if name == 'TRAILER!!!':break
        self.assertEqual(set(entries),{'dev','dev/console','proc','sys','init','tmp','native-init','TRAILER!!!'})
        self.assertEqual(entries['dev/console'],(0o20600,b''))
        self.assertEqual(entries['init'],(0o100755,supervisor))
        self.assertEqual(entries['native-init'],(0o100755,native))
        self.assertEqual(entries['tmp'],(0o41777,b''))
        for changed in (original.replace(b'console',b'consoLe',1),original+b'unknown'):
            with self.assertRaises(ValueError):owner.native_initramfs(changed,old,supervisor,native)
        with self.assertRaises(ValueError):owner.native_initramfs(original,old,supervisor,native+bytes(owner.image.MAX_INIT))

    def test_cargo_product_requires_the_owned_example_source_and_successful_static_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve();target = root/'owned-target'
            row = dict(reason='compiler-artifact',manifest_path=str(root/'crates/latent-streams/Cargo.toml'),
                target={'name':'kernel_constructor_vm','kind':['example'],'src_path':str(root/owner.EXAMPLE)},
                profile={'test':False,'opt_level':'z','debug_assertions':False},
                features=['default','development-outbound'],
                executable=str(target/programme.TARGET/'release/examples/kernel_constructor_vm'))
            finish = {'reason':'build-finished','success':True}
            def raw(value, end=finish):return (json.dumps(value)+'\n'+json.dumps(end)+'\n').encode()
            self.assertEqual(programme.cargo_product(raw(row),root,target),Path(row['executable']))
            mutations = []
            for value in (True,):
                changed=copy.deepcopy(row);changed['profile']['test']=value;mutations.append(raw(changed))
            changed=copy.deepcopy(row);changed['target']['src_path']=str(root/'foreign.rs');mutations.append(raw(changed))
            changed=copy.deepcopy(row);changed['features']=[];mutations.append(raw(changed))
            mutations.extend((raw(row,{'reason':'build-finished','success':False}),raw(row)+raw(row),json.dumps(row).encode()))
            for value in mutations:
                with self.assertRaises(ValueError):programme.cargo_product(value,root,target)
