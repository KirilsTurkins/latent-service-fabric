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


class MsiContextSource(unittest.TestCase):
    """Only source-reader/inverse/cut/lifetime controls; no native execution."""
    _CLONE_EDITS = {'msi_setup': [['\tint ret, i;\n', '\tint ret, i;\n\tstruct lsf_stream_msi_plan plan = {};\n'], ['\tif (dev->msi.data)\n\t\treturn 0;', '    if (dev->msi.data) {\n        unsigned int role;\n        if (lsf_prepaid_stream_msi_resource_classify(dev, dev->msi.data, &role) != 1 ||\n            role != LSF_STREAM_MSI_CONTEXT) {\n            lsf_factory_stream_constructor_retain_unknown(); return -EOPNOTSUPP;\n        }\n        return 0;\n    }\n    ret = lsf_factory_stream_msi_prepare(dev, &plan);\n    if (ret != 1) return ret;'], ['\tmd = devres_alloc(msi_device_data_release, sizeof(*md), GFP_KERNEL);', '\tmd = lsf_prepaid_stream_msi_devres_allocate(dev, LSF_STREAM_MSI_CONTEXT, &plan, msi_device_data_release);'], ['\tif (!md)\n\t\treturn -ENOMEM;', '\tif (!md) {\n\t\tlsf_factory_stream_msi_discard(dev, &plan);\n\t\treturn -ENOMEM;\n\t}'], ['\tret = msi_sysfs_create_group(dev);', '\tret = lsf_prepaid_stream_msi_add_group(dev, &msi_irqs_group, &plan);'], ['\t\tdevres_free(md);\n\t\treturn ret;', '\t\tdevres_free(md);\n\t\tlsf_factory_stream_msi_discard(dev, &plan);\n\t\treturn ret;'], ['\tdevres_add(dev, md);\n\treturn 0;', '\tdevres_add(dev, md);\n\tlsf_factory_stream_msi_discard(dev, &plan);\n\treturn 0;']], 'devm_group': [['const struct attribute_group *grp)', 'const struct attribute_group *grp,\n    const struct lsf_stream_msi_plan *plan)'], ['\tint error;\n', '\tint error;\n\n\tif (!lsf_prepaid_stream_msi_group_known(grp) || lsf_factory_stream_msi_selected(dev) != 1)\n\t\treturn -EOPNOTSUPP;\n'], ['\tdevres = devres_alloc(devm_attr_group_remove,\n\t\t\t      sizeof(*devres), GFP_KERNEL);', '\tdevres = lsf_prepaid_stream_msi_devres_allocate(dev, LSF_STREAM_MSI_GROUP, plan, devm_attr_group_remove);']]}
    _RELEASE = 'static void release_nodes(struct device *dev, struct list_head *todo)\n{\n\tstruct devres *dr, *tmp;\n\n\t/* Release.  Note that both devres and devres_group are\n\t * handled as devres in the following loop.  This is safe.\n\t */\n\tlist_for_each_entry_safe_reverse(dr, tmp, todo, node.entry) {\n\t\tdevres_log(dev, &dr->node, "REL");\n\t\tdr->node.release(dev, dr->data);\n\t\tkfree(dr);\n\t}\n}\n'
    _DOMAINS = 'bool pci_setup_msi_device_domain(struct pci_dev *pdev)\n{\n\tif (WARN_ON_ONCE(pdev->msix_enabled))\n\t\treturn false;\n\n\tif (pci_match_device_domain(pdev, DOMAIN_BUS_PCI_DEVICE_MSI))\n\t\treturn true;\n\tif (pci_match_device_domain(pdev, DOMAIN_BUS_PCI_DEVICE_MSIX))\n\t\tmsi_remove_device_irq_domain(&pdev->dev, MSI_DEFAULT_DOMAIN);\n\n\treturn pci_create_device_domain(pdev, &pci_msi_template, 1);\n}\nbool pci_setup_msix_device_domain(struct pci_dev *pdev, unsigned int hwsize)\n{\n\tif (WARN_ON_ONCE(pdev->msi_enabled))\n\t\treturn false;\n\n\tif (pci_match_device_domain(pdev, DOMAIN_BUS_PCI_DEVICE_MSIX))\n\t\treturn true;\n\tif (pci_match_device_domain(pdev, DOMAIN_BUS_PCI_DEVICE_MSI))\n\t\tmsi_remove_device_irq_domain(&pdev->dev, MSI_DEFAULT_DOMAIN);\n\n\treturn pci_create_device_domain(pdev, &pci_msix_template, hwsize);\n}\n'


    def test_msi_complete_materials_and_inner_forgery_rejection(self):
        import copy
        import hashlib
        from unittest.mock import patch
        from tools import host_stream_kernel_msi_context as stage
        raw=(stage.ROOT/stage.BUNDLE_PATH).read_bytes()
        values=stage.decode_materials(raw)
        self.assertEqual(len(values),5)
        self.assertEqual(set(values),set(stage.MATERIAL_PINS))
        for name,value in values.items():
            self.assertEqual((len(value),hashlib.sha256(value).hexdigest()),stage.MATERIAL_PINS[name])
        for altered in (raw[:-1],raw+b' ',b'\xff'+raw[1:]):
            with self.subTest(length=len(altered)),self.assertRaises(ValueError):stage.decode_materials(altered)
        original=json.loads(raw)
        def reject(value):
            altered=(json.dumps(value,separators=(',',':'))+'\n').encode()
            with patch.object(stage,'BUNDLE_PIN',(len(altered),hashlib.sha256(altered).hexdigest())):
                with self.assertRaises(ValueError):stage.decode_materials(altered)
        for field,value in [('path','../outside.c'),('bytes',True),('sha256','0'*64),('text','/* counterfeit */\n')]:
            candidate=copy.deepcopy(original);candidate['materials'][0][field]=value;reject(candidate)
        candidate=copy.deepcopy(original);candidate['materials'][1]=candidate['materials'][0];reject(candidate)
        candidate=copy.deepcopy(original);candidate['schemaVersion']=True;reject(candidate)
        altered=b'{"schemaVersion":1,"schemaVersion":1,"materials":[]}'
        with patch.object(stage,'BUNDLE_PIN',(len(altered),hashlib.sha256(altered).hexdigest())):
            with self.assertRaises(ValueError):stage.decode_materials(altered)

    def test_msi_reader_bounds_file_identity_and_length_before_hash(self):
        import stat
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools import host_stream_kernel_msi_context as stage
        raw=(stage.ROOT/stage.BUNDLE_PATH).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/stage.BUNDLE_PATH;path.parent.mkdir(parents=True)
            path.write_bytes(raw)
            self.assertEqual(stage.materials(root),stage.decode_materials(raw))
            path.write_bytes(raw+b'x'*(1024*1024))
            decode=stage.decode_materials
            with patch.object(stage,'decode_materials',wraps=decode) as observed:
                with self.assertRaises(ValueError):stage.materials(root)
                self.assertEqual(len(observed.call_args.args[0]),stage.BUNDLE_PIN[0]+1)
            path.write_bytes(raw)
            fake=SimpleNamespace(st_mode=stat.S_IFLNK,st_file_attributes=0)
            with patch.object(Path,'lstat',return_value=fake),patch.object(stage.os,'open') as opening:
                with self.assertRaises(ValueError):stage.materials(root)
                opening.assert_not_called()
            real=path.stat()
            changed=SimpleNamespace(st_mode=real.st_mode,st_dev=real.st_dev,st_ino=real.st_ino+1,st_file_attributes=0)
            with patch.object(stage.os,'fstat',return_value=changed):
                with self.assertRaises(ValueError):stage.materials(root)
        with patch.object(stage.hashlib,'sha256',side_effect=AssertionError('must not hash wrong length')):
            self.assertFalse(stage._bound(raw[:-1],stage.BUNDLE_PIN))

    def test_msi_two_native_clone_inverses_and_payment_before_publication(self):
        import hashlib
        from tools import host_stream_kernel_msi_context as stage
        from tools.host_stream_kernel_device_security import function
        parts=stage.materials()
        specs=[('msi_setup','kernel/irq/lsf-stream-msi-context.c','int lsf_prepaid_stream_msi_setup_device_data(',
            'kernel/irq/msi.c::int msi_setup_device_data('),
            ('devm_group','drivers/base/lsf-stream-msi-group.c','int lsf_prepaid_stream_msi_add_group(',
            'drivers/base/core.c::int devm_device_add_group(')]
        def inverse(name,body,new,old):
            if name=='msi_setup':
                prefix='\n{\n#ifndef CONFIG_SYSFS\n    return -EOPNOTSUPP;\n#else\n'
                self.assertEqual(body.count(prefix),1);self.assertTrue(body.endswith('#endif\n}\n'))
                body=body.replace(prefix,'\n{\n',1)[:-len('#endif\n}\n')]+'}\n'
            for before,after in reversed(self._CLONE_EDITS[name]):
                self.assertEqual(body.count(after),1);body=body.replace(after,before)
            return body.replace(new,old,1).encode()
        for name,path,new,key in specs:
            original_name=key.split('::',1)[1]
            current=function(parts[path].decode(),new)
            restored=inverse(name,current,new,original_name)
            self.assertEqual((len(restored),hashlib.sha256(restored).hexdigest()),stage.BODIES[key])
            mutated=current.replace('\n{\n','\n{\n    /* unreviewed extra effect */\n',1)
            # The whole-original-function pin, beyond marker presence, rejects
            # an otherwise well-formed additional statement/body change.
            if name=='devm_group':
                changed=inverse(name,mutated,new,original_name)
                self.assertNotEqual((len(changed),hashlib.sha256(changed).hexdigest()),stage.BODIES[key])
        factory=function(parts['net/factory-stream-msi-context.c'].decode(),'int lsf_factory_stream_msi_prepare(')
        self.assertLess(factory.index('for (index = 0; index < 2u; ++index)'),factory.index('spin_lock_irqsave'))
        self.assertLess(factory.index('lsf_stream_constructor_allocate_locked'),factory.index('security_cache_location = plan->slot[0]'))
        allocate=function(parts['drivers/base/lsf-stream-msi-devres.c'].decode(),'void *lsf_prepaid_stream_msi_devres_allocate(')
        self.assertLess(allocate.index('lsf_factory_stream_msi_take'),allocate.index('memset(dr, 0, total)'))
        self.assertIn('offsetof(struct devres, data)',parts['drivers/base/lsf-stream-msi-devres.c'].decode())
        self.assertIn('check_dr_size(payload, &total)',parts['drivers/base/lsf-stream-msi-devres.c'].decode())

    def test_msi_actual_callback_then_retirement_and_domain_cut_inverses(self):
        import hashlib
        from tools import host_stream_kernel_msi_context as stage
        from tools.host_stream_kernel_constructor_failure import Editor
        from tools.host_stream_kernel_device_security import function
        # Only the NEW pure text-edit statements are exercised on complete
        # authenticated native FUNCTION fixtures. No earlier projection or
        # full-TU/native compilation or runtime claim is implied.
        for key,text in [('drivers/base/devres.c::static void release_nodes(',self._RELEASE),
                *[(f'drivers/pci/msi/irqdomain.c::{prefix}',function(self._DOMAINS,prefix)) for prefix in
                    ('bool pci_setup_msi_device_domain(','bool pci_setup_msix_device_domain(')]]:
            self.assertEqual((len(text.encode()),hashlib.sha256(text.encode()).hexdigest()),stage.BODIES[key])
        released=stage._release_nodes(self._RELEASE)
        def ordered(text):
            return text.index('lsf_prepaid_stream_msi_devres_validate') < text.index('dr->node.release(dev, dr->data)') < \
                text.index('lsf_prepaid_stream_msi_devres_retire') < text.index('kfree(dr)')
        self.assertTrue(ordered(released))
        swapped=released.replace('dr->node.release(dev, dr->data);','SWAP;',1).replace(
            '(void)lsf_prepaid_stream_msi_devres_retire(dev, dr, LSF_STREAM_MSI_AFTER_RELEASE);',
            'dr->node.release(dev, dr->data);',1).replace('SWAP;',
            '(void)lsf_prepaid_stream_msi_devres_retire(dev, dr, LSF_STREAM_MSI_AFTER_RELEASE);',1)
        self.assertFalse(ordered(swapped))
        domain=Editor(self._DOMAINS)
        for prefix in ('bool pci_setup_msi_device_domain(','bool pci_setup_msix_device_domain('):
            original=function(domain.text,prefix)
            domain.edit(original,stage._device_domain(original))
        domain.finish()
        for prefix in ('bool pci_setup_msi_device_domain(','bool pci_setup_msix_device_domain('):
            wrapped=function(domain.text,prefix);original=function(self._DOMAINS,prefix)
            self.assertLess(wrapped.index('lsf_factory_stream_msi_selected'),wrapped.index(original[original.index('{\n')+2:]))
            self.assertIn('return false;',wrapped[:wrapped.index(original[original.index('{\n')+2:])])
        with self.assertRaises(ValueError):stage.transform({}, {})
        fake={str(i):b'counterfeit' for i in range(430)};before=dict(fake)
        with self.assertRaises(ValueError):stage.transform(fake,{})
        self.assertEqual(fake,before)


