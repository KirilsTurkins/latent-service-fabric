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
            ('close-request-accepted-held',[1,1,2,0,0,0,1300000,0,0]),
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
                self.assertTrue(result['actualNativeCloseRequestAccepted'])
                self.assertTrue(result['originalReceiptChargeObserved'])
                self.assertTrue(result['originalNodeCapacityQuarantined'])
                self.assertFalse(result['nativeQuotaReleased'])
                self.assertEqual(result['observedPendingFdHandoff'],owner.HANDOFF in kernel)

    def test_success_words_or_zero_counters_never_replace_original_retention_and_kernel_return(self):
        rows = observations();raw = b'\n'.join(rows+[owner.image.PHYSICAL_MARKER])+b'\n'
        bad = [b'\n'.join(rows)+b'\n',raw+owner.image.PHYSICAL_MARKER+b'\n',
            raw.replace(b'nativeQuotaReleased=0',b'nativeQuotaReleased=1'),
            raw.replace(b'state=ready connections=1',b'state=ready connections=0'),
            raw.replace(b'state=quarantined connections=1',b'state=quarantined connections=0'),
            raw.replace(b'state=close-request-accepted-held connections=1 failedCleanup=1 cleanupJobs=2',
                b'state=close-request-accepted-held connections=1 failedCleanup=1 cleanupJobs=1'),
            raw.replace(b'closeRequestAccepted=1',b'closeRequestAccepted=0'),
            raw.replace(b'metadataBytes=1200000',b'metadataBytes=1300000'),
            raw.replace(b'state=close-request-accepted-held',b'state=quarantined'),
            raw.replace(b'metadataBytes=1200000',b'metadataBytes=0'),
            raw.replace(b'metadataBytes=1200000',b'metadataBytes=1200000.0'),
            raw.replace(b'descriptors=0\nLSFNATIVE1 result',b'descriptors=1\nLSFNATIVE1 result'),
            raw+b'Kernel panic',raw+bytes(owner.image.MAX_SERIAL),
            b'\n'.join(rows+[owner.OUTSIDE,owner.image.PHYSICAL_MARKER])+b'\n',
            b'\n'.join(rows+[owner.HANDOFF,owner.image.PHYSICAL_MARKER])+b'\n',
            b'\n'.join(rows[:3]+rows[4:]+[owner.image.PHYSICAL_MARKER])+b'\n',
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
        with self.assertRaises(ValueError):owner.native_initramfs(original,old,supervisor,native+bytes(owner.MAX_NATIVE_INIT))

    def test_fixed_child_partition_preserves_original_elf_grammar_and_aggregate_budget(self):
        import inspect
        import struct
        inverse = inspect.getsource(owner.native_elf).replace('def native_elf(', 'def init_elf(')
        inverse = inverse.replace('MAX_NATIVE_INIT','MAX_INIT').replace('image.MAX_INIT_LOAD','MAX_INIT_LOAD')
        inverse = inverse.replace('image.require(', 'require(')
        self.assertEqual(inverse,inspect.getsource(owner.image.init_elf))
        original = static_image()
        large_child = original+bytes(owner.MAX_NATIVE_INIT-len(original))
        self.assertEqual(owner.native_elf(large_child)['bytes'],owner.MAX_NATIVE_INIT)
        with self.assertRaises(ValueError):owner.image.init_elf(large_child)
        with self.assertRaises(ValueError):owner.native_elf(large_child+b'x')
        for offset, encoding, value in ((64,'<I',3),(64,'<I',2),(68,'<I',7),
                (96,'<Q',513),(104,'<Q',owner.image.MAX_INIT_LOAD+1),
                (24,'<Q',0x900000),(112,'<Q',3),(18,'<H',183),(56,'<H',65)):
            changed = bytearray(original);struct.pack_into(encoding,changed,offset,value)
            with self.subTest(offset=offset,value=value),self.assertRaises(ValueError):
                owner.native_elf(bytes(changed))
        overlap = bytearray(original);struct.pack_into('<H',overlap,56,2)
        struct.pack_into('<IIQQQQQQ',overlap,120,1,4,256,0x400100,0,128,128,1)
        with self.assertRaises(ValueError):owner.native_elf(bytes(overlap))
        def memory_span(size):
            raw = bytearray(original);struct.pack_into('<Q',raw,104,size);return bytes(raw)
        pid1, child = memory_span(1024**2), memory_span(3*1024**2)
        self.assertEqual(owner.executable_partition(pid1,child)['aggregateLoadSpanBytes'],4*1024**2)
        with self.assertRaisesRegex(ValueError,'aggregate-executable-load-span'):
            owner.executable_partition(pid1,memory_span(3*1024**2+1))
        with self.assertRaisesRegex(ValueError,'aggregate-executable-load-span'):
            owner.native_initramfs(original_cpio(original),original,pid1,memory_span(3*1024**2+1))
        gap = bytearray(original);struct.pack_into('<H',gap,56,2)
        struct.pack_into('<IIQQQQQQ',gap,120,1,4,256,0x700000,0,128,128,1)
        with self.assertRaisesRegex(ValueError,'aggregate-executable-load-span'):
            owner.executable_partition(pid1,bytes(gap))
        big_pid1 = original+bytes(1536*1024-len(original))
        with self.assertRaisesRegex(ValueError,'unchanged-initramfs-byte-bound'):
            owner.native_initramfs(original_cpio(original),original,big_pid1,large_child)
        with self.assertRaises(ValueError):owner.executable_partition(large_child,original)

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


class Q35NodeBootSourceControls(unittest.TestCase):
    def test_pci_observation_requires_the_actual_unregistered_selected_slot(self):
        source = (owner.ROOT / owner.NODE_ROOT / 'factory-node-boot.c').read_text(encoding='utf8')
        self.assertIn('pci_find_bus(LSF_DEVICE_PCI_DOMAIN, LSF_DEVICE_PCI_BUS)', source)
        self.assertIn('pci_get_slot(bus, LSF_DEVICE_PCI_DEVFN)', source)
        self.assertIn('pci_dev_put(existing);\n        goto out;', source)
        self.assertIn('pci_bus_read_config_dword(bus, LSF_DEVICE_PCI_DEVFN, PCI_VENDOR_ID,', source)
        self.assertIn('(identity & 0xffffu) != LSF_DEVICE_PCI_VENDOR', source)
        self.assertIn('(identity >> 16) != LSF_DEVICE_PCI_DEVICE', source)
        self.assertLess(source.index('pci_lock_rescan_remove();'), source.index('pci_find_bus('))
        self.assertLess(source.index('pci_get_slot('), source.index('pci_bus_read_config_dword('))
        self.assertLess(source.index('(identity >> 16) != LSF_DEVICE_PCI_DEVICE'),
            source.index('LSFQ35PCICONFIG1'))
        self.assertLess(source.index('LSFQ35PCICONFIG1'), source.index('pci_unlock_rescan_remove();'))
        self.assertIn('cpu_online(0) &&\n        lsf_node_boot_selected_pci()', source)
        for forbidden in ('pci_scan_single_device(', 'pci_bus_add_device(', 'pci_enable_device('):
            self.assertNotIn(forbidden, source)
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location('lsf_node_pci_projector', owner.ROOT / owner.NODE_PROJECTOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        projector = module_from_spec(spec)
        spec.loader.exec_module(projector)
        entry = projector.NEW_ENTRY
        refusal = b'if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))\n        return -EPERM;'
        self.assertEqual(entry.count(refusal), 1)
        self.assertLess(entry.index(refusal), entry.index(b'lsf_node_boot_entry_ready()'))
        self.assertEqual(projector.inverse_bootstrap(entry), projector.OLD_ENTRY)

    def test_actual_node_facts_are_required_without_funding_or_retirement_credit(self):
        facts = (b'LSFNODEBOOT1 facts=[1, 2, 3, 4, 5, 6] cpu=[1, 1, 1, 2, 3, 4, 5, 6, 7] '
            b'accounting=[1, 2, 3, 4, 5, 6, 7, 8] vectors=[32, 33, 34, 35, 36, 37, 38, 39]')
        pci = b'[    1.234567] ' + owner.NODE_PCI_OBSERVATION
        raw = b'\n'.join((owner.NODE_BOOT,pci,facts,owner.NODE_HELD,b'LSFNODEBOOT1 childExit=0',owner.NODE_END))+b'\n'
        observed = owner.node_serial(raw)
        self.assertTrue(observed['originalEscrowRetained'])
        self.assertEqual(observed['selectedPciConfig'], {'bdf':'0000:00:03.0',
            'vendor':'1af4','device':'1041','unregistered':True,'observedInGuest':True})
        self.assertFalse(observed['pciConstructorQualified'])
        self.assertFalse(observed['napiQualified'])
        for key in ('nodeFunding','nodeRetired','irqEnabled','tcpEnabled'):
            self.assertIs(observed[key],False)
        for bad in (raw.replace(b'cpu=[1, 1, 1,',b'cpu=[2, 1, 1,'),
                raw.replace(b'32, 33, 34, 35, 36, 37, 38, 39',b'32, 32, 34, 35, 36, 37, 38, 39'),
                raw.replace(b'childExit=0',b'childExit=1'),raw.replace(b'nodeFunding=0',b'nodeFunding=1'),
                raw.replace(b'originalEscrowRetained=1',b'originalEscrowRetained=0'),
                raw.replace(b'accounting=[1, 2, 3,',b'accounting=[1, 4, 3,'),
                raw.replace(pci+b'\n',b''), raw+pci+b'\n',
                raw.replace(b'0000:00:03.0',b'0000:00:01.0'),
                raw.replace(b'vendor=1af4',b'vendor=1af5'),
                raw.replace(b'device=1041',b'device=1000'),
                raw.replace(b'unregistered=1',b'unregistered=0'),
                raw.replace(pci+b'\n'+facts, facts+b'\n'+pci),
                raw.replace(b'[    1.234567] '+owner.NODE_PCI_OBSERVATION,
                    owner.NODE_PCI_OBSERVATION),
                raw+owner.NODE_HELD+b'\n',raw+owner.image.PHYSICAL_MARKER+b'\n',
                raw.replace(b'facts=[1, 2, 3, 4, 5, 6]',b'facts=[1, 2]')):
            with self.subTest(raw=bad),self.assertRaises(ValueError):owner.node_serial(bad)

    def test_q35_argv_and_captured_loader_cannot_select_tcg_or_alternate_source(self):
        # This is the actual shared geometry material, with all ordinary
        # function bodies unchanged. The final image uses normal rodata layout.
        projector_path = owner.ROOT / owner.NODE_PROJECTOR
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location('lsf_node_geometry_projector', projector_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        projector = vars(module)
        geometry = (owner.ROOT / 'research/standard-outbound/linux-6.12-lineage/node-irq-geometry/geometry.c').read_bytes()
        placed = projector['geometry_for_link'](geometry)
        self.assertEqual(placed, geometry.replace(b'__section(".lsf_node_geometry")',
            b'__section(".rodata.lsf_node_geometry")', 1))
        self.assertEqual(projector['inverse_geometry_for_link'](placed), geometry)
        for bad in (geometry.replace(b'.lsf_node_geometry', b'.foreign_geometry'),
                geometry + geometry, placed, geometry + placed, None):
            with self.subTest(geometry=bad), self.assertRaises(ValueError):
                projector['geometry_for_link'](bad)
        for bad in (geometry, placed + placed, geometry + placed, None):
            with self.subTest(inverse=bad), self.assertRaises(ValueError):
                projector['inverse_geometry_for_link'](bad)
        root = Path(tempfile.gettempdir()).resolve()/'owned'
        argv = owner.node_boot_argv(*(root/n for n in ('qemu','kernel','cpio','firmware')))
        self.assertEqual(argv[argv.index('-machine')+1],'pc-q35-11.1')
        self.assertEqual(argv[argv.index('-accel')+1],'kvm')
        self.assertEqual(argv[argv.index('-smp')+1],'1,maxcpus=1')
        self.assertEqual(argv[argv.index('-nic')+1],'none')
        self.assertEqual(argv.count('-device'),1)
        self.assertEqual(argv[argv.index('-device')+1],
            'virtio-net-pci,id=net0,bus=pcie.0,addr=0x3,disable-legacy=on,mac=52:54:00:12:34:56,vectors=3,romfile=')
        self.assertNotIn('-netdev',argv)
        self.assertFalse(any('iommu' in x or 'tcg' in x for x in argv))
        captured = {owner.NODE_PROJECTOR:b'ROOT = None\n',
            **{owner.NODE_ROOT+n:b'' for n in owner.NODE_MATERIALS}}
        with self.assertRaises(ValueError):owner.node_compose({}, {}, captured)
        # A forged borrowed/funding marker is not an alternate success profile.
        with self.assertRaises(ValueError):owner.node_serial(owner.NATIVE_PASS+b'\n')
        # Tar link closure is pure metadata; no host symlink privilege is used.
        root_name = 'qemu-11.1.2'
        rows = {root_name: {'type': '5', 'link': ''},
            root_name+'/data': {'type': '5', 'link': ''},
            root_name+'/data/value': {'type': '0', 'link': ''},
            root_name+'/alias': {'type': '2', 'link': 'data/value'},
            root_name+'/nested': {'type': '5', 'link': ''},
            root_name+'/nested/link': {'type': '2', 'link': '../alias'},
            root_name+'/hard': {'type': '1', 'link': root_name+'/data/value'}}
        targets = owner.node_qemu_link_targets(rows, 10**12)
        self.assertEqual(targets, {root_name+name: root_name+'/data/value'
            for name in ('/alias', '/nested/link', '/hard')})
        for link in ('/opt/X11/include', '../../outside', 'missing', 'roms/edk2/unused', chr(92)+'outside'):
            changed = copy.deepcopy(rows); changed[root_name+'/alias']['link'] = link
            with self.subTest(link=link), self.assertRaises(ValueError):
                owner.node_qemu_link_targets(changed, 10**12)
        changed = copy.deepcopy(rows); changed[root_name+'/alias']['link'] = 'nested/link'
        with self.assertRaisesRegex(ValueError, 'node-qemu-link-cycle'):
            owner.node_qemu_link_targets(changed, 10**12)
        for target in ('data', 'alias'):
            changed = copy.deepcopy(rows); changed[root_name+'/hard']['link'] = root_name+'/'+target
            with self.subTest(hard=target), self.assertRaises(ValueError):
                owner.node_qemu_link_targets(changed, 10**12)
        changed = copy.deepcopy(rows); changed[root_name+'/alias/child'] = {'type': '0', 'link': ''}
        with self.assertRaisesRegex(ValueError, 'node-qemu-no-link-ancestor'):
            owner.node_qemu_link_targets(changed, 10**12)
        changed = {root_name: rows[root_name], root_name+'/data/value': rows[root_name+'/data/value']}
        for index in range(17):
            changed[root_name+'/link'+str(index)] = {'type': '2',
                'link': 'link'+str(index+1) if index < 16 else 'data/value'}
        with self.assertRaisesRegex(ValueError, 'node-qemu-link-depth'):
            owner.node_qemu_link_targets(changed, 10**12)
        changed[root_name+'/link0']['link'] = 'link2'
        self.assertEqual(owner.node_qemu_link_targets(changed, 10**12)[root_name+'/link0'],
            root_name+'/data/value')
        with self.assertRaisesRegex(ValueError, 'node-qemu-preflight-deadline'):
            owner.node_qemu_link_targets(rows, 0)
        for raw in ('/outside', root_name+'/../escape', root_name+'//alias',
                root_name+'/roms/edk2/../../escape', root_name+'/./alias', root_name+chr(92)+'alias'):
            with self.subTest(name=raw), self.assertRaises(ValueError):
                owner.node_qemu_source_name(raw)


class Q35NodePciPrefixControls(unittest.TestCase):
    @staticmethod
    def serial():
        pci = b'[    1.234567] ' + owner.NODE_PCI_OBSERVATION
        prefix = (b'[    2.345678] LSFQ35PCIPREFIX1 bdf=0000:00:03.0 vendor=1af4 '
            b'device=1041 born=1 returned=1 registered=0 scopeRevoked=1 slot=40 '
            b'generation=45 live=40,41,40 cursor=4096,5760,5760')
        facts = (b'LSFNODEBOOT1 facts=[1, 2, 3, 4, 5, 6] cpu=[1, 1, 1, 2, 3, 4, 5, 6, 7] '
            b'accounting=[524288, 4096, 4096, 4096, 45, 40, 1, 46] '
            b'vectors=[32, 33, 34, 35, 36, 37, 38, 39]')
        return b'\n'.join((owner.NODE_BOOT,pci,prefix,b'LSFNODEPREFIX1 childAck=1',
            facts,owner.NODE_HELD,b'LSFNODEBOOT1 childExit=0',owner.NODE_END))+b'\n'

    def test_prefix_requires_one_original_record_and_ordered_return(self):
        raw = self.serial()
        observed = owner.node_prefix_serial(raw)
        self.assertEqual(observed['pciPrefix']['live'],[40,41,40])
        self.assertEqual(observed['pciPrefix']['cursor'],[4096,5760,5760])
        self.assertTrue(observed['pciPrefix']['scopeRevoked'])
        self.assertFalse(observed['pciPrefix']['registered'])
        for key in ('nodeFunding','nodeRetired','irqEnabled','tcpEnabled',
                'pciConstructorQualified','napiQualified'):
            self.assertIs(observed[key],False)
        for bad in (raw.replace(b'born=1',b'born=0'),raw.replace(b'returned=1',b'returned=0'),
                raw.replace(b'registered=0 scopeRevoked=1',b'registered=1 scopeRevoked=1'),
                raw.replace(b'scopeRevoked=1',b'scopeRevoked=0'),
                raw.replace(b'live=40,41,40',b'live=40,42,40'),
                raw.replace(b'live=40,41,40',b'live=40,41,39'),
                raw.replace(b'cursor=4096,5760,5760',b'cursor=4096,5760,4096'),
                raw.replace(b'cursor=4096,5760,5760',b'cursor=4095,5760,5760'),
                raw.replace(b'generation=45',b'generation=0'),
                raw.replace(b'slot=40',b'slot=256'),
                raw.replace(b'LSFNODEPREFIX1 childAck=1\n',b''),
                raw+b'LSFNODEPREFIX1 childAck=1\n',
                raw.replace(b'LSFNODEPREFIX1 childAck=1',b'LSFNODEPREFIX1 childAck=0'),
                raw.replace(b'LSFNODEBOOT1 facts=',b'LSFNODEPREFIX1 childAck=1\nLSFNODEBOOT1 facts='),
                raw.replace(b'[    2.345678] LSFQ35PCIPREFIX1',b'LSFQ35PCIPREFIX1'),
                raw.replace(b'device=1041 born=1',b'device=1000 born=1')):
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                owner.node_prefix_serial(bad)

    def test_prefix_sources_are_captured_and_wrong_projection_refuses(self):
        captured = owner.node_prefix_capture(owner.ROOT)
        self.assertEqual(set(captured),{owner.PREFIX_BRIDGE,owner.PREFIX_PROJECTOR,owner.PREFIX_MATERIAL})
        self.assertTrue(all(captured.values()))
        with self.assertRaises(ValueError):
            owner.node_prefix_compose({},captured)
        with self.assertRaises(ValueError):
            owner.node_prefix_compose({},{})

    def test_prefix_uses_original_actor_one_scope_and_no_network_authority(self):
        root = owner.ROOT / owner.PREFIX_ROOT
        source = (root/'node-pci-prefix/factory-node-pci-prefix.c').read_text(encoding='utf8')
        bridge = (root/'node-constructor-bridge/projector.py').read_text(encoding='utf8')
        projector = (root/'node-pci-prefix/projector.py').read_text(encoding='utf8')
        for predicate in ('lsf_node_actor(file, node)','lsf_node_device_actor_current()',
                'node->prefix_attempted = 1u','node->prefix_task = current',
                'after->prefix_active = 0u','after->prefix_task = NULL',
                'factory.pool.poisoned = 1u','WRITE_ONCE(factory.uncertain, 1u)'):
            self.assertIn(predicate,source)
        self.assertIn('node->prefix_task == current',bridge)
        self.assertIn('lsf_factory_device_pci_owned(dev, sizeof(*dev)) != 0',bridge)
        self.assertIn('lsf_node_prefix_pci_birth(dev)',projector)
        self.assertIn('lsf_node_prefix_pci_returned(lsf_factory_device_pci_return(dev))',projector)
        self.assertLess(projector.index('lsf_node_prefix_pci_birth(dev)'),
            projector.index('lsf_prepaid_pci_setup_device(dev)',projector.index('PROBE_NEW')))
        self.assertIn('default n',projector)


class Q35NodePciSetupControls(unittest.TestCase):
    @staticmethod
    def serial():
        prefix = (b'[    2.345678] LSFQ35PCIPREFIX1 bdf=0000:00:03.0 vendor=1af4 '
            b'device=1041 born=1 returned=1 registered=0 scopeRevoked=1 slot=40 '
            b'generation=45 live=40,41,40 cursor=4096,5760,5760')
        setup = (b'[    2.345678] LSFQ35PCISETUP1 bdf=0000:00:03.0 vendor=1af4 '
            b'device=1041 header=0 class=020000 cfg=4096 companion=0 born=1 setup=1 '
            b'pending=1 firmwareReturned=1 pciReturned=1 registered=0 scopeRevoked=1 '
            b'pciSlot=40 pciGeneration=45 firmwareSlot=41 firmwareGeneration=46 '
            b'live=40,42,40 cursor=4096,6016,6016')
        return Q35NodePciPrefixControls.serial().replace(prefix,setup).replace(
            b'LSFNODEPREFIX1 childAck=1',b'LSFNODESETUP1 childAck=1')

    def test_distinct_original_records_must_both_actually_return(self):
        raw = self.serial()
        observed = owner.node_setup_serial(raw)
        self.assertEqual(observed['pciSetup']['live'],[40,42,40])
        self.assertEqual(observed['pciSetup']['cursor'],[4096,6016,6016])
        self.assertFalse(observed['pciSetup']['companionObserved'])
        self.assertTrue(observed['pciSetup']['firmwareRecordReturned'])
        self.assertTrue(observed['pciSetup']['pciRecordReturned'])
        self.assertFalse(observed['pciSetup']['registered'])
        for key in ('nodeFunding','nodeRetired','irqEnabled','tcpEnabled',
                'pciConstructorQualified','napiQualified'):
            self.assertIs(observed[key],False)
        for bad in (raw.replace(b'pending=1',b'pending=0'),
                raw.replace(b'firmwareReturned=1',b'firmwareReturned=0'),
                raw.replace(b'pciReturned=1',b'pciReturned=0'),
                raw.replace(b'scopeRevoked=1',b'scopeRevoked=0'),
                raw.replace(b'registered=0',b'registered=1'),
                raw.replace(b'firmwareSlot=41',b'firmwareSlot=40'),
                raw.replace(b'firmwareGeneration=46',b'firmwareGeneration=45'),
                raw.replace(b'live=40,42,40',b'live=40,41,40'),
                raw.replace(b'live=40,42,40',b'live=40,42,41'),
                raw.replace(b'cursor=4096,6016,6016',b'cursor=4096,6016,4096'),
                raw.replace(b'class=020000',b'class=010000'),
                raw.replace(b'cfg=4096',b'cfg=255'),
                raw.replace(b'LSFNODESETUP1 childAck=1\n',b''),
                raw+b'LSFNODESETUP1 childAck=1\n'):
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                owner.node_setup_serial(bad)

    def test_setup_sources_are_captured_and_unknown_projection_refuses(self):
        captured = owner.node_setup_capture(owner.ROOT)
        self.assertEqual(set(captured),{owner.SETUP_PROJECTOR,owner.SETUP_MATERIAL})
        self.assertTrue(all(captured.values()))
        with self.assertRaises(ValueError):
            owner.node_setup_compose({},captured)
        with self.assertRaises(ValueError):
            owner.node_setup_compose({},{})

    def test_setup_uses_original_actor_and_distinguishes_pending_from_return(self):
        source = (owner.ROOT/owner.SETUP_MATERIAL).read_text(encoding='utf8')
        projector = (owner.ROOT/owner.SETUP_PROJECTOR).read_text(encoding='utf8')
        for predicate in ('lsf_node_constructor_actor_current()', 'node->prefix_pending = 1u',
                'node->prefix_waiting != 1u', '!lsf_node_device_actor_current()',
                'fw->phase != LSF_PREPAID_RETURNED', 'pci->phase != LSF_PREPAID_RETURNED',
                'context->cursor != node->prefix_peak_cursor', 'cond_resched()'):
            self.assertIn(predicate,source)
        self.assertIn('CONFIG_LSF_STREAM_NODE_PCI_SETUP',projector)
        self.assertIn('return -ECANCELED',projector)
        self.assertIn('after->prefix_task = NULL',projector)

    def test_actor_scope_is_revoked_before_the_original_deadline_bounded_wait(self):
        from importlib.util import module_from_spec, spec_from_file_location
        path = owner.ROOT/owner.SETUP_PROJECTOR
        spec = spec_from_file_location('q35_setup_control_projector',path)
        stage = module_from_spec(spec)
        spec.loader.exec_module(stage)
        edits = [row for row in stage.OPERATIONS if row[0] == 'net/factory-node-pci-prefix.c']
        sequence = next(new for _,_,_,old,new in edits if b'error = lsf_node_boot_pci_prefix()' in old)
        sequence = sequence[sequence.index(b'error = lsf_node_boot_pci_prefix()'):]
        points = [sequence.index(x) for x in (b'error = lsf_node_boot_pci_prefix()',
            b'after->prefix_active = 0u', b'after->prefix_task = NULL', b'after->prefix_waiting = 1u',
            b'spin_unlock_irqrestore', b'mutex_unlock(&factory_lock)', b'lsf_node_setup_wait(node)')]
        self.assertEqual(points,sorted(points))
        wait = (owner.ROOT/owner.SETUP_MATERIAL).read_bytes().split(b'static int lsf_node_setup_wait(',1)[1]
        self.assertIn(b'node->prefix_waiting != 1u || node->prefix_task ||',wait)
        self.assertIn(b'!lsf_node_device_actor_current()',wait)
        self.assertIn(b'fatal_signal_pending(current)',wait)
        self.assertIn(b'cond_resched()',wait)
        self.assertNotIn(b'mutex_lock(',wait)
        capacity = (owner.ROOT/'research/standard-outbound/linux-6.12-lineage/node-capacity/factory-node-capacity.c').read_bytes()
        self.assertIn(b'ktime_get_ns() < node->expires_ns',capacity)

    def test_pending_and_intermediate_firmware_return_cannot_report_pci_return(self):
        source = (owner.ROOT/owner.SETUP_MATERIAL).read_bytes()
        pending = source.split(b'void lsf_node_setup_pending(',1)[1].split(b'void lsf_node_setup_unexpected(',1)[0]
        for item in (b'setup_error != -ECANCELED',b'requested != 1',b'!owned->retirement',
                b'owned->queued',b'owned->returned',b'pci_record->phase != LSF_PREPAID_LIVE',
                b'fw_record->phase != LSF_PREPAID_LIVE'):
            self.assertIn(item,pending)
        self.assertNotIn(b'node->prefix_returned = 1u',pending)
        wait = source.split(b'static int lsf_node_setup_wait(',1)[1]
        child = wait.index(b'fw->phase == LSF_PREPAID_RETURNED')
        still_pending = wait.index(b'result = 1; /* Child finished',child)
        both = wait.index(b'pci->phase != LSF_PREPAID_RETURNED',still_pending)
        success = wait.index(b'node->prefix_returned = 1u',both)
        self.assertLess(child,still_pending)
        self.assertLess(still_pending,both)
        self.assertLess(both,success)
        self.assertIn(b'owned->revoked || owned->put_error',wait)
        for forbidden in (b'free_pages(',b'kfree(',b'request_irq(',b'register_netdevice('):
            self.assertNotIn(forbidden,source)


class Q35NodePciFixupControls(unittest.TestCase):
    @staticmethod
    def serial():
        marker = (b'[    2.345679] LSFQ35PCIFIXUP1 entries=125 matches=0 dispatcher=1 '
            b'intxCheck=0 barProbe=0 registered=0\n')
        return Q35NodePciSetupControls.serial().replace(
            b'LSFNODESETUP1 childAck=1', marker+b'LSFNODESETUP1 childAck=1')

    def test_original_dispatch_no_match_requires_bounded_ordered_marker(self):
        raw = self.serial()
        observed = owner.node_fixup_serial(raw)
        self.assertEqual(observed['pciEarlyFixup']['linkedEntries'], 125)
        self.assertEqual(observed['pciEarlyFixup']['matchingCallbacks'], 0)
        self.assertTrue(observed['pciEarlyFixup']['originalDispatcherReached'])
        for key in ('intxMaskCheckReached','barProbeReached','registered','callbacksQualified'):
            self.assertFalse(observed['pciEarlyFixup'][key])
        for bad in (raw.replace(b'entries=125', b'entries=0'),
                raw.replace(b'entries=125', b'entries=513'),
                raw.replace(b'matches=0', b'matches=1'),
                raw.replace(b'dispatcher=1', b'dispatcher=0'),
                raw.replace(b'intxCheck=0', b'intxCheck=1'),
                raw.replace(b'barProbe=0', b'barProbe=1'),
                raw.replace(b'LSFQ35PCIFIXUP1', b'WRONGMARKER'),
                raw + b'[    2.345679] LSFQ35PCIFIXUP1 entries=1 matches=0 dispatcher=1 intxCheck=0 barProbe=0 registered=0\n'):
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                owner.node_fixup_serial(bad)

    def test_source_capture_and_incomplete_projection_refuse(self):
        captured = owner.node_fixup_capture(owner.ROOT)
        self.assertEqual(set(captured), {owner.FIXUP_PROJECTOR, owner.FIXUP_MATERIAL})
        self.assertTrue(all(captured.values()))
        with self.assertRaises(ValueError):
            owner.node_fixup_compose({}, captured, b'')
        with self.assertRaises(ValueError):
            owner.node_fixup_compose({}, {}, b'')

    def test_linked_table_and_owned_completion_are_fail_closed(self):
        from importlib.util import module_from_spec, spec_from_file_location
        path = owner.ROOT/owner.FIXUP_PROJECTOR
        spec = spec_from_file_location('q35_fixup_control_projector', path)
        stage = module_from_spec(spec); spec.loader.exec_module(stage)
        raw = repr(stage.OPERATIONS)
        for predicate in ('__start_pci_fixups_early','__end_pci_fixups_early',
                'lsf_pci_fixup_matches(dev, f)','bytes / sizeof(*f) > 512u',
                'is_kernel_rodata(first)','is_kernel_rodata(last - 1)', 'STRICT_KERNEL_RWX',
                'f->class_shift >= 32u','lsf_fixup_before != lsf_fixup_after',
                'lsf_node_fixup_reached(dev, lsf_fixup_after)', 'return -ECANCELED'):
            self.assertIn(predicate, raw)
        material = (owner.ROOT/owner.FIXUP_MATERIAL).read_text(encoding='utf8')
        for predicate in ('lsf_node_constructor_actor_current()', 'node->prefix_fixup',
                'lsf_node_setup_records_locked', 'pci_record->phase != LSF_PREPAID_LIVE',
                'fw_record->phase != LSF_PREPAID_LIVE', 'factory.pool.poisoned = 1u'):
            self.assertIn(predicate, material)


class Q35NodePciIntxControls(unittest.TestCase):
    @staticmethod
    def serial():
        raw = Q35NodePciFixupControls.serial()
        old = b'intxCheck=0 barProbe=0 registered=0\n'
        replacement = (b'intxCheck=1 barProbe=0 registered=0\n'
            b'[    2.345680] LSFQ35PCIINTX1 command=0007 pin=1 line=255 '
            b'restored=1 barProbe=0 registered=0\n')
        assert raw.count(old) == 1
        return raw.replace(old, replacement)

    def test_marker_requires_saved_word_and_ordered_original_owner(self):
        raw = self.serial()
        observation = owner.node_intx_serial(raw)
        self.assertEqual(observation['pciIntx']['originalCommand'], 7)
        self.assertTrue(observation['pciIntx']['savedCommandRestored'])
        for name in ('irqFundingQualified', 'sharedInterruptCustodyQualified', 'physicalBankRetired'):
            self.assertFalse(observation['pciIntx'][name])
        for bad in (raw.replace(b'command=0007', b'command=0003'),
                    raw.replace(b'command=0007', b'command=0407'),
                    raw.replace(b'pin=1', b'pin=0'), raw.replace(b'line=255', b'line=256'),
                    raw.replace(b'restored=1', b'restored=0'),
                    raw.replace(b'intxCheck=1', b'intxCheck=0'),
                    raw.replace(b'LSFQ35PCIINTX1', b'OTHER'),
                    raw.replace(b'barProbe=0', b'barProbe=1', 1),
                    raw + b'[    2.345680] LSFQ35PCIINTX1 command=0007 pin=1 line=255 restored=1 barProbe=0 registered=0\n'):
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                owner.node_intx_serial(bad)

    def test_selected_irq_state_is_fenced_on_both_sides_of_the_write(self):
        source = (owner.ROOT/owner.INTX_VIRTIO).read_text(encoding='utf8')
        before = source.split("b'    pci_default_write_config(pci_dev, address, val, len);\\n'", 1)
        self.assertEqual(len(before), 2)
        self.assertIn('pci_dev->irq_state ||', before[0])
        self.assertIn('pci_dev->irq_state ||', before[1])
        self.assertIn('grabbed=0 irq=0 master=1', before[1])

    def test_source_capture_and_unbound_projection_refuse(self):
        captured = owner.node_intx_capture(owner.ROOT)
        self.assertEqual(set(captured), {owner.INTX_PROJECTOR, owner.INTX_FACTORY,
            owner.INTX_PROBE, owner.INTX_SINK, owner.INTX_VIRTIO})
        with self.assertRaises(ValueError):
            owner.node_intx_compose({}, captured)
        with self.assertRaises(ValueError):
            owner.node_intx_compose({}, {})

    def test_exact_actor_forward_and_restore_only_are_distinct(self):
        material = (owner.ROOT/owner.INTX_FACTORY).read_text(encoding='utf8')
        for predicate in ('node->prefix_task != current', 'node->mm != current->mm',
                'node->tgid != task_tgid(current)', 'node->cred != current_cred()',
                'node->net != current->nsproxy->net_ns', 'lsf_node_setup_records_locked',
                'pci_record->phase != LSF_PREPAID_LIVE', 'fw_record->phase != LSF_PREPAID_LIVE'):
            self.assertIn(predicate, material)
        forward_start = 'int lsf_node_intx_forward(struct pci_dev *pci)\n{'
        forward_end = 'int lsf_node_intx_preflight(struct pci_dev *pci, u16 original)\n{'
        restore_start = 'int lsf_node_intx_claim_restore(struct pci_dev *pci, u16 original)\n{'
        restore_end = 'int lsf_node_intx_restore_written(struct pci_dev *pci, u16 original)\n{'
        for marker in (forward_start, forward_end, restore_start, restore_end):
            self.assertEqual(material.count(marker), 1, marker)
        forward = material.split(forward_start, 1)[1].split(forward_end, 1)[0]
        restore = material.split(restore_start, 1)[1].split(restore_end, 1)[0]
        self.assertIn('lsf_node_constructor_actor_current()', forward)
        self.assertNotIn('lsf_node_constructor_actor_current()', restore)
        self.assertIn('node->prefix_intx_saved == original', restore)
        self.assertIn('LSF_NODE_INTX_RESTORE_CLAIMED', restore)
        self.assertNotIn('pci_write_config', restore)


class Q35NodeKvmLaunchControls(unittest.TestCase):
    @staticmethod
    def record():
        return {'uid':1001, 'euid':1001, 'gid':1001, 'egid':1001,
            'groups':[4,100,118,999,1001], 'label':'unconfined',
            'entry':{'symlink':False,'characterDevice':True,'mode':8624,'device':7,'inode':460,
                'rdev':2792,'major':10,'minor':232,'ownerUid':0,'ownerGid':993,
                'readWrite':True},
            'statErrno':None,'opened':True,'openErrno':None,'sameEntry':True}

    @staticmethod
    def receipt():
        after = {'uid':1001, 'euid':1001, 'gid':1001, 'egid':1001,
            'groups':[4,100,118,999,1001], 'mode':8624,'device':7,'inode':460,
            'rdev':2792,'major':10,'minor':232,'ownerUid':0,'ownerGid':993}
        return {'kvmAccess':{'after':after,'aclAfter':[
            'user::rw-','user:1001:rw-','group::rw-','mask::rw-','other::---']}}

    def test_child_probe_reports_real_open_and_denial_without_a_vm(self):
        import contextlib, io, os, stat
        from types import SimpleNamespace
        entry=SimpleNamespace(st_mode=stat.S_IFCHR|0o660,st_dev=7,st_ino=460,
            st_rdev=2792,st_uid=0,st_gid=993)
        for denied in (False,True):
            with self.subTest(denied=denied), contextlib.ExitStack() as stack:
                for name,value in (('getuid',1001),('geteuid',1001),('getgid',1001),
                                   ('getegid',1001),('getgroups',[4,100,118,999,1001])):
                    stack.enter_context(patch.object(os,name,return_value=value,create=True))
                stack.enter_context(patch.object(os,'major',return_value=10,create=True))
                stack.enter_context(patch.object(os,'minor',return_value=232,create=True))
                stack.enter_context(patch.object(os,'O_CLOEXEC',0,create=True))
                stack.enter_context(patch.object(os,'O_NOFOLLOW',0,create=True))
                stack.enter_context(patch.object(os,'lstat',return_value=entry))
                stack.enter_context(patch.object(os,'fstat',return_value=entry))
                stack.enter_context(patch.object(os,'access',return_value=True))
                close=stack.enter_context(patch.object(os,'close'))
                stack.enter_context(patch.object(os,'open',
                    side_effect=PermissionError(13,'denied') if denied else None,
                    return_value=123))
                stack.enter_context(patch('builtins.open',return_value=io.BytesIO(b'unconfined\n')))
                output=stack.enter_context(patch('sys.stdout',new_callable=io.StringIO))
                exec(compile(programme._NODE_KVM_OPEN_PROBE,'<fixed KVM probe>','exec'),{})
                row=json.loads(output.getvalue())
                self.assertTrue(row['entry']['readWrite'])
                self.assertEqual(row['opened'],not denied)
                self.assertEqual(row['openErrno'],13 if denied else None)
                self.assertEqual(row['sameEntry'],None if denied else True)
                self.assertEqual(close.call_count,0 if denied else 1)

    def test_same_owned_child_requires_actual_matching_open_and_exact_acl(self):
        record = self.record(); receipt = self.receipt(); calls = []
        def run(label,*argv,seconds):
            calls.append((label,argv,seconds))
            if label.endswith('-open'):
                self.assertEqual(argv[:4],(programme.sys.executable,'-I','-B','-c'))
                self.assertEqual(argv[4],programme._NODE_KVM_OPEN_PROBE)
                return json.dumps(record).encode()
            return b'user::rw-\nuser:1001:rw-\ngroup::rw-\nmask::rw-\nother::---\n'
        row = programme.node_kvm_observe(run,receipt,'before-boot',require_open=True)
        self.assertEqual(row['child'],record)
        self.assertEqual(row['acl'],receipt['kvmAccess']['aclAfter'])
        self.assertEqual([call[0] for call in calls],
            ['node-KVM-before-boot-open','node-KVM-before-boot-ACL'])
        self.assertEqual(receipt['kvmLaunchChecks'],[row])

    def test_access_true_but_open_denied_is_retained_and_refused(self):
        record=self.record();record.update(opened=False,openErrno=13,sameEntry=None)
        receipt=self.receipt()
        def run(label,*argv,seconds):
            return (json.dumps(record).encode() if label.endswith('-open') else
                b'user::rw-\nuser:1001:rw-\ngroup::rw-\nmask::rw-\nother::---\n')
        with self.assertRaisesRegex(ValueError,'node-KVM-probe-real-open-required'):
            programme.node_kvm_observe(run,receipt,'initial',require_open=True)
        self.assertTrue(receipt['kvmLaunchChecks'][0]['child']['entry']['readWrite'])
        self.assertEqual(receipt['kvmLaunchChecks'][0]['child']['openErrno'],13)
        after=self.receipt()
        observed=programme.node_kvm_observe(run,after,'after-boot-failure',require_open=False)
        self.assertEqual(observed['child']['openErrno'],13)

    def test_changed_identity_acl_and_malformed_records_fail_closed(self):
        for change,expected in (('inode','identity-changed'),('acl','ACL-changed'),
                                ('schema','closed-record'),('inconsistent','record-consistency')):
            with self.subTest(change=change):
                record=self.record();receipt=self.receipt()
                if change=='inode':record['entry']['inode']+=1
                if change=='schema':record['unexpected']=True
                if change=='inconsistent':record['openErrno']=13
                def run(label,*argv,seconds):
                    if label.endswith('-open'):return json.dumps(record).encode()
                    if change=='acl':return b'user::rw-\ngroup::rw-\nother::---\n'
                    return b'user::rw-\nuser:1001:rw-\ngroup::rw-\nmask::rw-\nother::---\n'
                with self.assertRaisesRegex(ValueError,expected):
                    programme.node_kvm_observe(run,receipt,'before-boot',require_open=True)


class Q35NodePciIntxOwnerControls(unittest.TestCase):
    def test_trace_configuration_is_explicit_and_refuses_replacement(self):
        from tools import q35_intx_owner as host
        command = ('/absolute/qemu', '-machine', 'pc-q35-11.1')
        traced = host.trace_argv(command)
        self.assertEqual(traced[:len(command)], command)
        configure = (owner.ROOT/'tools/qualify_host_stream_kernel_native_vm.py').read_text(encoding='utf8')
        self.assertIn("*(['--enable-trace-backends=log'] if intx else [])", configure)
        self.assertEqual(traced[len(command):], tuple(part for event in host.EVENTS
            for part in ('-trace', 'enable='+event)))
        for bad in (command+('-trace', 'old'), command+('-D', 'old'), list(command)):
            with self.subTest(argv=bad), self.assertRaises(ValueError):
                host.trace_argv(bad)

    def test_loss_probe_requires_exact_sink_and_only_accepts_exit_74(self):
        import stat
        import time
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools import q35_intx_owner as host
        class Commands:
            root = '/owned'
            environment = {}
            deadline = time.monotonic()+10
            def __init__(self): self.records, self.retained = [], []
            def retain(self,label,result): self.retained.append((label,result.output,result.stderr))
        class Result:
            stdout, stderr = b'', b''
            def __init__(self, code): self.returncode = code
        device = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=123)
        argv = ('/absolute/qemu','-trace','enable=pci_cfg_read')
        with patch.object(host.Path, 'lstat', return_value=device), \
             patch.object(host.os, 'major', return_value=1, create=True), \
             patch.object(host.os, 'minor', return_value=7, create=True), \
             patch.object(host.build_process, 'run_bounded_result', return_value=Result(74)) as invoke:
            commands=Commands(); result=host.probe_loss(commands,argv)
            self.assertEqual(result['actualExit'],74)
            self.assertTrue(commands.records[0]['descendantsCleaned'])
            self.assertEqual(invoke.call_args.args[0][-2:], ['-D',str(host.Path('/dev/full'))])
        for code in (0, 1, 75):
            with self.subTest(code=code), patch.object(host.Path, 'lstat', return_value=device), \
                 patch.object(host.os, 'major', return_value=1, create=True), \
                 patch.object(host.os, 'minor', return_value=7, create=True), \
                 patch.object(host.build_process, 'run_bounded_result', return_value=Result(code)), \
                 self.assertRaises(ValueError):
                host.probe_loss(Commands(),argv)
        device.st_mode = stat.S_IFREG
        with patch.object(host.Path, 'lstat', return_value=device), \
             patch.object(host.build_process, 'run_bounded_result') as invoke, self.assertRaises(ValueError):
            host.probe_loss(Commands(),argv)
        invoke.assert_not_called()


"""Bounded grammar/refusal controls; synthetic data is not a VM observation."""
import unittest
from tools import q35_intx_trace as trace

def cfg(kind, offset, value, device=b'virtio-net-pci'):
    arrow = b'->' if kind == b'read' else b'<-'
    return b'pci_cfg_'+kind+b' '+device+b' 00:03.0 @0x'+format(offset, 'x').encode()+b' '+arrow+b' 0x'+format(value, 'x').encode()

def route(index, parent, pic):
    return [b'pci_route_irq IRQ '+str(index).encode()+b' @/machine/peripheral/net0 -> IRQ '+str(parent).encode()+b' @root-complex',
            b'x86_gsi_interrupt GSI interrupt #'+str(16+parent).encode()+b' level:0',
            b'x86_gsi_interrupt GSI interrupt #'+str(pic).encode()+b' level:0']

def example():
    rows = [cfg(b'read', off, value) for off, value in trace.PREFIX]
    rows += [cfg(b'read', 4, 7), cfg(b'read', 0x3d, 1), cfg(b'read', 0x3c, 0xff),
             cfg(b'read', 4, 7), cfg(b'write', 4, 0x407)]
    for i, parent in enumerate((7, 4, 5, 6)):
        rows += route(i, parent, i+8)
    rows += [b'lsf_q35_virtio_guard old=0x7 new=0x407 status=0 isr=0 disabled=0 broken=0 started=0 kick=0 vhost=0 ioeventfd=0 grabbed=0 irq=0 master=1 vga=0 mappings=stable bql=1',
             cfg(b'read', 4, 0x407), cfg(b'write', 4, 7)]
    for i, parent in enumerate((7, 4, 5, 6)):
        rows += route(i, parent, i+8)
    rows += [b'lsf_q35_virtio_guard old=0x407 new=0x7 status=0 isr=0 disabled=0 broken=0 started=0 kick=0 vhost=0 ioeventfd=0 grabbed=0 irq=0 master=1 vga=0 mappings=stable bql=1',
             cfg(b'read', 4, 7), cfg(b'read', 0x3d, 1), cfg(b'read', 0x3c, 0xff),
             cfg(b'read', 4, 7), cfg(b'read', 0x3d, 1), cfg(b'read', 0x3c, 0xff)]
    rows += [cfg(b'read', off, value) for off, value in reversed(trace.PREFIX)]
    return b'\n'.join(rows)+b'\n'

class TraceRefusalControls(unittest.TestCase):
    def test_expected_complete_pattern_is_only_a_source_model(self):
        result = trace.inspect(example(), 7, 1, 0xff)
        self.assertEqual(result['selectedCommandWrites'], 2)
        self.assertEqual(result['selectedRouteCallbacks'], 8)
        self.assertEqual(result['virtioGuardPasses'], 2)
        self.assertEqual(result['apicGsi'], [23, 20, 21, 22])
        self.assertEqual(result['picGsi'], [8, 9, 10, 11])
        self.assertFalse(result['traceDeliveryQualified'])
        self.assertFalse(result['irqFundingQualified'])

    def test_missing_extra_or_asserted_callbacks_refuse(self):
        raw = example()
        cases = (raw.replace(b'x86_gsi_interrupt GSI interrupt #23 level:0\n', b'', 1),
                 raw.replace(b'x86_gsi_interrupt GSI interrupt #23 level:0',
                             b'x86_gsi_interrupt GSI interrupt #23 level:1', 1),
                 raw.replace(b'x86_gsi_interrupt GSI interrupt #8 level:0\n',
                             b'x86_gsi_interrupt GSI interrupt #8 level:0\n'
                             b'x86_gsi_interrupt GSI interrupt #8 level:0\n', 1),
                 raw.replace(b'@/machine/peripheral/net0', b'@/machine/peripheral/foreign', 1),
                 raw.replace(b'x86_gsi_interrupt GSI interrupt #8 level:0',
                             b'x86_gsi_interrupt GSI interrupt #9 level:0', 1),
                 raw.replace(b'status=0 isr=0 disabled=0 broken=0',
                             b'status=0 isr=0 disabled=1 broken=0', 1),
                 raw.replace(b'grabbed=0 irq=0 master=1', b'grabbed=0 irq=1 master=1', 1),
                 raw.replace(b'lsf_q35_virtio_guard old=0x7 new=0x407 status=0 isr=0 disabled=0 broken=0 started=0 kick=0 vhost=0 ioeventfd=0 grabbed=0 irq=0 master=1 vga=0 mappings=stable bql=1\n', b'', 1))
        for case in cases:
            with self.subTest(case=case[:80]), self.assertRaises(ValueError):
                trace.inspect(case, 7, 1, 0xff)

    def test_config_mutation_and_unbounded_or_ambiguous_trace_refuse(self):
        raw = example()
        first = b'\n'.join(cfg(b'read', *row) for row in trace.PREFIX)+b'\n'
        cases = (raw.replace(cfg(b'write', 4, 0x407), cfg(b'write', 4, 0x405), 1),
                 raw.replace(cfg(b'write', 4, 7), cfg(b'write', 0x10, 7), 1),
                 first+raw, raw[:-1], raw+b'trace event missing\n',
                 raw+b'x'*(trace.MAX_TRACE+1),
                 raw.replace(cfg(b'read', 0x3d, 1), cfg(b'read', 0x3d, 2), 1))
        for case in cases:
            with self.subTest(length=len(case)), self.assertRaises(ValueError):
                trace.inspect(case, 7, 1, 0xff)

if __name__ == '__main__':
    unittest.main(verbosity=2)
