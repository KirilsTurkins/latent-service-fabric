"""Source controls for the uninstalled device pre-enumeration prefix."""
from pathlib import Path
import unittest
from tools import host_stream_kernel_device as device


class KernelDevicePrefixSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = device.fixture()
        cls.sections = cls.value['sections']

    def owned(self, name):
        return (device.OWNED/name).read_text()

    def test_original_packet_inputs_and_six_complete_definitions_are_preserved(self):
        parent = device.prior.fixture()
        self.assertEqual(len(self.value['source']),58)
        self.assertEqual({n:self.value['source'][n] for n in parent['source']},parent['source'])
        self.assertEqual(set(self.value['source'])-set(parent['source']),device.EXTRAS)
        self.assertEqual(len([r for r in self.sections.values() if r['source']==device.PCI]),6)
        self.assertTrue(all(self.value[g] is False for g in device.GATES))

    def test_whole_source_definition_missing_changed_duplicate_and_crlf_refuse(self):
        with self.assertRaises(ValueError):device.authenticate({})
        for name,row in self.sections.items():
            raw=row['text']
            self.assertEqual(device.section(raw,name),raw)
            for changed in (raw+raw,raw.replace('\n','\r\n'),raw.replace('\n{\n','\n{\n;\n',1)):
                with self.subTest(name=name),self.assertRaises(ValueError):
                    device.section(changed,name)

    def test_selected_fence_precedes_existing_lookup_and_keeps_complete_normal_body(self):
        raw=self.sections['pci_scan_single_device']['text']
        routed=device.scan_routing(raw)
        declaration,body=raw.split('\n{\n',1)
        selected=routed.split('#else\n',1)[0]
        self.assertLess(selected.index('lsf_factory_device_selected('),selected.index('pci_get_slot('))
        self.assertIn('\t{\n'+body+'}\n',selected)
        self.assertTrue(routed.endswith('#else\n'+raw+'#endif\n'))
        self.assertNotIn('0x1af4',routed)

    def test_previously_discovered_device_is_put_and_never_adopted(self):
        selected=device.private(self.sections['pci_scan_single_device']['text'],'pci_scan_single_device')
        self.assertLess(selected.index('lsf_factory_device_pci_enter('),selected.index('pci_get_slot('))
        self.assertIn('if (dev) {\n\t\tpci_dev_put(dev);\n\t\tdev = NULL;\n\t\tgoto out;\n\t}',selected)
        self.assertIn('pci_device_add(dev, bus);\n\nout:\n\tlsf_factory_device_pci_leave();\n\treturn dev;',selected)

    def test_original_factory_close_mutex_spans_every_selected_constructor_exit(self):
        raw=self.owned('factory-device.c')
        enter=raw[raw.index('int lsf_factory_device_pci_enter('):raw.index('void lsf_factory_device_pci_leave(')]
        self.assertLess(enter.index('mutex_lock(&factory_lock)'),enter.index('lsf_factory_device_pci_ready('))
        self.assertIn('mutex_unlock(&factory_lock);\n        return 0;',enter)
        selected=device.private(self.sections['pci_scan_single_device']['text'],'pci_scan_single_device')
        tail=selected.split('lsf_factory_device_pci_enter(',1)[1]
        self.assertEqual(tail.count('return NULL;'),1)
        self.assertEqual(tail.count('return dev;'),1)
        self.assertLess(selected.index('pci_device_add(dev, bus)'),selected.index('lsf_factory_device_pci_leave()'))
        factory=self.owned('factory.c')
        release=factory[factory.index('static int lsf_factory_release('):]
        self.assertLess(release.index('mutex_lock(&factory_lock)'),release.index('factory.pool.stopped = 1'))

    def test_sriov_alternate_path_refuses_before_any_bus_or_device_birth(self):
        raw=self.sections['pci_iov_add_virtfn']['text']; selected=device.vf_routing(raw)
        fence=selected.split('\t{\n',1)[0]
        self.assertIn('pci_iov_virtfn_bus(dev, id), pci_iov_virtfn_devfn(dev, id)',fence)
        self.assertIn('return -EOPNOTSUPP;',fence)
        self.assertLess(selected.index('return -EOPNOTSUPP;'),selected.index('virtfn_add_bus('))
        self.assertLess(selected.index('return -EOPNOTSUPP;'),selected.index('pci_alloc_dev('))
        self.assertNotIn('lsf_prepaid_pci_alloc_dev',selected)
        self.assertTrue(selected.endswith('#else\n'+raw+'#endif\n'))
        self.assertIn('\t{\n'+raw.split('\n{\n',1)[1]+'}\n',selected)
        with self.assertRaises(ValueError):device.vf_routing(raw+'\n')

    def test_sriov_coordinate_helpers_are_complete_original_read_only_geometry(self):
        for name in ('pci_iov_virtfn_bus','pci_iov_virtfn_devfn'):
            raw=self.sections[name]['text']
            self.assertEqual(device.section(raw,name),raw)
            self.assertIn('if (!dev->is_physfn)\n\t\treturn -EINVAL;',raw)
            for forbidden in ('alloc(', 'pci_device_add(', 'pci_write_', '->offset =', '->stride ='):
                self.assertNotIn(forbidden,raw)

    def test_private_setup_keeps_every_original_statement_except_name_spelling(self):
        raw=self.sections['pci_setup_device']['text'];selected=device.private(raw,'pci_setup_device')
        guard_start=selected.index('\tif (lsf_factory_device_pci_owned(')
        guard_end=selected.index('\thdr_type = pci_hdr_type(dev);')
        restored=selected[:guard_start]+selected[guard_end:]
        restored=restored.replace('lsf_prepaid_pci_setup_device(', 'pci_setup_device(').replace(
            '\tdev_set_name(&dev->dev, LSF_DEVICE_PCI_NAME);\n',
            '\tdev_set_name(&dev->dev, "%04x:%02x:%02x.%d", pci_domain_nr(dev->bus),\n'
            '\t\t     dev->bus->number, PCI_SLOT(dev->devfn),\n'
            '\t\t     PCI_FUNC(dev->devfn));\n')
        self.assertEqual(restored,raw)
        self.assertIn('pci_set_of_node(dev)',selected)
        self.assertIn('pci_set_acpi_fwnode(dev)',selected)
        self.assertIn('pci_fixup_device(pci_fixup_early, dev)',selected)

    def test_actual_birth_and_real_rodata_guard_precede_every_setup_effect(self):
        selected=device.private(self.sections['pci_setup_device']['text'],'pci_setup_device')
        self.assertLess(selected.index('lsf_factory_device_pci_owned(dev, sizeof(*dev)) != 1'),
            selected.index('pci_domain_nr(dev->bus)'))
        self.assertLess(selected.index('!is_kernel_rodata((unsigned long)LSF_DEVICE_PCI_NAME)'),
            selected.index('pci_set_of_node(dev)'))
        self.assertLess(selected.index('!is_kernel_rodata((unsigned long)LSF_DEVICE_PCI_NAME)'),
            selected.index('dev_set_name('))
        self.assertIn('#define LSF_DEVICE_PCI_NAME "0000:00:03.0"',self.owned('device-private.h'))
        self.assertEqual('%04x:%02x:%02x.%d' % (0,0,3,0),'0000:00:03.0')

    def test_name_uses_actual_normal_const_string_allocation_and_cleanup_contract(self):
        fmt=self.sections['kvasprintf_const']['text'];dup=self.sections['kstrdup_const']['text']
        self.assertIn("if (!strchr(fmt, '%'))\n\t\treturn kstrdup_const(fmt, gfp);",fmt)
        self.assertIn('if (is_kernel_rodata((unsigned long)s))\n\t\treturn s;',dup)
        self.assertIn('return kstrdup(s, gfp);',dup)
        self.assertNotIn('%','0000:00:03.0');self.assertNotIn('/','0000:00:03.0')
        self.assertIn('kobject_set_name_vargs(&dev->kobj, fmt, vargs)',self.sections['dev_set_name']['text'])
        cleanup=self.sections['kobject_cleanup']['text']
        self.assertLess(cleanup.index('t->release(kobj)'),cleanup.index('kfree_const(name)'))
        self.assertIn('if (!is_kernel_rodata((unsigned long)x))\n\t\tkfree(x);',self.sections['kfree_const']['text'])

    def test_new_whole_pci_use_lookup_is_positive_only_and_never_adopts_addresses(self):
        raw=self.owned('factory-device.c');owned=raw[raw.index('int lsf_factory_device_pci_owned('):]
        self.assertLess(owned.index('value < base || value - base >= LSF_BACKING_BYTES'),
            owned.index('record = &factory.pool.records[i]'))
        self.assertIn('record->deferred != LSF_PREPAID_PUBLISHED || record->bytes < minimum',owned)
        self.assertIn('record->cache_anchor != factory.device->root.generation',owned)
        self.assertIn('owned = -1;',owned)
        self.assertIn('owned = 1;',owned)
        for forbidden in ('lsf_device_allocate(', 'kfree(', 'alloc_pages(', 'scope.identity'):
            self.assertNotIn(forbidden,owned)

    def test_real_pci_constructor_changes_only_original_allocator_and_signature(self):
        raw=self.sections['pci_alloc_dev']['text']
        selected=device.private(raw,'pci_alloc_dev')
        restored=selected.replace('lsf_prepaid_pci_alloc_dev(struct pci_bus *bus, int devfn)',
            'pci_alloc_dev(struct pci_bus *bus)').replace(
            '\tdev = lsf_factory_device_pci_allocate(pci_domain_nr(bus), bus->number,\n'
            '\t\tdevfn, sizeof(struct pci_dev));\n',
            '\tdev = kzalloc(sizeof(struct pci_dev), GFP_KERNEL);\n')
        self.assertEqual(restored,raw)
        for marker in ('pci_bus_get(bus)','spin_lock_init(&dev->pcie_cap_lock)',
            'raw_spin_lock_init(&dev->msi_lock)','PCI Exclusive'):
            self.assertIn(marker,selected)

    def test_identity_and_real_owner_checked_before_birth_and_original_setup(self):
        selected=device.private(self.sections['pci_scan_device']['text'],'pci_scan_device')
        self.assertLess(selected.index('lsf_factory_device_pci_ready('),selected.index('pci_bus_read_dev_vendor_id('))
        self.assertLess(selected.index('(l & 0xffff) != LSF_DEVICE_PCI_VENDOR'),selected.index('lsf_prepaid_pci_alloc_dev('))
        self.assertLess(selected.index('(l >> 16) != LSF_DEVICE_PCI_DEVICE'),selected.index('lsf_prepaid_pci_alloc_dev('))
        self.assertIn('if (lsf_prepaid_pci_setup_device(dev)) {\n\t\tpci_bus_put(dev->bus);\n'
            '\t\t(void)lsf_factory_device_pci_return(dev);\n\t\treturn NULL;',selected)
        self.assertNotIn('kfree(',selected)

    def test_final_callback_keeps_every_original_cleanup_before_private_return(self):
        raw=self.sections['pci_release_dev']['text'];selected=device.final_routing(raw)
        extension='#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (lsf_factory_device_pci_return(pci_dev))\n'
        extension+='\t\treturn;\n#endif\n'
        self.assertEqual(selected.replace(extension,''),raw)
        for marker in ('pci_release_capabilities(pci_dev)','pci_release_of_node(pci_dev)',
            'pcibios_release_device(pci_dev)','pci_bus_put(pci_dev->bus)','bitmap_free(pci_dev->dma_alias_mask)'):
            self.assertLess(selected.index(marker),selected.index('lsf_factory_device_pci_return('))

    def test_same_original_store_tail_and_separate_node_domain_no_application_scope(self):
        raw=self.owned('device-prepaid.h')
        self.assertIn('#define LSF_DEVICE_OWNER_SLOT (LSF_OWNER_SLOTS - 1u)',raw)
        self.assertIn('key.slot != LSF_DEVICE_OWNER_SLOT',raw)
        self.assertIn('LSF_FACTORY_INFRA_OFFSET + context->cursor',raw)
        self.assertIn('i < LSF_ALLOCATION_SLOTS',raw)
        self.assertIn('struct lsf_prepaid_view *record = &pool->records[i]',raw)
        self.assertNotIn('struct lsf_scope scope',raw)
        self.assertNotIn('context->scope =',raw)
        self.assertNotIn('alloc_pages',raw)
        self.assertNotIn('kmalloc',raw)

    def test_same_record_actual_parent_generation_and_children_block_early_return(self):
        raw=self.owned('device-prepaid.h')
        self.assertIn('.cache_bucket = parent.slot',raw)
        self.assertIn('.cache_anchor = parent.generation',raw)
        self.assertIn('child->cache_bucket == ticket.slot && child->cache_anchor == ticket.generation',raw)
        self.assertLess(raw.index('child->cache_bucket == ticket.slot'),raw.index('record->phase = LSF_PREPAID_RETURNED'))
        self.assertIn('context->live != 1',raw)
        self.assertNotIn('LSF_PREPAID_EMPTY;',raw)

    def test_fixed_coordinate_does_not_select_every_virtio_or_any_operator_path(self):
        raw=self.owned('device-private.h')
        self.assertIn('#define LSF_DEVICE_PCI_DEVFN (3u << 3)',raw)
        self.assertIn('domain == LSF_DEVICE_PCI_DOMAIN && bus == LSF_DEVICE_PCI_BUS &&',raw)
        self.assertIn('devfn == LSF_DEVICE_PCI_DEVFN',raw)
        self.assertIn('#define LSF_DEVICE_PCI_DEVICE 0x1041u',raw)
        for marker in ('module_param','sysctl','EXPORT_SYMBOL','ioctl'):
            self.assertNotIn(marker,raw)

    def test_actual_factory_root_prepaid_before_pointer_and_single_constructor(self):
        raw=self.owned('factory-device.c')
        self.assertLess(raw.index('lsf_device_allocate(&factory.pool, key, sizeof(*state)'),
            raw.index('state = (void *)'))
        self.assertLess(raw.index('lsf_device_publish(&factory.pool, key, root'),raw.index('factory.device = state'))
        self.assertIn('current->mm == factory.mm',raw)
        self.assertIn('current_cred() == factory.cred',raw)
        self.assertIn('current->nsproxy->net_ns == factory.net',raw)
        self.assertIn('!factory.device->pci_attempted',raw)
        self.assertIn('factory.device->pci_attempted = 1;',raw)

    def test_unknown_interior_never_normal_frees_and_real_final_return_keeps_backing(self):
        raw=self.owned('factory-device.c')
        self.assertLess(raw.index('value < base || value - base >= LSF_BACKING_BYTES'),
            raw.index('record = &factory.pool.records[i]'))
        self.assertIn('returned = -1;',raw)
        self.assertIn('factory.pool.poisoned = 1;',raw)
        self.assertIn('WRITE_ONCE(factory.uncertain, 1)',raw)
        self.assertLess(raw.index('lsf_device_queue(&factory.pool'),raw.index('lsf_device_finish(&factory.pool'))
        for marker in ('kfree(', '__free_pages(', 'reserve_protocol_metadata(', 'new lsf_'):
            self.assertNotIn(marker,raw)

    def test_unclosed_original_setup_and_mandatory_registration_still_block_enablement(self):
        factory=self.owned('factory.c');selected=self.owned('factory-private.h')
        self.assertIn('if (!lsf_factory_selected_consumer())\n        return error;',factory)
        self.assertLess(factory.index('if (!lsf_factory_selected_consumer())'),factory.index('factory.pages = alloc_pages('))
        self.assertIn('lsf_factory_selected_consumer(void)\n{\n    return NULL;',selected)
        self.assertIn('pci_init_capabilities(dev);',self.sections['pci_device_add']['text'])
        self.assertIn('ret = device_add(&dev->dev);',self.sections['pci_device_add']['text'])
        self.assertIn('dev_set_name(&dev->dev',self.sections['pci_setup_device']['text'])
        self.assertTrue(all(self.value[g] is False for g in device.GATES))


if __name__=='__main__':unittest.main()