class MsiContextOwner(unittest.TestCase):
    def test_msi_owner_has_exact_sources_targets_and_closed_union(self):
        from tools import qualify_host_stream_kernel_stream_objects as owner
        expected=('kernel/irq/msi.o','drivers/base/devres.o','drivers/base/core.o',
            'drivers/pci/msi/irqdomain.o','fs/sysfs/group.o','net/factory.o')
        self.assertEqual(owner.mode_targets(msi_context=True),expected)
        with self.assertRaises(ValueError):owner.mode_targets(msi_context=1)
        for mode in ('vp_transport','constructor_mmio','netdev_post_init','netdev_layout',
                'netdev_directory','classdir_kernfs','classdir'):
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                owner.mode_targets(msi_context=True,**{mode:True})
        before=owner.vp_materials(owner.ROOT);current=owner.msi_materials(owner.ROOT)
        self.assertEqual((len(current['physicalInputs']),len(current['logicalIdentities'])),(69,100))
        self.assertEqual(current['prior67Physical'],before['physicalInputs'])
        self.assertEqual(current['prior94Logical'],before['logicalIdentities'])
        self.assertEqual(current['projectionOutputCount'],439)
        self.assertFalse(current['runtimeOrFundingQualified'])
        for target in expected:self.assertEqual(owner.public_allowed('objects/'+target,msi_context=True),owner.MAX_OBJECT)
        for name in ('objects/drivers/net/virtio_net.o','objects/drivers/virtio/virtio_ring.o',
                'layout.json','source-tree.tar','logs/00-vp-transport-objects.stdout.txt'):
            self.assertIsNone(owner.public_allowed(name,msi_context=True))
        self.assertIsNotNone(owner.public_allowed('logs/00-msi-context-objects.stderr.txt',msi_context=True))
        self.assertIsNone(owner.public_allowed('logs/00-msi-context-objects.stderr.txt',vp_transport=True))
        with self.assertRaises(ValueError):owner.msi_compose({},Path('not-a-kernel-tree'))
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            (output/'receipt.json').write_bytes(b'{"status":"failed"}\n')
            self.assertEqual(set(owner.admit(output,msi_context=True)['files']),{'receipt.json'})
            path=output/'objects/net/socket.o';path.parent.mkdir(parents=True);path.write_bytes(b'not-a-product')
            with self.assertRaises(ValueError):owner.admit(output,msi_context=True)


