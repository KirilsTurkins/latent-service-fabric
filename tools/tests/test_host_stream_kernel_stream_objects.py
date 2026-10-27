"""Pure controls only: no kernel archive, compiler, SDK or process execution."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_host_stream_kernel_stream_objects as owner

def _layout_test_object(tu, *, fields=None, writable=False, relocation=False, symbol_size=None):
    # SYNTHETIC parser bytes only. These are never assembly/qualification facts.
    from tools import host_stream_kernel_stream_layout as layout
    index,descriptor=layout.descriptor(tu)
    if fields is None:fields={name:{'value':64,**({'alignment':8} if align is not None else {})}
        for name,_,align,_,_ in descriptor}
    cells=[layout.MAGIC,layout.VERSION,index,len(descriptor)]
    for field_id,(name,_,align,_,_) in enumerate(descriptor,1):
        cells.extend((field_id,1+(align is not None),fields[name]['value']))
        if align is not None:cells.append(fields[name]['alignment'])
    table=struct.pack('<'+'Q'*len(cells),*cells)
    names=b'\0';name_offsets={}
    for name in ('.shstrtab','.strtab','.symtab',layout.section_name(index),'.rela.test'):
        name_offsets[name]=len(names);names+=name.encode()+b'\0'
    symbol_strings=b'\0'+layout.symbol_name(index).encode()+b'\0'
    raw=bytearray(64);sections=[(0,)*10]
    def section(name,kind,flags,data,alignment,entsize=0,link=0,info=0):
        raw.extend(b'\0'*((-len(raw))%alignment));offset=len(raw);raw.extend(data)
        sections.append((name_offsets[name],kind,flags,0,offset,len(data),link,info,alignment,entsize))
    section('.shstrtab',3,0,names,1)
    section('.strtab',3,0,symbol_strings,1)
    symbols=b'\0'*24+struct.pack('<IBBHQQ',1,1,0,4,0,len(table) if symbol_size is None else symbol_size)
    section('.symtab',2,0,symbols,8,24,2,2)
    section(layout.section_name(index),1,3 if writable else 2,table,8)
    if relocation:section('.rela.test',4,0,struct.pack('<QQq',0,(1<<32)|1,0),8,24,3,4)
    raw.extend(b'\0'*((-len(raw))%8));shoff=len(raw)
    for row in sections:raw.extend(struct.pack('<IIQQQQIIQQ',*row))
    raw[:7]=b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHIQQQIHHHHHH',raw,16,1,62,1,0,0,shoff,0,64,0,0,64,len(sections),1)
    return bytes(raw)


def _layout_test_fields():
    # Deliberately artificial small values. Fixed-profile constants and cross-TU
    # shapes are made internally consistent solely to test report behavior.
    from tools import host_stream_kernel_stream_layout as layout
    values={tu:{name:{'value':64,**({'alignment':8} if align is not None else {})}
        for name,_,align,_,_ in fields} for tu,fields in layout.DESCRIPTOR if fields}
    for tu in ('drivers/net/virtio_net.c','drivers/virtio/virtio_ring.c'):
        for name,value in {'page.bytes':4096,'cache.bytes':64,'rx.descriptors':32,'tx.descriptors':64}.items():
            values[tu][name]['value']=value
    factory=values['net/factory.c']
    for name,value in {'backing.bytes':524288,'bootstrap.ceiling':1048576,'infra.offset':327680,
        'infra.bytes':196608,'tcp.bytes':98304,'dns.bytes':65536,'records.count':256,
        'owners.count':64,'application_contexts':4,'cpus':64,'global.records':16384}.items():
        factory[name]['value']=value
    values['drivers/virtio/virtio_pci_common.c']['msix.offstack_enabled']['value']=0
    values['drivers/virtio/virtio_pci_common.c']['msix.optional_backing']['value']=0
    return values


class StreamObjectOwner(unittest.TestCase):
    def test_original_deadline_rejects_invalid_and_expired_start_before_work(self):
        for value in (None, True, 1, float('nan'), float('inf'), -1.0, 101.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                owner.deadline(value, now=100.0)
        with self.assertRaises(ValueError):
            owner.deadline(0.0, now=1315.0)
        self.assertEqual(owner.deadline(10.0, now=20.0), 1330.0)

    def test_public_gate_rejects_private_members_and_reserves_admission_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); output=root/'public';output.mkdir()
            private=root/'private';private.mkdir();(private/'key').write_bytes(b'not-public')
            receipt=b'{"status":"failed","stage":"eighteen-objects"}\n'
            (output/'receipt.json').write_bytes(receipt)
            record=owner.admit(output)
            self.assertEqual(set(record['files']), {'receipt.json'})
            self.assertEqual((output/'receipt.json').read_bytes(),receipt)
            self.assertEqual((private/'key').read_bytes(),b'not-public')
            (output/'private-key').write_bytes(b'never-upload')
            with self.assertRaises(ValueError):owner.admit(output)
            (output/'private-key').unlink()
            with patch.object(owner,'MAX_PUBLIC',owner.MAX_DOCUMENT+len(receipt)-1):
                with self.assertRaises(ValueError):owner.admit(output)
            with patch.object(owner,'MAX_PUBLIC',owner.MAX_DOCUMENT+len(receipt)):
                self.assertLessEqual(owner.admit(output)['payloadBytes']+len((output/'ADMISSION.json').read_bytes()),owner.MAX_PUBLIC)

    def test_object_gate_accepts_relocatable_without_claiming_link_and_refuses_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'one.o'; raw=bytearray(128)
            raw[:7]=b'\x7fELF\x02\x01\x01'
            struct.pack_into('<HHI',raw,16,1,62,1)
            struct.pack_into('<Q',raw,40,64)
            struct.pack_into('<HH',raw,58,64,1)
            path.write_bytes(raw)
            self.assertEqual(owner.object_identity(path),owner.identity(bytes(raw)))
            struct.pack_into('<H',raw,16,2);path.write_bytes(raw)
            with self.assertRaises(ValueError):owner.object_identity(path)

    def test_classdir_source_freeze_is_exact_and_preserves_default_source_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in owner.CLASSDIR_SOURCE_PATHS:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                raw=(owner.ROOT/name).read_bytes()
                if name=='tools/host_stream_kernel_stream_classdir.py':
                    # TEST-ONLY exact historical positive fixture. The extended
                    # current helper is bound in full ONLY by the new52 mode;
                    # production old50 still refuses its changed whole bytes.
                    raw=raw[:10630]
                    self.assertEqual(owner.identity(raw),{'bytes':10630,
                        'sha256':'d0f71e8566f9e8db028855737857a9671ae6e3412df9e745817b06378f24878f'})
                target.write_bytes(raw)
            normal=owner.selected_sources(root)
            current=owner.selected_sources(root,classdir=True)
            self.assertEqual(len(normal),47)
            self.assertEqual(len(current),50)
            self.assertTrue(all(current[name]==value for name,value in normal.items()))
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir=1)
            path=root/'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-classdir.c'
            path.write_bytes(path.read_bytes()+b'\n')
            self.assertEqual(owner.selected_sources(root),normal)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir=True)

    def test_classdir_public_gate_refuses_other_original_object_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            (output/'receipt.json').write_bytes(b'{"status":"failed","stage":"classdir-objects"}\n')
            record=owner.admit(output,classdir=True)
            self.assertEqual(set(record['files']),{'receipt.json'})
            self.assertEqual(set(owner.CLASSDIR_TARGETS),
                {'net/factory.o','drivers/base/core.o','lib/kobject.o','net/core/net-sysfs.o'})
            self.assertIsNotNone(owner.public_allowed('objects/net/socket.o'))
            self.assertIsNone(owner.public_allowed('objects/net/socket.o',classdir=True))
            forbidden=output/'objects/net/socket.o';forbidden.parent.mkdir(parents=True)
            forbidden.write_bytes(b'rejected before publication')
            with self.assertRaises(ValueError):owner.admit(output,classdir=True)

    def test_classdir_kernfs_freeze_binds_full_projector_and_keeps_historical_modes_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in owner.REGISTRATION_SOURCE_PATHS:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((owner.ROOT/name).read_bytes())
            current=owner.selected_sources(root,classdir_kernfs=True)
            normal=owner.selected_sources(root)
            self.assertEqual(len(current),52)
            self.assertEqual(len(normal),47)
            self.assertTrue(all(current[name]==value for name,value in normal.items()))
            helper='tools/host_stream_kernel_stream_classdir.py'
            self.assertEqual(current[helper],owner.identity((owner.ROOT/helper).read_bytes()))
            self.assertGreater(current[helper]['bytes'],10630)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir=True)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir_kernfs=1)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir=True,classdir_kernfs=True)
            path=root/'research/standard-outbound/linux-6.12-lineage/factory-stream-classdir-registration.c'
            path.write_bytes(path.read_bytes()+b'\n')
            self.assertEqual(owner.selected_sources(root),normal)
            with self.assertRaises(ValueError):owner.selected_sources(root,classdir_kernfs=True)

    def test_classdir_kernfs_public_gate_keeps_exact_nine_targets_and_current_only_channels(self):
        expected={'net/factory.o','drivers/base/core.o','lib/kobject.o','fs/sysfs/dir.o',
            'fs/kernfs/dir.o','lib/idr.o','lib/radix-tree.o','security/security.o','security/selinux/hooks.o'}
        self.assertEqual(set(owner.mode_targets(classdir_kernfs=True)),expected)
        self.assertEqual(len(owner.mode_targets()),18)
        self.assertEqual(len(owner.mode_targets(classdir=True)),4)
        self.assertIsNotNone(owner.public_allowed('logs/00-baseline-fetch.stdout.txt',classdir_kernfs=True))
        self.assertIsNone(owner.public_allowed('logs/00-baseline-fetch.stdout.txt'))
        self.assertIsNone(owner.public_allowed('logs/00-baseline-fetch.stdout.txt',classdir=True))
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            (output/'receipt.json').write_bytes(b'{"status":"failed","stage":"classdir-kernfs-objects"}\n')
            self.assertEqual(set(owner.admit(output,classdir_kernfs=True)['files']),{'receipt.json'})
            for name in ('net/socket.o','net/core/net-sysfs.o'):
                self.assertIsNone(owner.public_allowed('objects/'+name,classdir_kernfs=True))
            forbidden=output/'objects/net/core/net-sysfs.o';forbidden.parent.mkdir(parents=True)
            forbidden.write_bytes(b'unchanged TU is outside this programme')
            with self.assertRaises(ValueError):owner.admit(output,classdir_kernfs=True)

    def test_netdev_directory_freeze_preserves_all_fifty_two_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in owner.DIRECTORY_SOURCE_PATHS:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((owner.ROOT/name).read_bytes())
            original=owner.selected_sources(root,classdir_kernfs=True)
            current=owner.selected_sources(root,netdev_directory=True)
            self.assertEqual(len(original),52)
            self.assertEqual(len(current),55)
            self.assertTrue(all(current[name]==value for name,value in original.items()))
            self.assertEqual(len(owner.selected_sources(root)),47)
            for kwargs in ({'netdev_directory':1},
                {'netdev_directory':True,'classdir':True},
                {'netdev_directory':True,'classdir_kernfs':True}):
                with self.assertRaises(ValueError):owner.selected_sources(root,**kwargs)
            path=root/'tools/host_stream_kernel_stream_netdev_directory.py'
            path.write_bytes(path.read_bytes()+b'\n')
            self.assertEqual(owner.selected_sources(root,classdir_kernfs=True),original)
            with self.assertRaises(ValueError):owner.selected_sources(root,netdev_directory=True)

    def test_netdev_directory_public_gate_is_closed_to_nine_changed_targets(self):
        expected={'net/factory.o','drivers/base/core.o','lib/kobject.o','fs/sysfs/dir.o',
            'fs/kernfs/dir.o','lib/idr.o','lib/radix-tree.o','security/security.o','security/selinux/hooks.o'}
        self.assertEqual(set(owner.mode_targets(netdev_directory=True)),expected)
        for flag in ({},{'classdir':True},{'classdir_kernfs':True}):
            self.assertIsNone(owner.public_allowed('logs/00-netdev-directory-objects.stdout.txt',**flag))
        self.assertIsNotNone(owner.public_allowed('logs/00-baseline-fetch.stdout.txt',netdev_directory=True))
        self.assertIsNotNone(owner.public_allowed('logs/00-netdev-directory-objects.stdout.txt',netdev_directory=True))
        for stage in ('eighteen-objects','classdir-objects','classdir-kernfs-objects'):
            self.assertIsNone(owner.public_allowed('logs/00-'+stage+'.stdout.txt',netdev_directory=True))
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            (output/'receipt.json').write_bytes(b'{"status":"failed","stage":"netdev-directory-objects"}\n')
            self.assertEqual(set(owner.admit(output,netdev_directory=True)['files']),{'receipt.json'})
            forbidden=output/'objects/net/core/net-sysfs.o';forbidden.parent.mkdir(parents=True)
            forbidden.write_bytes(b'unchanged TU is outside the selected programme')
            with self.assertRaises(ValueError):owner.admit(output,netdev_directory=True)

    def test_layout_source_freeze_preserves_notify_and_all_prior_modes(self):
        from tools import host_stream_kernel_stream_layout as layout
        current=owner.selected_sources(owner.ROOT,netdev_layout=True)
        original=owner.selected_sources(owner.ROOT,netdev_directory=True)
        self.assertEqual(len(current),59)
        self.assertEqual(len(owner.NOTIFY_SOURCE_PATHS),58)
        self.assertEqual(len(original),55)
        self.assertTrue(all(current[name]==row for name,row in original.items()))
        self.assertEqual(owner.LAYOUT_TARGETS,tuple(tu[:-2]+'.o' for tu,_ in layout.DESCRIPTOR))
        self.assertEqual(sum(len(fields) for _,fields in layout.DESCRIPTOR),93)
        self.assertEqual(sum(bool(fields) for _,fields in layout.DESCRIPTOR),8)
        for tu,fields in layout.DESCRIPTOR:
            block=layout.source_block(tu)
            if not fields:
                self.assertEqual(block,'');continue
            self.assertIn(layout.symbol_name(layout.descriptor(tu)[0]),block)
            for _,expression,align,_,_ in fields:
                self.assertIn(expression,block)
                if align is not None:self.assertIn(align,block)
            if layout.uses_emitter(fields):
                self.assertIn('no_instrument_function',block)
                self.assertEqual(block.count('"i" ('),sum(1+(a is not None) for _,_,a,_,_ in fields))
                self.assertNotIn('return ',block)
        for kwargs in ({'netdev_layout':1},{'netdev_layout':True,'netdev_directory':True},
            {'netdev_layout':True,'classdir':True},{'netdev_layout':True,'classdir_kernfs':True}):
            with self.assertRaises(ValueError):owner.mode_targets(**kwargs)
        self.assertEqual(owner.public_allowed('layout.json',netdev_layout=True),64*1024)
        for kwargs in ({},{'classdir':True},{'classdir_kernfs':True},{'netdev_directory':True}):
            self.assertIsNone(owner.public_allowed('layout.json',**kwargs))
        self.assertIsNone(owner.public_allowed('objects/net/socket.o',netdev_layout=True))
        self.assertIsNone(owner.public_allowed('logs/00-netdev-directory-objects.stdout.txt',netdev_layout=True))
        self.assertIsNotNone(owner.public_allowed('logs/00-netdev-layout-objects.stdout.txt',netdev_layout=True))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in owner.LAYOUT_SOURCE_PATHS:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((owner.ROOT/name).read_bytes())
            helper=root/'tools/host_stream_kernel_stream_layout.py'
            helper.write_bytes(helper.read_bytes()+b'\n')
            with self.assertRaises(ValueError):owner.selected_sources(root,netdev_layout=True)
            self.assertEqual(owner.selected_sources(root,netdev_directory=True),original)
        with self.assertRaises(ValueError):layout.transform({})

    def test_layout_elf_refuses_malformed_tables_and_reports_only_incomplete_lower_bound(self):
        from tools import host_stream_kernel_stream_layout as layout
        fields=_layout_test_fields()
        decoded={tu:layout.decode(_layout_test_object(tu,fields=rows),tu) for tu,rows in fields.items()}
        report=json.loads(layout.report_bytes(decoded))
        self.assertEqual(report['knownMinimum']['recordHighWater'],76)
        self.assertEqual(report['knownMinimum']['status'],'insufficient-to-prove-fit')
        self.assertIsNone(report['actualPreRxEntryCursor'])
        self.assertIsNone(report['actualPreRxEntryOccupiedRecords'])
        for flag in ('prefixComplete','compiledUsefulFit','runtimeQualified','consumerSelected',
            'whole738Complete','productExecution'):
            self.assertIs(report[flag],False)
        self.assertFalse(report['constructorDemandFacts']['returnedTemporaryBirthsReusable'])
        self.assertGreater(len(report['uncovered']),2)
        tu='drivers/net/virtio_net.c'
        for kwargs in ({'writable':True},{'relocation':True},{'symbol_size':0}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                layout.decode(_layout_test_object(tu,fields=fields[tu],**kwargs),tu)
        raw=_layout_test_object(tu,fields=fields[tu])
        shoff=struct.unpack_from('<Q',raw,40)[0]
        offset=struct.unpack_from('<Q',raw,shoff+4*64+24)[0]
        for delta in (0,8,16,24,32,40):
            bad=bytearray(raw);bad[offset+delta]^=1
            with self.subTest(cell=delta),self.assertRaises(ValueError):layout.decode(bytes(bad),tu)
        for changed in (raw[:63],raw[:-1],b'bad'+raw[3:]):
            with self.assertRaises(ValueError):layout.decode(changed,tu)
        pci='drivers/virtio/virtio_pci_common.c'
        fields[pci]['msix.optional_backing']['value']=1
        with self.assertRaises(ValueError):layout.decode(_layout_test_object(pci,fields=fields[pci]),pci)
        fields[pci]['msix.optional_backing']['value']=0
        fields[tu]['rx.head']['value']=16384
        decoded[tu]=layout.decode(_layout_test_object(tu,fields=fields[tu]),tu)
        overflow=json.loads(layout.report_bytes(decoded))
        self.assertEqual(overflow['knownMinimum']['status'],'decisive-lower-bound-overflow')
        self.assertFalse(overflow['compiledUsefulFit'])
        del decoded[pci]
        with self.assertRaises(ValueError):layout.report_bytes(decoded)

    def test_post_init_projection_keeps_whole_ordinary_body_and_original_unwind(self):
        from tools import host_stream_kernel_stream_post_init as post
        from tools.host_stream_kernel_constructor_failure import Editor
        # Actual source fragments only: no C compiler or notifier execution.
        fixture=json.loads((Path(__file__).parent/'fixtures/host_stream_kernel_post_init.json').read_bytes())
        self.assertTrue(fixture['sourceOnly'])
        self.assertFalse(fixture['compilerQualification'])
        raw=fixture['fragments']['net/core/dev.c::int register_netdevice(']
        original=post._body(raw,'net/core/dev.c','int register_netdevice(')
        editor=Editor(original);post._register(editor);code=editor.finish()
        self.assertIn(original[original.index('\n{\n')+1:],code)
        clone=post.function(code,'static int lsf_prepaid_stream_register_netdevice(')
        gate=clone.index('    {\n        struct virtio_device *same = NULL;')
        call=clone.index('\tret = call_netdevice_notifiers(NETDEV_POST_INIT, dev);\n')
        restored=(clone[:gate]+clone[call:]).replace(
            'static int lsf_prepaid_stream_register_netdevice(', 'int register_netdevice(',1)
        self.assertEqual(restored,original)
        self.assertEqual(clone.count('call_netdevice_notifiers(NETDEV_POST_INIT, dev)'),1)
        self.assertLess(clone.index('lsf_stream_post_init_chains(dev)'),call)
        self.assertIn('goto err_ifindex_release; /* No POST_INIT ran: no PRE_UNINIT. */',clone[:call])
        self.assertEqual(clone[call:],original[original.index('\tret = call_netdevice_notifiers(NETDEV_POST_INIT, dev);\n'):])
        before=code[:code.index('static int lsf_prepaid_stream_register_netdevice(')]
        self.assertNotIn('call_netdevice_notifiers(',before)
        self.assertNotIn('raw_notifier_call_chain(',before)
        self.assertEqual(len(post.CALLBACKS),4)
        for key,pin in post.BODIES.items():
            path,signature=key.split('::',1);text=fixture['fragments'][key]
            self.assertEqual(post._body(text,path,signature),text)
            changed=text.replace('\n{\n','\n{ /* altered original */\n',1)
            with self.assertRaises(ValueError):post._body(changed,path,signature)
            with self.assertRaises(ValueError):post._body('static inline '+text,path,signature)
        # New source does not alter the separately executed59-source tuple.
        self.assertEqual(len(owner.selected_sources(owner.ROOT,netdev_layout=True)),59)

    def test_post_init_instances_are_bound_before_next_and_both_chains_preflight(self):
        from tools import host_stream_kernel_stream_post_init as post
        fixture=json.loads((Path(__file__).parent/'fixtures/host_stream_kernel_post_init.json').read_bytes())
        for key in post.DECLARATIONS:
            path,prefix=key.split('::',1);text=fixture['fragments'][key]
            self.assertEqual(post._declaration(text,path,prefix),text)
            with self.assertRaises(ValueError):post._declaration(text.replace(' = {',' = { /* changed */',1),path,prefix)
            with self.assertRaises(ValueError):post._declaration('__attribute__((used)) '+text,path,prefix)
        for _,block,callback,priority,name in post.CALLBACKS:
            text=post._callback_source(block,callback,priority,name)
            self.assertLess(text.index('nb != &'+block),text.index('nb->notifier_call'))
            self.assertIn('nb->notifier_call == '+callback,text)
            self.assertIn('nb->priority == '+priority,text)
            self.assertNotIn('nb->next',text)
            self.assertNotIn(callback+'(',text)
        preflight=post._preflight_source()
        self.assertIn('ASSERT_RTNL();',preflight)
        self.assertIn('{ &dev_net(dev)->netdev_chain, &netdev_chain }',preflight)
        self.assertLess(preflight.index('if (!identity || (seen & identity)) return 0;'),
            preflight.index('nb = rcu_dereference_raw(nb->next);'))
        self.assertEqual(preflight.count('seen |= identity;'),1)
        self.assertNotIn('raw_notifier_call_chain(',preflight)
        self.assertNotIn('kzalloc(',preflight)
        self.assertNotIn('schedule_work(',preflight)
        with self.assertRaises(ValueError):post.transform({}, {})
        with self.assertRaises(ValueError):post.transform({str(i):b'fragment is not a whole input' for i in range(375)}, {})

    def test_post_init_owner_keeps_exact_eight_targets_and_denies_size_probe_union(self):
        current=owner.selected_sources(owner.ROOT,netdev_post_init=True)
        historical=owner.selected_sources(owner.ROOT,netdev_layout=True)
        self.assertEqual(len(current),62)
        self.assertEqual(len(historical),59)
        self.assertTrue(all(current[n]==row for n,row in historical.items()))
        self.assertEqual(owner.mode_targets(netdev_post_init=True),('net/core/dev.o',
            'drivers/net/virtio_net.o','net/ipv4/fib_frontend.o','net/factory.o',
            'net/ipv4/devinet.o','net/ipv6/addrconf.o','net/core/rtnetlink.o','drivers/virtio/virtio.o'))
        for kwargs in ({'netdev_post_init':1},{'netdev_post_init':True,'netdev_layout':True},
            {'netdev_post_init':True,'netdev_directory':True},{'netdev_post_init':True,'classdir':True},
            {'netdev_post_init':True,'classdir_kernfs':True}):
            with self.assertRaises(ValueError):owner.mode_targets(**kwargs)
        self.assertIsNone(owner.public_allowed('layout.json',netdev_post_init=True))
        self.assertIsNone(owner.public_allowed('objects/drivers/virtio/virtio_ring.o',netdev_post_init=True))
        self.assertIsNotNone(owner.public_allowed('objects/drivers/virtio/virtio.o',netdev_post_init=True))
        self.assertIsNotNone(owner.public_allowed('logs/00-baseline-fetch.stdout.txt',netdev_post_init=True))
        self.assertIsNotNone(owner.public_allowed('logs/00-netdev-post-init-objects.stdout.txt',netdev_post_init=True))
        for old in ('eighteen-objects','classdir-objects','classdir-kernfs-objects',
            'netdev-directory-objects','netdev-layout-objects'):
            self.assertIsNone(owner.public_allowed('logs/00-'+old+'.stdout.txt',netdev_post_init=True))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in owner.POST_INIT_SOURCE_PATHS:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((owner.ROOT/name).read_bytes())
            helper=root/'tools/host_stream_kernel_stream_post_init.py'
            helper.write_bytes(helper.read_bytes()+b'\n')
            with self.assertRaises(ValueError):owner.selected_sources(root,netdev_post_init=True)
            self.assertEqual(owner.selected_sources(root,netdev_layout=True),historical)
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            (output/'receipt.json').write_bytes(b'{"status":"failed","stage":"netdev-post-init-objects"}\n')
            self.assertEqual(set(owner.admit(output,netdev_post_init=True)['files']),{'receipt.json'})
            (output/'layout.json').write_bytes(b'{}\n')
            with self.assertRaises(ValueError):owner.admit(output,netdev_post_init=True)


    def test_constructor_bundle_physical_sources_and_logical_origins_are_closed(self):
        from tools import host_stream_kernel_stream_constructor as constructor
        current=owner.selected_sources(owner.ROOT,constructor_mmio=True)
        materials=owner.constructor_materials(owner.ROOT)
        self.assertEqual(len(current),65)
        self.assertEqual(materials['physicalInputs'],current)
        self.assertEqual(len(materials['logicalIdentities']),90)
        self.assertEqual(set(materials['logicalOrigins']),set(materials['logicalIdentities']))
        self.assertEqual(set(current),set(owner.POST_INIT_SOURCE_PATHS)|set(owner.CONSTRUCTOR_MMIO_ADDED_LIMITS))
        logical=constructor.constructor_sources()
        self.assertEqual(len(logical),26)
        for ordinal,(name,kind,length,sha) in enumerate(constructor.CONSTRUCTOR_BUNDLE_ROWS):
            self.assertNotIn(name,current)
            self.assertEqual(owner.identity(logical[name]),{'bytes':length,'sha256':sha})
            self.assertEqual(materials['logicalOrigins'][name],{
                'kind':'utf8-source-bundle','path':constructor.CONSTRUCTOR_BUNDLE,
                'ordinal':ordinal,'sourceType':kind})
        for name in owner.POST_INIT_SOURCE_PATHS:
            self.assertEqual(materials['logicalOrigins'][name],{'kind':'physical-file','path':name})
        raw=(owner.ROOT/constructor.CONSTRUCTOR_BUNDLE).read_bytes()
        # The real frozen whole-container pin stays in force: no test swaps a
        # pin to fabricate an accepted modified row or guessed C preimage.
        malformed=[raw[:-1],raw+b' ',b'\xff'+raw[1:],raw.replace(b'"type":"c"',b'"type":"h"',1)]
        model=json.loads(raw);model['sources'][1]=model['sources'][0]
        malformed.append((json.dumps(model,separators=(',',':'))+'\n').encode())
        for candidate in malformed:
            with self.subTest(bytes=len(candidate)),self.assertRaises(ValueError):
                constructor._constructor_decode(candidate)
        for name in ('../outside.c','unknown.c','factory-stream-mmio.c/child','x\\y.c'):
            with self.subTest(name=name),self.assertRaises(ValueError):constructor._constructor_source(name)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in owner.CONSTRUCTOR_MMIO_SOURCE_PATHS:
                q=root/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((owner.ROOT/name).read_bytes())
            self.assertEqual(owner.selected_sources(root,constructor_mmio=True),current)
            bundle=root/constructor.CONSTRUCTOR_BUNDLE;bundle.write_bytes(raw+b'\n')
            with self.assertRaises(ValueError):owner.selected_sources(root,constructor_mmio=True)

    def test_constructor_mmio_owner_keeps_only_twenty_two_changed_targets_and_stage_union(self):
        expected=('net/factory.o','drivers/base/dd.o','drivers/pci/bus.o','drivers/pci/pci-driver.o',
            'drivers/pci/pci-sysfs.o','drivers/pci/pci.o','drivers/pci/proc.o','drivers/pci/iomap.o',
            'drivers/virtio/virtio.o','drivers/virtio/virtio_pci_common.o',
            'drivers/virtio/virtio_pci_modern_dev.o','drivers/net/virtio_net.o','kernel/resource.o',
            'arch/x86/mm/pat/memtype.o','arch/x86/mm/pat/memtype_interval.o','arch/x86/mm/ioremap.o',
            'mm/vmalloc.o','lib/kobject.o','lib/idr.o','lib/radix-tree.o','fs/proc/generic.o','fs/proc/inode.o')
        self.assertEqual(owner.mode_targets(constructor_mmio=True),expected)
        for name in expected:
            self.assertEqual(owner.public_allowed('objects/'+name,constructor_mmio=True),owner.MAX_OBJECT)
        for old in ('classdir','classdir_kernfs','netdev_directory','netdev_layout','netdev_post_init'):
            with self.subTest(mode=old),self.assertRaises(ValueError):
                owner.mode_targets(constructor_mmio=True,**{old:True})
        with self.assertRaises(ValueError):owner.mode_targets(constructor_mmio=1)
        for name in ('layout.json','objects/net/socket.o','objects/drivers/virtio/virtio_ring.o',
            'objects/drivers/base/core.o','source-tree.tar','private/key'):
            self.assertIsNone(owner.public_allowed(name,constructor_mmio=True))
        for old in ('eighteen-objects','classdir-objects','classdir-kernfs-objects',
            'netdev-directory-objects','netdev-layout-objects','netdev-post-init-objects'):
            self.assertIsNone(owner.public_allowed('logs/00-'+old+'.stdout.txt',constructor_mmio=True))
        self.assertIsNotNone(owner.public_allowed('logs/00-baseline-fetch.stdout.txt',constructor_mmio=True))
        self.assertIsNotNone(owner.public_allowed('logs/31-constructor-mmio-objects.stderr.txt',constructor_mmio=True))
        self.assertIsNone(owner.public_allowed('logs/32-constructor-mmio-objects.stderr.txt',constructor_mmio=True))
        self.assertEqual([row[1] for row in owner.CONSTRUCTOR_MMIO_DERIVED],[398,407,410,414,417,427])
        with self.assertRaises(ValueError):owner.constructor_compose({},Path('not-a-kernel-tree'))
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            (output/'receipt.json').write_bytes(b'{"status":"failed","stage":"constructor-mmio-objects"}\n')
            self.assertEqual(set(owner.admit(output,constructor_mmio=True)['files']),{'receipt.json'})
            q=output/'objects/net/socket.o';q.parent.mkdir(parents=True);q.write_bytes(b'not-a-product')
            with self.assertRaises(ValueError):owner.admit(output,constructor_mmio=True)


class VpTransportMaterials(unittest.TestCase):
    """Source-reader controls only; no native producer/IRQ/fit qualification."""
    def test_vp_transport_container_binds_complete_typed_materials(self):
        import hashlib
        from tools import host_stream_kernel_vp_transport as stage
        raw=(stage.ROOT/stage.BUNDLE_PATH).read_bytes()
        values=stage.decode_materials(raw)
        self.assertEqual(set(values),set(stage.MATERIAL_PINS))
        self.assertEqual(len(values),3)
        for name,value in values.items():
            self.assertEqual((len(value),hashlib.sha256(value).hexdigest()),stage.MATERIAL_PINS[name])
        for altered in (raw[:-1],raw+b' ',raw.replace(b'IRQ',b'IrQ',1)):
            with self.assertRaises(ValueError):stage.decode_materials(altered)

    def test_vp_transport_forged_container_still_rejects_row_and_schema_forgery(self):
        import copy
        import hashlib
        from unittest.mock import patch
        from tools import host_stream_kernel_vp_transport as stage
        original=json.loads((stage.ROOT/stage.BUNDLE_PATH).read_bytes())
        def forged(value):
            raw=(json.dumps(value,separators=(',',':'))+'\n').encode()
            with patch.object(stage,'BUNDLE_PIN',(len(raw),hashlib.sha256(raw).hexdigest())):
                with self.assertRaises(ValueError):stage.decode_materials(raw)
        for key,value in (('path','include/net/unknown.h'),('bytes',True),
                          ('sha256','0'*64),('text','/* substituted body */\n')):
            value0=copy.deepcopy(original);value0['materials'][0][key]=value;forged(value0)
        value=copy.deepcopy(original);value['materials'][1]=value['materials'][0];forged(value)
        value=copy.deepcopy(original);value['schemaVersion']=True;forged(value)
        raw=b'{"schemaVersion":1,"schemaVersion":1,"materials":[]}'
        with patch.object(stage,'BUNDLE_PIN',(len(raw),hashlib.sha256(raw).hexdigest())):
            with self.assertRaises(ValueError):stage.decode_materials(raw)

    def test_vp_transport_refuses_incomplete_or_counterfeit_prior_source_map(self):
        from tools import host_stream_kernel_vp_transport as stage
        with self.assertRaises(ValueError):stage.transform({})
        fake={str(n):b'not-original-source' for n in range(427)}
        before=dict(fake)
        with self.assertRaises(ValueError):stage.transform(fake)
        self.assertEqual(fake,before)


class VpTransportOwner(unittest.TestCase):
    def test_vp_owner_cold_materials_exact_mode_and_public_stage(self):
        import subprocess
        import sys
        from tools import qualify_host_stream_kernel_stream_objects as owner
        self.assertIs(owner.mode_targets(vp_transport=True),owner.CONSTRUCTOR_MMIO_TARGETS)
        with self.assertRaises(ValueError):owner.mode_targets(constructor_mmio=True,vp_transport=True)
        with self.assertRaises(ValueError):owner.mode_targets(vp_transport=1)
        self.assertEqual(owner.public_allowed('objects/net/factory.o',vp_transport=True),owner.MAX_OBJECT)
        self.assertIsNotNone(owner.public_allowed('logs/00-vp-transport-objects.stdout.txt',vp_transport=True))
        self.assertIsNone(owner.public_allowed('logs/00-constructor-mmio-objects.stdout.txt',vp_transport=True))
        self.assertIsNone(owner.public_allowed('logs/00-vp-transport-objects.stdout.txt',constructor_mmio=True))
        self.assertIsNone(owner.public_allowed('objects/net/socket.o',vp_transport=True))
        with self.assertRaises(ValueError):owner.vp_compose({})
        # Cold direct-script-like import, without invoking hosted run/main or
        # a native projection/compiler. Earlier constructor import failure
        # must not recur in the new exact67/94 material path.
        code = """import json,runpy,sys
from pathlib import Path
path=Path(sys.argv[1]).resolve();root=path.parents[1]
assert all(Path(p).resolve()!=root for p in sys.path)
assert not any(n=='tools' or n.startswith('tools.') for n in sys.modules)
module=runpy.run_path(str(path),run_name='cold_vp_materials')
actual=module['vp_materials'](root)
assert actual['runtimeOrFundingQualified'] is False
print(json.dumps({'physical':len(actual['physicalInputs']),'logical':len(actual['logicalIdentities']),
    'priorPhysical':len(actual['prior65Physical']),'priorLogical':len(actual['prior90Logical']),
    'outputs':actual['projectionOutputCount']}))
"""
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,'-I','-B','-c',code,owner.__file__],
                cwd=directory,capture_output=True,check=False,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace')[:4096])
            self.assertEqual(json.loads(result.stdout),{'physical':67,'logical':94,
                'priorPhysical':65,'priorLogical':90,'outputs':430})
            output=Path(directory)/'public';output.mkdir()
            (output/'receipt.json').write_bytes(b'{"status":"failed"}\n')
            self.assertEqual(set(owner.admit(output,vp_transport=True)['files']),{'receipt.json'})


if __name__=='__main__':unittest.main()