class Q35MsiSource(unittest.TestCase):
    _TOKEN_NATIVE = 'void irq_domain_update_bus_token(struct irq_domain *domain,\n\t\t\t\t enum irq_domain_bus_token bus_token)\n{\n\tchar *name;\n\n\tif (domain->bus_token == bus_token)\n\t\treturn;\n\n\tmutex_lock(&irq_domain_mutex);\n\n\tdomain->bus_token = bus_token;\n\n\tname = kasprintf(GFP_KERNEL, "%s-%d", domain->name, bus_token);\n\tif (!name) {\n\t\tmutex_unlock(&irq_domain_mutex);\n\t\treturn;\n\t}\n\n\tdebugfs_remove_domain_dir(domain);\n\n\tif (domain->flags & IRQ_DOMAIN_NAME_ALLOCATED)\n\t\tkfree(domain->name);\n\telse\n\t\tdomain->flags |= IRQ_DOMAIN_NAME_ALLOCATED;\n\n\tdomain->name = name;\n\tdebugfs_add_domain_dir(domain);\n\n\tmutex_unlock(&irq_domain_mutex);\n}\n'
    _TABLE_EDITS = [['static int msix_capability_init(', 'static int lsf_q35_msix_capability_init('], ['\tint ret, tsize;\n\tu16 control;\n', '\tint ret, tsize;\n\tu16 control;\n\tvoid __iomem *paid;\n\tunsigned int prepaid_tsize;\n\n\tif (entries || affd || (nvec != 2 && nvec != 3) || dev->msix_base ||\n\t    !lsf_q35_x86_parent_known(dev_get_msi_domain(&dev->dev)) ||\n\t    lsf_q35_msi_current(&dev->dev) != 1) return -EOPNOTSUPP;\n\tpci_read_config_word(dev, dev->msix_cap + PCI_MSIX_FLAGS, &control);\n\tprepaid_tsize = msix_table_size(control);\n\tpaid = lsf_q35_msix_map(dev, prepaid_tsize);\n\tif (!paid) return -ENOMEM;\n'], ['\tdev->msix_base = msix_map_region(dev, tsize);', '\tif (tsize != prepaid_tsize) { ret = -EOPNOTSUPP; goto out_disable; }\n\tdev->msix_base = paid;\n\tpaid = NULL;'], ['ret = msix_setup_interrupts(dev, entries, nvec, affd);', 'ret = lsf_q35_msix_interrupts_closed(dev, entries, nvec, affd);'], ['\tpci_msix_clear_and_set_ctrl(dev, PCI_MSIX_FLAGS_MASKALL | PCI_MSIX_FLAGS_ENABLE, 0);\n', '\tpci_msix_clear_and_set_ctrl(dev, PCI_MSIX_FLAGS_MASKALL | PCI_MSIX_FLAGS_ENABLE, 0);\n\tif (paid) iounmap(paid);\n']]

    def test_q35_eight_materials_exact_bounded_and_length_before_hash(self):
        import hashlib
        from unittest.mock import patch
        from tools import qualify_host_stream_kernel_stream_objects as owner
        stage=owner.q35_stage(owner.ROOT)[0]
        parts=stage.materials()
        self.assertEqual(len(parts),8)
        for name,raw in parts.items():
            self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),stage.MATERIAL_PINS[name])
        seen=[]
        def read(path,maximum):
            name=next(n for n,p in stage.MATERIAL_PATHS.items() if path==stage.ROOT/p)
            seen.append((name,maximum));return parts[name]
        with patch.object(stage,'read_file',side_effect=read):self.assertEqual(stage.materials(),parts)
        self.assertEqual(dict(seen),{n:p[0] for n,p in stage.MATERIAL_PINS.items()})
        with patch.object(stage,'read_file',return_value=b'x'):
            with self.assertRaises(ValueError):stage.materials()
        with patch.object(stage.hashlib,'sha256',side_effect=AssertionError('wrong-length hash')):
            self.assertFalse(stage._bound(b'x',(2,'0'*64)))
        with self.assertRaises(ValueError):stage.transform({}, {})

    def test_q35_loader_uses_captured_bytes_and_refuses_alternate_sources(self):
        import _io
        import importlib.util
        from unittest.mock import patch
        from tools import qualify_host_stream_kernel_stream_objects as owner
        path=(owner.ROOT/owner.Q35_MODULE).resolve()
        expected=owner.read(path,owner.Q35_PINS[owner.Q35_MODULE][0])
        factory=importlib.util.spec_from_file_location;open_code=_io.open_code
        opened=Path.open;loaders=[]
        def deny_code(name,*args,**kwargs):
            self.assertNotIn(str(name),(str(path),str(path)+'.pyc'))
            return open_code(name,*args,**kwargs)
        def deny_path(value,*args,**kwargs):
            self.assertNotEqual(value.resolve(),path)
            return opened(value,*args,**kwargs)
        def inspect_spec(name,location,*,loader):
            self.assertEqual((name,str(location)),('_lsf_q35_projector',str(path)))
            self.assertEqual(loader.get_data(str(path)),expected)
            with self.assertRaises(ValueError):loader.get_filename('_foreign_q35')
            for alternate in (str(path)+'.pyc',str(path.parent/'foreign.py')):
                with self.subTest(path=alternate),self.assertRaises(ValueError):loader.get_data(alternate)
            with self.assertRaises(OSError):loader.path_stats(str(path))
            execute=loader.exec_module
            def captured_only(module):
                # No source reopen or bytecode write is allowed AFTER capture.
                with patch.object(_io,'open_code',side_effect=deny_code), \
                        patch.object(Path,'open',deny_path), \
                        patch.object(loader,'set_data',side_effect=AssertionError('bytecode write')):
                    execute(module)
            loader.exec_module=captured_only;loaders.append(loader)
            return factory(name,location,loader=loader)
        with patch.object(importlib.util,'spec_from_file_location',side_effect=inspect_spec):
            stage,physical,_=owner.q35_stage(owner.ROOT)
        self.assertEqual(len(loaders),1)
        self.assertEqual(physical[owner.Q35_MODULE],owner.identity(expected))
        self.assertEqual((stage.ROOT,Path(stage.__file__).resolve()),(owner.ROOT.resolve(),path))

    def test_q35_whole_native_wrapper_inverse_and_wrong_input_refusal(self):
        import hashlib
        from tools import qualify_host_stream_kernel_stream_objects as owner
        stage=owner.q35_stage(owner.ROOT)[0]
        original=self._TOKEN_NATIVE
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),'251e44d392defeb2ec285a0994b6d015ff5ec7424aec09e6e43df03d3eafb7de')
        branch='\tif (lsf_q35_domain_links_known(domain)) return;\n'
        wrapped=stage._wrap(original,branch)
        prefix='\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+branch+'#endif\n'
        self.assertEqual(wrapped.count(prefix),1)
        self.assertEqual(wrapped.replace(prefix,'\n',1)[:-2],original)
        wrong={n:b'counterfeit' for n in stage.PREIMAGES}
        before=dict(wrong)
        with self.assertRaises(ValueError):stage.edit_inputs(wrong,{})
        self.assertEqual(wrong,before)

    def test_q35_native_msix_clone_inverse_and_admission_before_enable(self):
        import hashlib
        from tools import qualify_host_stream_kernel_stream_objects as owner
        stage=owner.q35_stage(owner.ROOT)[0]
        from tools.host_stream_kernel_device_security import function
        parts=stage.materials();text=parts['drivers/pci/msi/lsf-stream-q35-table.c'].decode()
        body=function(text,'static int lsf_q35_msix_capability_init(')
        def inverse(value):
            for old,new in reversed(self._TABLE_EDITS):
                self.assertEqual(value.count(new),1);value=value.replace(new,old)
            return value
        self.assertEqual(hashlib.sha256(inverse(body).encode()).hexdigest(),'9160b44d022e610c29d085904f3a8143ff72dc45b3818d40e169cd57589f9674')
        mutated=body.replace('\n{\n','\n{\n    /* unreviewed */\n',1)
        self.assertNotEqual(hashlib.sha256(inverse(mutated).encode()).hexdigest(),'9160b44d022e610c29d085904f3a8143ff72dc45b3818d40e169cd57589f9674')
        self.assertLess(body.index('lsf_q35_msix_map('),body.index('pci_msix_clear_and_set_ctrl('))
        cut=function(text,'static int lsf_q35_msix_interrupts_closed(')
        self.assertLess(cut.index('lsf_q35_msi_empty_locked'),cut.index('pci_free_msi_irqs'))
        self.assertIn('return -EOPNOTSUPP;',cut)
        for forbidden in ('request_irq(', 'msi_setup_interrupts(', 'irq_domain_alloc_irqs('):
            self.assertNotIn(forbidden,cut)

    def test_q35_typed_full_payment_and_physical_cleanup_cuts(self):
        from tools import qualify_host_stream_kernel_stream_objects as owner
        stage=owner.q35_stage(owner.ROOT)[0]
        from tools.host_stream_kernel_device_security import function
        parts=stage.materials()
        source=parts['kernel/irq/lsf-stream-q35-msi.c'].decode()
        birth=function(source,'bool lsf_q35_msi_create(')
        self.assertLess(birth.index('lsf_q35_msi_prepare('),birth.index('lsf_q35_msi_take('))
        self.assertLess(birth.index('lsf_q35_msi_take('),birth.index('__msi_create_irq_domain('))
        self.assertIn('char name[sizeof(template->name)]',birth)
        self.assertIn('sizeof(template->name) + 12u',birth)
        domain=parts['kernel/irq/lsf-stream-q35-domain.c'].decode()
        self.assertIn('sizeof(struct irqchip_fwid)',domain)
        self.assertIn('struct_size((struct irq_domain *)NULL, revmap, 0)',domain)
        self.assertIn('token_bytes > sizeof(((struct msi_domain_template *)0)->name) + 12u',domain)
        factory=parts['net/factory-stream-q35-msi.c'].decode()
        sibling=function(factory,'void *lsf_q35_msi_sibling(')
        self.assertLess(sibling.index('if (found != 1'),sibling.index('lsf_device_publish('))
        retirement=function(factory,'int lsf_q35_msi_retire(')
        self.assertIn('child->deferred == LSF_PREPAID_PUBLISHED',retirement)
        self.assertLess(retirement.index('lsf_device_queue('),retirement.index('lsf_device_finish('))
        self.assertNotIn('factory.pool.cursor =',factory)
        self.assertFalse(stage.PROFILE['runtimeQualified'])
        self.assertFalse(stage.PROFILE['sharedControllerFundingQualified'])


class Q35MsiOwner(unittest.TestCase):
    def test_q35_exact_physical_logical_targets_and_closed_public_union(self):
        from tools import qualify_host_stream_kernel_stream_objects as owner
        targets=('kernel/irq/msi.o','kernel/irq/irqdomain.o','drivers/pci/msi/msi.o',
            'drivers/pci/msi/irqdomain.o','arch/x86/kernel/apic/msi.o',
            'arch/x86/kernel/apic/vector.o','net/factory.o')
        self.assertEqual(owner.mode_targets(q35=True),targets)
        with self.assertRaises(ValueError):owner.mode_targets(q35=1)
        for old in ('msi_context','vp_transport','constructor_mmio','netdev_post_init',
                'netdev_layout','netdev_directory','classdir_kernfs','classdir'):
            with self.subTest(mode=old),self.assertRaises(ValueError):owner.mode_targets(q35=True,**{old:True})
        base=owner.msi_materials(owner.ROOT);current=owner.q35_materials(owner.ROOT)
        self.assertEqual((len(current['physicalInputs']),len(current['logicalIdentities'])),(78,109))
        self.assertEqual(current['prior69Physical'],base['physicalInputs'])
        self.assertEqual(current['prior100Logical'],base['logicalIdentities'])
        self.assertEqual(current['projectionOutputCount'],451)
        self.assertFalse(current['runtimeOrFundingQualified'])
        for t in targets:self.assertEqual(owner.public_allowed('objects/'+t,q35=True),owner.MAX_OBJECT)
        for name in ('objects/drivers/base/core.o','layout.json','source-tree.tar','logs/00-msi-context-objects.stdout.txt'):
            self.assertIsNone(owner.public_allowed(name,q35=True))
        self.assertEqual(owner.public_allowed('logs/00-q35-msi-domain-objects.stderr.txt',q35=True),4*1024**2)
        self.assertIsNone(owner.public_allowed('logs/00-q35-msi-domain-objects.stderr.txt',msi_context=True))
        with self.assertRaises(ValueError):owner.q35_compose({},Path('not-a-kernel-tree'))
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);(out/'receipt.json').write_bytes(b'{"status":"failed"}\n')
            self.assertEqual(set(owner.admit(out,q35=True)['files']),{'receipt.json'})
            bad=out/'objects/net/socket.o';bad.parent.mkdir(parents=True);bad.write_bytes(b'not-a-product')
            with self.assertRaises(ValueError):owner.admit(out,q35=True)


class MsiDescriptorSource(unittest.TestCase):
    @staticmethod
    def _raw(name):
        return (owner.ROOT/'research/standard-outbound/linux-6.12-lineage/msi-descriptor'/name).read_text(encoding='utf-8')

    def test_captured_inventory_and_native_preload_refusal(self):
        import importlib.util
        base=owner.q35_materials(owner.ROOT)
        current=owner.msi_descriptor_materials(owner.ROOT)
        self.assertEqual((len(current['physicalInputs']),len(current['logicalIdentities'])),(83,114))
        self.assertEqual(current['prior78Physical'],base['physicalInputs'])
        self.assertEqual(current['prior109Logical'],base['logicalIdentities'])
        self.assertEqual(current['projectionOutputCount'],456)
        self.assertEqual(set(owner.MSI_DESCRIPTOR_NATIVE_PINS),{'lib/xarray.c','include/linux/xarray.h'})
        self.assertFalse(set(owner.MSI_DESCRIPTOR_NATIVE_PINS)&set(current['physicalInputs']))
        bad={n:b'x' for n in owner.MSI_DESCRIPTOR_NATIVE_PINS}
        with patch.object(importlib.util,'spec_from_file_location',side_effect=AssertionError('load-before-auth')), \
                patch.object(owner,'identity',side_effect=AssertionError('wrong-length-hash')):
            with self.assertRaises(ValueError):owner.msi_descriptor_stage(owner.ROOT,bad)
        with patch.object(owner,'q35_materials',return_value=base), \
                patch.object(owner,'read',return_value=b'x'), \
                patch.object(owner,'identity',side_effect=AssertionError('wrong-length-hash')):
            with self.assertRaises(ValueError):owner.msi_descriptor_capture(owner.ROOT)

    def test_native_node_clones_have_exact_whole_body_inverses(self):
        import hashlib
        from tools.host_stream_kernel_device_security import function
        raw=self._raw('lsf-stream-msi-xarray.c')
        expected={'static void *xas_alloc(': '20a04052b6accaf80b577380a94ff103cb87db6c5f22561e7e554642b635707f', 'bool xas_nomem(': '9fe1db9d57e36d6cb3db7813b9262731cc43be1101e589b154c79e340c93d030', 'static bool __xas_nomem(': 'c938c3902230d47b43cb748ee92bad346e0a4c8689b847cad93a68938a41ac4f', 'void xas_destroy(': '20d19541915b9364c2abab776fb9c716b20ba28825b9eb7ac1621b9171639f12'}
        replacements={
            'static void *xas_alloc(':('static struct xa_node *lsf_msi_xas_alloc(',[
                ('\tif (parent || shift || xas->xa_index > 2u || xas->xa_shift || xas->xa_sibs) {\n'
                 '\t\tlsf_factory_stream_constructor_retain_unknown();\n'
                 '\t\txas_set_err(xas, -EOPNOTSUPP); return NULL;\n\t}\n\n',''),
                ('\t\tif (!lsf_msi_store_node_for(node, xas->xa) ||\n'
                 '\t\t    node->array != (struct xarray *)xas) {\n'
                 '\t\t\tlsf_factory_stream_constructor_retain_unknown();\n'
                 '\t\t\txas_set_err(xas, -EOPNOTSUPP); return NULL;\n\t\t}\n','')]),
            'bool xas_nomem(':('static bool lsf_msi_xas_nomem(',[]),
            'static bool __xas_nomem(':('static bool lsf_msi_internal_xas_nomem(',[]),
            'void xas_destroy(':('static void lsf_msi_xas_destroy(',[
                ('\t\tif (!lsf_msi_store_node_for(node, xas->xa) ||\n'
                 '\t\t    node->array != (struct xarray *)xas || rcu_access_pointer(node->parent)) {\n'
                 '\t\t\tlsf_factory_stream_constructor_retain_unknown(); return;\n\t\t}\n',''),
                ('\t\t/* The last same-operation check has completed. Do not retain a\n'
                 '\t\t * dead xa_state stack address in the original bank after cleanup. */\n'
                 '\t\tnode->array = NULL;\n','')]),
        }
        for original,(prefix,edits) in replacements.items():
            with self.subTest(function=original):
                current=function(raw,prefix)
                for before,after in edits:
                    self.assertEqual(current.count(before),1)
                    current=current.replace(before,after,1)
                current=current.replace(prefix,original,1).replace('lsf_msi_xa_preallocate(xas, gfp)',
                    'kmem_cache_alloc_lru(radix_tree_node_cachep, xas->xa_lru, gfp)')
                self.assertEqual(hashlib.sha256(current.encode()).hexdigest(),expected[original])

    def test_same_operation_marker_and_current_attempt_cleanup(self):
        from tools.host_stream_kernel_device_security import function
        nodes=self._raw('lsf-stream-msi-xarray.c')
        factory=self._raw('factory-stream-msi-descriptor.c')
        allocate=function(nodes,'static struct xa_node *lsf_msi_xa_preallocate(')
        self.assertIn('node->array = (struct xarray *)xas;',allocate)
        self.assertLess(allocate.index('lsf_msi_store_node_take'),allocate.index('INIT_LIST_HEAD'))
        consume=function(nodes,'static struct xa_node *lsf_msi_xas_alloc(')
        self.assertLess(consume.index('node->array != (struct xarray *)xas'),consume.index('xas->xa_alloc = NULL'))
        self.assertLess(consume.index('xas->xa_alloc = NULL'),consume.index('node->array = xas->xa'))
        destroy=function(nodes,'static void lsf_msi_xas_destroy(')
        self.assertLess(destroy.index('node->array != (struct xarray *)xas'),destroy.index('node->array = NULL'))
        self.assertLess(destroy.index('node->array = NULL'),destroy.index('radix_tree_node_rcu_free'))
        current=function(factory,'int lsf_msi_store_node_for(')
        for guard in ('first->phase == LSF_PREPAID_LIVE','latest == first',
                'latest->generation == record->security_cache_identity',
                'first->security_cache_identity == context.generation'):
            self.assertIn(guard,current)
        late=function(factory,'static struct lsf_prepaid_view *lsf_msi_store_record_locked(')
        self.assertIn('first->phase != LSF_PREPAID_RETURNED',late)
        self.assertNotIn('latest',late);self.assertNotIn('node->array',late)
        callback=function(factory,'int lsf_msi_store_radix_selected(')
        for kind in ('LSF_DEVICE_CLEANUP_PID_RADIX','LSF_DEVICE_IDR_NODE',
                'LSF_DEVICE_STREAM_CLASSDIR_IDR','LSF_DEVICE_STREAM_NETDEV_DIRECTORY_IDR'):
            self.assertIn(kind,callback)
        self.assertIn('factory.pool.poisoned = 1',callback)

    def test_aggregate_admission_and_real_irq_cut(self):
        from tools.host_stream_kernel_device_security import function
        factory=self._raw('factory-stream-msi-descriptor.c')
        descriptor=self._raw('lsf-stream-msi-descriptor.c')
        prepare=function(factory,'int lsf_msi_store_prepare(')
        self.assertIn('attempts >= 3u',prepare)
        self.assertIn('nvec != (attempts == 2u ? 2u : 3u)',prepare)
        self.assertLess(prepare.index('lsf_stream_constructor_allocate_locked'),prepare.index('plan->nvec = nvec'))
        self.assertNotIn('lsf_device_publish',prepare)
        take=function(factory,'void *lsf_msi_store_take(')
        for guard in ('lsf_stream_bind_current_locked','found->deferred != LSF_PREPAID_PRIVATE',
                'record->cache_bucket != pci.slot','record->cache_anchor != pci.generation'):
            self.assertIn(guard,take)
        alloc=function(descriptor,'struct msi_desc *lsf_msi_descriptor_allocate(')
        for guard in ('init->affinity','init->nvec_used != 1u','init->msi_index >= 3u',
                'init->pci.mask_base != to_pci_dev(dev)->msix_base'):
            self.assertIn(guard,alloc)
        self.assertNotIn('kzalloc(',alloc);self.assertNotIn('kmemdup_array(',alloc)
        cut=function(descriptor,'int lsf_msi_descriptor_setup(')
        self.assertIn('return -EOPNOTSUPP;',cut)
        for forbidden in ('msi_domain_alloc_irqs_all_locked(', 'irq_domain_alloc_descs(',
                'request_irq(', 'alloc_percpu('):self.assertNotIn(forbidden,cut)
        projection=self._raw('projector.py')
        self.assertIn('return lsf_msi_descriptor_setup(dev, nvec, type);',projection)
        self.assertIn('lsf_factory_selected_consumer',projection)


class MsiDescriptorOwner(unittest.TestCase):
    def test_closed_targets_materials_and_public_union(self):
        targets=('kernel/irq/msi.o','drivers/pci/msi/irqdomain.o','drivers/pci/msi/msi.o',
            'lib/xarray.o','lib/radix-tree.o','net/factory.o')
        self.assertEqual(owner.mode_targets(msi_descriptor=True),targets)
        with self.assertRaises(ValueError):owner.mode_targets(msi_descriptor=1)
        for old in ('classdir','classdir_kernfs','netdev_directory','netdev_layout',
                'netdev_post_init','constructor_mmio','vp_transport','msi_context','q35'):
            with self.subTest(mode=old),self.assertRaises(ValueError):
                owner.mode_targets(msi_descriptor=True,**{old:True})
        self.assertEqual((owner.MAX_COMMANDS,owner.MAX_OBJECT,owner.MAX_PUBLIC),(32,16*1024**2,128*1024**2))
        for t in targets:self.assertEqual(owner.public_allowed('objects/'+t,msi_descriptor=True),owner.MAX_OBJECT)
        self.assertIsNone(owner.public_allowed('objects/arch/x86/kernel/apic/vector.o',msi_descriptor=True))
        self.assertIsNone(owner.public_allowed('objects/lib/xarray.o',q35=True))
        self.assertEqual(owner.public_allowed('logs/00-msi-descriptor-objects.stdout.txt',msi_descriptor=True),4*1024**2)
        self.assertIsNone(owner.public_allowed('logs/00-q35-msi-domain-objects.stdout.txt',msi_descriptor=True))
        with self.assertRaises(ValueError):owner.msi_descriptor_compose({},Path('not-a-kernel-tree'),Path('not-created'))
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);(out/'receipt.json').write_bytes(b'{"status":"failed"}\n')
            self.assertEqual(set(owner.admit(out,msi_descriptor=True)['files']),{'receipt.json'})
            bad=out/'objects/net/socket.o';bad.parent.mkdir(parents=True);bad.write_bytes(b'not-an-object')
            with self.assertRaises(ValueError):owner.admit(out,msi_descriptor=True)


class ZNodeBootstrapObjectOwner(unittest.TestCase):
    def test_one_target_and_complete_capture_do_not_open_historical_modes(self):
        self.assertEqual(owner.mode_targets(node_bootstrap=True), ('net/factory.o',))
        for other in ('classdir', 'msi_context', 'q35', 'msi_descriptor'):
            with self.assertRaises(ValueError):
                owner.mode_targets(node_bootstrap=True, **{other: True})
        with self.assertRaises(ValueError):
            owner.mode_targets(node_bootstrap=1)
        self.assertEqual(len(owner.NODE_PINS), 2)
        self.assertEqual(owner.NODE_PHYSICAL_BYTES, 1008506)
        self.assertEqual(owner.NODE_MODULE, 'research/standard-outbound/linux-6.12-lineage/node-bootstrap/projector.py')
        self.assertEqual(owner.public_allowed('objects/net/factory.o', node_bootstrap=True), owner.MAX_OBJECT)
        for wrong in ('objects/net/socket.o', 'objects/lib/xarray.o', 'layout.json', 'logs/00-msi-descriptor-objects.stdout.txt'):
            self.assertIsNone(owner.public_allowed(wrong, node_bootstrap=True))
        self.assertEqual(owner.public_allowed('logs/00-node-bootstrap-objects.stdout.txt', node_bootstrap=True), 4*1024**2)
        self.assertIsNone(owner.public_allowed('logs/32-node-bootstrap-objects.stdout.txt', node_bootstrap=True))
        self.assertEqual(len(owner.NODE_STAGES), len(owner.MSI_DESCRIPTOR_STAGES))
        self.assertEqual(owner.NODE_STAGES.count('node-bootstrap-objects'), 1)
        self.assertNotIn('msi-descriptor-objects', owner.NODE_STAGES)


class ZNodeIrqGeometryOwner(unittest.TestCase):
    def test_complete_capture_and_closed_six_object_scope(self):
        source=owner.geometry_materials(owner.ROOT)
        self.assertEqual((len(source['physicalInputs']),len(source['logicalIdentities'])),(88,119))
        self.assertEqual((len(source['prior85Physical']),len(source['prior116Logical'])),(85,116))
        self.assertEqual(sum(r['bytes'] for r in source['physicalInputs'].values()),1018112)
        self.assertEqual(owner.mode_targets(node_geometry=True),owner.GEOMETRY_TARGETS)
        self.assertEqual(len(owner.GEOMETRY_TARGETS),6)
        for old in ('node_bootstrap','msi_descriptor','q35','msi_context','classdir'):
            with self.assertRaises(ValueError):owner.mode_targets(node_geometry=True,**{old:True})
        with self.assertRaises(ValueError):owner.mode_targets(node_geometry=1)
        for target in owner.GEOMETRY_TARGETS:
            self.assertEqual(owner.public_allowed('objects/'+target,node_geometry=True),owner.MAX_OBJECT)
        self.assertIsNone(owner.public_allowed('objects/net/factory.o',node_geometry=True))
        self.assertIsNone(owner.public_allowed('logs/00-node-bootstrap-objects.stdout.txt',node_geometry=True))
        self.assertEqual(owner.public_allowed('logs/00-node-irq-geometry-objects.stdout.txt',node_geometry=True),4*1024**2)
        self.assertEqual(owner.mode_targets(node_bootstrap=True),('net/factory.o',))

    @staticmethod
    def _elf(role=1,flags=2,relocation=False):
        import struct
        fields=owner.GEOMETRY_FIELDS[role]
        values=[8]*len(fields)
        for i,name in enumerate(fields):
            if name.endswith('.enabled'):values[i]=0
        data=struct.pack('<28Q',0x314f45474e46534c,1,role,len(fields),*values,*([0]*(24-len(fields))))
        strings=b'\0.shstrtab\0.lsf_node_geometry\0'
        raw=bytearray(64);raw[:7]=b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HHI',raw,16,1,62,1)
        raw.extend(strings);data_offset=len(raw);raw.extend(data)
        table=len(raw);rows=[(0,0,0,0,0,0,0,0,0,0),
            (1,3,0,0,64,len(strings),0,0,1,0),
            (11,1,flags,0,data_offset,len(data),0,0,8,0)]
        if relocation:rows.append((0,4,0,0,data_offset,24,0,2,8,24))
        for row in rows:raw.extend(struct.pack('<IIQQQQIIQQ',*row))
        struct.pack_into('<Q',raw,40,table);struct.pack_into('<HHH',raw,58,64,len(rows),1)
        return bytes(raw)

    def test_passive_geometry_rejects_wrong_role_write_relocations_and_truncation(self):
        good=self._elf()
        decoded=owner.geometry_decode(good,1)
        self.assertFalse(decoded['objectExecuted']);self.assertFalse(decoded['fundingOrFitQualified'])
        for bad,role in [(good,2),(good[:-1],1),(self._elf(flags=3),1),
                (self._elf(flags=6),1),(self._elf(relocation=True),1),(b'not ELF',1)]:
            with self.subTest(role=role,length=len(bad)),self.assertRaises(ValueError):
                owner.geometry_decode(bad,role)
        for role in owner.GEOMETRY_FIELDS:self.assertEqual(owner.geometry_decode(self._elf(role),role)['role'],role)

    def test_native_operands_preserve_unfunded_dynamic_and_shared_boundaries(self):
        root=owner.ROOT/'research/standard-outbound/linux-6.12-lineage/node-irq-geometry'
        body=(root/'geometry.c').read_text()
        self.assertIn('num_possible_cpus() != 1 || !cpu_possible(0) || nr_cpu_ids != 1',body)
        self.assertIn('pcpu_chunk_struct_size',body);self.assertIn('need_pcpuobj_ext()',body)
        self.assertIn('pcpu_group_sizes[group]',body);self.assertIn('check_mul_overflow',body)
        self.assertIn('asynchronous balance work',body)
        for birth in ('kmalloc(', 'kzalloc(', 'alloc_pages(', 'alloc_percpu(', 'request_irq(', 'NodeFunding'):
            self.assertNotIn(birth,body)
        self.assertEqual(len(owner.GEOMETRY_NATIVE_PINS),6)
        self.assertEqual(set(owner.GEOMETRY_NATIVE_PINS),{'kernel/irq/matrix.c','lib/maple_tree.c',
            'mm/percpu.c','mm/percpu-vm.c','mm/percpu-internal.h','kernel/irq/irqdesc.c'})


class ZNodeNativeCapacityOwner(unittest.TestCase):
    def _review(self, root):
        prefix = Path(owner.CAPACITY_MODULE).parent
        research = {}
        for name, raw in [('projector.py',b'# captured only\n'),('native.c',b'int captured;\n')]:
            path = root/prefix/name; path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            research[(prefix/name).as_posix()] = owner.identity(raw)
        primary = {n:owner.identity(b'int original;\n') for n in
            ('fs/proc/generic.c','fs/proc/inode.c','fs/proc/internal.h',
             'drivers/virtio/virtio_pci_common.c')}
        return {'research':research,'primary':primary,'projectorPrimary':{},'outputCount':464}

    def test_closed_route_rejects_mixed_modes_and_unrelated_products(self):
        old = (False,)*12
        self.assertEqual(owner.capacity_targets(False,*old),owner.mode_targets())
        self.assertEqual(owner.capacity_targets(True,*old),owner.CAPACITY_TARGETS)
        self.assertEqual(len(owner.CAPACITY_TARGETS),18)
        with self.assertRaises(ValueError): owner.capacity_targets(True,True,*old[1:])
        with self.assertRaises(ValueError): owner.capacity_targets(1,*old)
        for name in owner.CAPACITY_TARGETS:
            self.assertEqual(owner.public_allowed('objects/'+name,node_capacity=True),owner.MAX_OBJECT)
        for name in ('objects/net/socket.o','layout.json','logs/00-node-irq-geometry-objects.stdout.txt',
                     'logs/32-node-capacity-objects.stdout.txt'):
            self.assertIsNone(owner.public_allowed(name,node_capacity=True))
        self.assertEqual(owner.public_allowed('logs/00-node-capacity-objects.stderr.txt',
            node_capacity=True),4*1024**2)

    def test_capture_refuses_unfrozen_extra_drift_and_overflow_before_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); review=self._review(root)
            with patch.object(owner,'CAPACITY_REVIEW',None):
                with self.assertRaises(ValueError): owner.capacity_capture(root)
            with patch.object(owner,'CAPACITY_REVIEW',review),patch.object(owner,'geometry_capture',return_value=({}, {}, {})):
                rows,raw=owner.capacity_capture(root)
                self.assertEqual(rows,{n:owner.identity(b) for n,b in raw.items()})
                extra=root/Path(owner.CAPACITY_MODULE).parent/'unexpected.c';extra.write_bytes(b'x')
                with self.assertRaises(ValueError): owner.capacity_capture(root)
                extra.unlink()
                path=root/owner.CAPACITY_MODULE;path.write_bytes(b'drift')
                with self.assertRaises(ValueError): owner.capacity_capture(root)
                path.write_bytes(raw[owner.CAPACITY_MODULE])
                with patch.object(owner,'MAX_SOURCE',1):
                    with self.assertRaises(ValueError): owner.capacity_capture(root)

    def test_native_capture_retains_every_original_body_and_refuses_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);review=self._review(root)
            tree=root/'linux';tree.mkdir()
            for name in review['primary']:
                path=tree/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'int original;\n')
            with patch.object(owner,'CAPACITY_REVIEW',review):
                result=owner.capacity_native_capture(tree,root/'captured')
                self.assertEqual(set(result),set(review['primary']))
                for name,raw in result.items():
                    self.assertEqual((root/'captured/native'/name).read_bytes(),raw)
                (tree/'fs/proc/generic.c').write_bytes(b'changed')
                with self.assertRaises(ValueError): owner.capacity_native_capture(tree,root/'rejected')


if __name__=='__main__':unittest.main()
