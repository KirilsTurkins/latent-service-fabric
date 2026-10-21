"""Authenticate the uninstalled cached-firmware subset without a kernel build."""
import inspect
import re
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_firmware as firmware


class KernelDeviceFirmwareSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value=firmware.fixture()
        cls.sections=cls.value['sections']

    def owned(self,name):
        return (firmware.OWNED/name).read_text()

    def test_exact_sixty_six_whole_members_and_all_nineteen_original_definitions_remain(self):
        old=firmware.prior.fixture()
        # Original66 plus five authenticated lifetime/queue source inputs.
        self.assertEqual(len(self.value['source']),71)
        self.assertEqual({name:self.value['source'][name] for name in old['source']},old['source'])
        self.assertEqual(set(self.value['source'])-set(old['source']),firmware.EXTRAS)
        self.assertEqual({name:self.sections[name] for name in old['sections']},old['sections'])
        self.assertEqual(set(self.sections)-set(old['sections']),firmware.DEFINITIONS)
        self.assertEqual(len(self.sections),55)

    def test_missing_changed_duplicate_crlf_and_wrong_definition_refuse(self):
        with self.assertRaises(ValueError):firmware.authenticate({})
        for name in firmware.DEFINITIONS:
            raw=self.sections[name]['text']
            self.assertEqual(firmware.section(raw,name),raw)
            for changed in ('',raw+'\n'+raw,raw.replace('\n','\r\n'),raw.replace('{','{ ',1)):
                with self.subTest(name=name),self.assertRaises(ValueError):firmware.section(changed,name)
        with self.assertRaises(ValueError):firmware.companion(self.sections['pci_set_acpi_fwnode']['text'])

    def test_companion_keeps_original_identity_and_root_hid_policy(self):
        text=firmware.companion(self.sections['acpi_pci_find_companion']['text'])
        self.assertIn('struct pci_dev *pci_dev = to_pci_dev(dev);',text)
        self.assertIn('check_children = pci_is_bridge(pci_dev);',text)
        self.assertIn('addr = (PCI_SLOT(pci_dev->devfn) << 16) | PCI_FUNC(pci_dev->devfn);',text)
        self.assertIn('adev && adev->pnp.type.platform_id && !addr &&\n\t    pci_is_root_bus(pci_dev->bus)',text)
        self.assertIn('pci_acpi_find_companion_hook ?\n\t\tpci_acpi_find_companion_hook(pci_dev) : NULL;',text)
        self.assertIn('if (error)\n\t\treturn error;',text)
        self.assertNotIn('down_read(',text)
        self.assertNotIn('up_read(',text)

    def test_actual_owned_birth_check_precedes_all_device_dereferences(self):
        text=self.owned('device-acpi-private.c')
        self.assertLess(text.index('lsf_factory_device_pci_owned(dev, sizeof(*dev)) != 1'),text.index('dev_fwnode(&dev->dev)'))
        self.assertIn('dev_fwnode(&dev->dev) || pci_dev_is_added(dev)',text)
        self.assertLess(text.index('dev_fwnode(&dev->dev)'),text.index('lsf_prepaid_acpi_scan_enter()'))
        self.assertNotIn('lsf_device_allocate(',text)

    def test_same_original_try_locks_cover_hook_lookup_and_association(self):
        text=self.owned('device-acpi-private.c')
        ordered=('lsf_prepaid_acpi_scan_enter()','down_read_trylock(&pci_acpi_companion_lookup_sem)',
            'if (pci_acpi_find_companion_hook)','lsf_prepaid_acpi_pci_find_companion(&dev->dev, &companion)',
            'ACPI_COMPANION_SET(&dev->dev, companion)','up_read(&pci_acpi_companion_lookup_sem)',
            'lsf_prepaid_acpi_scan_leave()')
        positions=[text.index(value) for value in ordered]
        self.assertEqual(positions,sorted(positions))
        self.assertIn('goto scan_out;',text);self.assertIn('goto lookup_out;',text)
        self.assertEqual(text.count('return error;'),5)
        self.assertNotIn('pci_acpi_find_companion_hook(',text)

    def test_original_hook_writers_use_the_same_write_semaphore(self):
        for name in ('pci_acpi_set_companion_lookup_hook','pci_acpi_clear_companion_lookup_hook'):
            text=self.sections[name]['text']
            self.assertLess(text.index('down_write(&pci_acpi_companion_lookup_sem)'),text.index('pci_acpi_find_companion_hook ='))
            self.assertLess(text.index('pci_acpi_find_companion_hook ='),text.index('up_write(&pci_acpi_companion_lookup_sem)'))

    def test_scan_admission_refuses_unknown_init_and_rechecks_actual_state_after_lock(self):
        text=self.owned('device-acpi-lock.c')
        self.assertEqual(text.count('READ_ONCE(acpi_disabled)'),2)
        self.assertEqual(text.count('READ_ONCE(acpi_scan_initialized)'),2)
        self.assertIn('!mutex_trylock(&acpi_scan_lock)',text)
        self.assertNotIn('mutex_lock(',text)
        self.assertEqual(text.count('mutex_unlock(&acpi_scan_lock)'),3)
        self.assertIn('acpi_scan_initialized = true;',self.sections['acpi_scan_init']['text'])
        for name in ('acpi_scan_lock_acquire','acpi_scan_lock_release'):
            self.assertIn('&acpi_scan_lock',self.sections[name]['text'])

    def test_finite_walk_counts_before_upstream_filters_non_acpi_children(self):
        text=self.owned('device-acpi-walk.c')
        self.assertLess(text.index('++owned->visited > LSF_DEVICE_ACPI_CHILDREN'),
            text.index('return acpi_dev_for_one_check(dev, &owned->original)'))
        self.assertIn('return -EOPNOTSUPP;',text)
        self.assertIn('return device_for_each_child(&parent->dev, &owned,',text)
        self.assertIn('#define LSF_DEVICE_ACPI_CHILDREN 32u',self.owned('device-firmware-private.h'))
        self.assertIn('if (dev->bus != &acpi_bus_type)\n\t\treturn 0;',self.sections['acpi_dev_for_one_check']['text'])

    def test_original_device_iterator_preserves_reference_exit_and_stops_before_advance(self):
        text=self.sections['device_for_each_child']['text']
        self.assertIn('klist_iter_init(&parent->p->klist_children, &i)',text)
        self.assertIn('while (!error && (child = next_device(&i)))',text)
        self.assertLess(text.index('error = fn(child, data)'),text.index('klist_iter_exit(&i)'))
        self.assertLess(text.index('klist_iter_exit(&i)'),text.index('return error;'))
        self.assertIn('klist_next(i)',self.sections['next_device']['text'])

    def test_single_walk_preserves_unique_match_and_refuses_second_before_aml(self):
        text=self.owned('device-acpi-child.c')
        self.assertIn('!adev->pnp.type.bus_address || acpi_device_adr(adev) != wd->address',text)
        self.assertIn('if (!wd->adev) {\n        owned->error = lsf_prepaid_acpi_reference(owned->consumer, adev);',text)
        self.assertLess(text.index('lsf_prepaid_acpi_reference(owned->consumer, adev)'),text.index('wd->adev = adev;'))
        self.assertIn('if (owned->error)\n            return 1;\n        wd->adev = adev;\n        return 0;',text)
        self.assertIn('owned->error = -EOPNOTSUPP;',text)
        self.assertIn('walked = lsf_prepaid_acpi_dev_for_each_child(parent, lsf_prepaid_check_one_child, &owned)',text)
        self.assertIn('if (owned.error)\n        return owned.error;',text)
        self.assertIn('if (walked)\n        return -EOPNOTSUPP;',text)
        self.assertNotIn('find_child_checks(',text);self.assertNotIn('acpi_evaluate_integer(',text)
        self.assertIn('if (check_children)\n        return -EOPNOTSUPP;',text)

    def test_original_ambiguity_really_enters_sta_instead_of_being_called_pure(self):
        self.assertIn('find_child_checks(wd->adev, wd->check_children)',self.sections['check_one_child']['text'])
        self.assertIn('acpi_evaluate_integer(adev->handle, "_STA", NULL, &sta)',self.sections['find_child_checks']['text'])
        self.assertIn('acpi_find_child(parent, address, check_children, true)',self.sections['acpi_find_child_device']['text'])

    def test_only_private_setup_call_gains_closed_error_propagation(self):
        code=inspect.getsource(firmware.derive)
        self.assertIn("old=prior.private(prior.fixture()['sections']['pci_setup_device']['text'],'pci_setup_device')",code)
        self.assertIn('err = lsf_prepaid_pci_set_acpi_fwnode(dev);\\n\\tif (err)\\n\\t\\treturn err;',code)
        self.assertIn("text=replace(outputs[prior.PCI].decode(),old,selected)",code)
        self.assertIn('lsf_factory_device_firmware_constructor_leave();',code)
        self.assertIn('lsf_factory_device_firmware_retire(address);',code)
        self.assertNotIn("outputs['net/prepaid.h']",code)

    def test_actual_reference_chain_and_iterator_lifetime_are_authenticated(self):
        expected={
            'acpi_dev_get':'get_device(&adev->dev)',
            'acpi_dev_put':'put_device(&adev->dev)',
            'get_device':'kobject_get(&dev->kobj)',
            'put_device':'kobject_put(&dev->kobj)',
            'kobject_get':'kref_get(&kobj->kref)',
            'kobject_put':'kref_put(&kobj->kref, kobject_release)',
            'klist_children_get':'get_device(dev)',
            'klist_children_put':'put_device(dev)',
            'klist_next':'kref_get(&next->n_ref)',
            'klist_iter_exit':'klist_put(i->i_cur, false)',
        }
        for name,call in expected.items():self.assertIn(call,self.sections[name]['text'],name)
        text=self.owned('factory-device-firmware.c')
        self.assertLess(text.index('lsf_device_allocate('),text.index('acpi_dev_get(adev)'))
        self.assertIn('owned->companion = acpi_dev_get(adev);',text)
        self.assertIn('owned->handle = adev->handle;',text)

    def test_original_deletion_callbacks_errors_requeue_and_put_are_preserved(self):
        for name,project in (('acpi_device_del_work_fn',firmware.deletion_worker),
                             ('acpi_scan_drop_device',firmware.deletion_invalidation)):
            raw=self.sections[name]['text'];text=project(raw)
            self.assertEqual(re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n','',text,flags=re.S),raw)
            with self.assertRaises(ValueError):project(raw.replace('acpi_device','changed_acpi_device',1))
        raw=firmware.deletion_worker(self.sections['acpi_device_del_work_fn']['text'])
        self.assertLess(raw.index('lsf_acpi_deletions_active++'),raw.index('\n\t\tmutex_unlock(&acpi_device_del_lock);',raw.index('lsf_acpi_deletions_active++')))
        self.assertLess(raw.index('acpi_dev_put(adev);'),raw.index('lsf_acpi_deletions_active--'))
        self.assertNotIn('goto ',raw)
        self.assertIn('if (lsf_acpi_deletions_active == ~0u)',raw)
        self.assertIn('if (!lsf_acpi_deletions_active)',raw)

    def test_admission_and_invalidation_share_original_delete_mutex(self):
        text=self.owned('device-acpi-lock.c')
        self.assertIn('!mutex_trylock(&acpi_device_del_lock)',text)
        for condition in ('lsf_acpi_deletion_uncertain','lsf_acpi_deletions_active','!list_empty(&acpi_device_del_list)'):
            self.assertIn(condition,text)
        self.assertIn('lockdep_assert_held(&acpi_device_del_lock);',text)
        self.assertIn('adev->handle == INVALID_ACPI_HANDLE',text)
        raw=firmware.deletion_invalidation(self.sections['acpi_scan_drop_device']['text'])
        ordered=('mutex_lock(&acpi_device_del_lock)','lsf_factory_device_firmware_invalidate(adev, adev->handle)',
                 'adev->handle = INVALID_ACPI_HANDLE','mutex_unlock(&acpi_device_del_lock)')
        positions=[raw.index(x) for x in ordered];self.assertEqual(positions,sorted(positions))

    def test_revocation_is_not_lifetime_retirement_or_pool_reuse(self):
        text=self.owned('factory-device-firmware.c')
        function=text.split('void lsf_factory_device_firmware_invalidate(',1)[1].split('\n}\n',1)[0]
        self.assertIn('owned->handle != handle',function)
        self.assertIn('owned->revoked = 1;',function)
        self.assertIn('WRITE_ONCE(factory.uncertain, 1)',function)
        for forbidden in ('acpi_dev_put(', 'lsf_device_finish(', 'lsf_device_queue(', 'kfree('):self.assertNotIn(forbidden,function)
        current=text.split('int lsf_factory_device_firmware_current(',1)[1].split('\n}\n',1)[0]
        self.assertIn('!owned->revoked && !owned->retirement && !owned->returned',current)
        self.assertIn('owned->handle == adev->handle',current)

    def test_one_real_child_work_reservation_precedes_exact_queue_dispatch(self):
        text=self.owned('factory-device-firmware.c')
        schedule=text.split('static void lsf_factory_device_firmware_schedule(void)',1)[1].split('\n}\n',1)[0]
        ordered=('factory.device->constructor_active','lsf_device_queue(&factory.pool','owned->queued = 1',
                 'spin_unlock_irqrestore(&pool_lock, flags)','lsf_prepaid_acpi_queue_reference_put(work)')
        positions=[schedule.index(x) for x in ordered];self.assertEqual(positions,sorted(positions))
        self.assertIn('LSF_DEVICE_ACPI_REFERENCE',schedule)
        self.assertIn('lsf_factory_device_firmware_poison();',schedule)
        self.assertIn('INIT_WORK(&owned->work, lsf_factory_device_firmware_put)',text)
        for forbidden in ('alloc_workqueue(', 'alloc_ordered_workqueue(', 'schedule_work(', 'queue_work('):self.assertNotIn(forbidden,text)

    def test_constructor_unlock_precedes_work_schedule_and_failure_stays_owned(self):
        code=inspect.getsource(firmware.derive)
        self.assertIn('mutex_unlock(&factory_lock);\\n\'\n        \'    lsf_factory_device_firmware_constructor_leave();',code)
        text=self.owned('factory-device-firmware.c')
        leave=text.split('void lsf_factory_device_firmware_constructor_leave(void)',1)[1].split('\n}\n',1)[0]
        self.assertLess(leave.index('factory.device->constructor_active = 0'),leave.index('lsf_factory_device_firmware_schedule()'))
        retire=text.split('int lsf_factory_device_firmware_retire(',1)[1].split('\n}\n',1)[0]
        self.assertIn('owned->retirement = 1;',retire)
        self.assertNotIn('acpi_dev_put(',retire);self.assertNotIn('lsf_device_finish(',retire)
        self.assertIn('if (owned->retirement)\n        goto poison;',retire)

    def test_known_queue_closure_refuses_before_any_descriptor_or_reference_admission(self):
        text=self.owned('device-acpi-private.c')
        self.assertLess(text.index('!lsf_prepaid_acpi_reference_queue_ready()'),text.index('lsf_factory_device_firmware_begin(dev)'))
        queue=self.owned('device-acpi-queue.c')
        ready=queue.split('int lsf_prepaid_acpi_reference_queue_ready(void)',1)[1].split('\n}\n',1)[0]
        ordered=('spin_lock_irqsave(&lsf_acpi_reference_queue_lock, flags)',
            'ready = lsf_acpi_reference_queue_live','spin_unlock_irqrestore(&lsf_acpi_reference_queue_lock, flags)', 'return ready;')
        positions=[ready.index(x) for x in ordered];self.assertEqual(positions,sorted(positions))
        self.assertNotIn('acpi_queue_hotplug_work(',ready)

    def test_real_put_outside_all_private_locks_precedes_child_and_parent_return(self):
        text=self.owned('factory-device-firmware.c')
        put=text.split('static void lsf_factory_device_firmware_put(',1)[1].split('\n}\n',1)[0]
        ordered=('owned->putting = 1','spin_unlock_irqrestore(&pool_lock, flags)',
            'ACPI_COMPANION_SET(&pci->dev, NULL)','acpi_dev_put(companion)',
            'spin_lock_irqsave(&pool_lock, flags)', 'lsf_device_finish(&factory.pool',
            'owned->returned = 1','lsf_factory_device_pci_return(pci)')
        cursor=0
        for name in ordered:cursor=put.index(name,cursor)+len(name)
        physical=put.split('spin_unlock_irqrestore(&pool_lock, flags);',1)[1].split('acpi_dev_put(companion);',1)[0]
        self.assertNotIn('mutex_lock(',physical);self.assertNotIn('spin_lock',physical)
        self.assertIn('deferred != LSF_PREPAID_QUEUED',put)
        self.assertIn('else if (dev_fwnode(&pci->dev))\n            goto poison_unlocked;',put)

    def test_original_queue_lifecycle_preserved_and_destroy_has_no_private_lock(self):
        for name in ('acpi_os_initialize1','acpi_os_terminate'):
            raw=self.sections[name]['text'];text=firmware.queue_lifecycle(raw,name)
            self.assertEqual(re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n','',text,flags=re.S),raw)
        init=firmware.queue_lifecycle(self.sections['acpi_os_initialize1']['text'],'acpi_os_initialize1')
        self.assertLess(init.index('BUG_ON(!kacpi_hotplug_wq)'),init.index('lsf_prepaid_acpi_reference_queue_state(true)'))
        end=firmware.queue_lifecycle(self.sections['acpi_os_terminate']['text'],'acpi_os_terminate')
        self.assertLess(end.index('lsf_prepaid_acpi_reference_queue_state(false)'),end.index('destroy_workqueue('))
        self.assertIn('return queue_work(kacpi_hotplug_wq, work);',self.sections['acpi_queue_hotplug_work']['text'])
        queue=self.owned('device-acpi-queue.c')
        self.assertIn('if (lsf_acpi_reference_queue_live)',queue)
        self.assertIn('queued = acpi_queue_hotplug_work(work);',queue)
        self.assertNotIn('destroy_workqueue(',queue)

    def test_descriptor_original_generation_parent_and_whole_extent_gate_every_dereference(self):
        text=self.owned('factory-device-firmware.c')
        for condition in ('record->generation != ticket.generation', 'record->kind != LSF_DEVICE_ACPI_REFERENCE',
            'record->owner_generation != factory.device->key.generation',
            'record->bytes < sizeof(struct lsf_factory_device_firmware)',
            'record->cache_bucket != pci.slot', 'record->cache_anchor != pci.generation',
            'owned->pci.slot != pci.slot', 'owned->pci.generation != pci.generation',
            'owned->pci_address != address', 'record->bytes < sizeof(struct pci_dev)'):
            self.assertIn(condition,text)
        self.assertNotIn('container_of(work',text)

    def test_all_private_includes_follow_actual_static_dependencies(self):
        code=inspect.getsource(firmware.derive)
        self.assertIn("raw+'\\n#ifdef CONFIG_LSF_STREAM_FACTORY\\n'+companion(raw)",code)
        self.assertIn("(GLUE,'acpi_find_child_device','device-acpi-child.c')",code)
        self.assertIn("(BUS,'acpi_dev_for_each_child','device-acpi-walk.c')",code)
        self.assertIn("'static bool acpi_scan_initialized;\\n#ifdef CONFIG_LSF_STREAM_FACTORY\\n'",code)
        self.assertIn('after its actual lookup rwsem, hook and original',self.owned('device-acpi-private.c'))

    def test_no_new_allocator_fallback_synthetic_owner_or_aml_stub_in_private_path(self):
        for name in ('device-acpi-child.c','device-acpi-walk.c','device-acpi-lock.c','device-acpi-private.c'):
            text=self.owned(name)
            for forbidden in ('kmalloc(', 'kzalloc(', 'kfree(', 'alloc_pages(', 'acpi_evaluate_integer(',
                'acpi_evaluate_object(', 'module_param(', 'EXPORT_SYMBOL', 'lsf_prepaid_initialize('):
                self.assertNotIn(forbidden,text,name)

    def test_actual_association_body_is_preserved_and_no_hook_policy_is_silently_skipped(self):
        text=self.sections['set_primary_fwnode']['text']
        self.assertIn('dev->fwnode = fwnode;',text)
        self.assertIn('fwnode->secondary = fn;',text)
        self.assertIn('if (parent && fn == parent->fwnode)',text)
        private=self.owned('device-acpi-private.c')
        self.assertIn('if (pci_acpi_find_companion_hook)\n        goto lookup_out;',private)
        self.assertLess(private.index('if (!error)'),private.index('ACPI_COMPANION_SET('))

    def test_all_enablement_firmware_and_runtime_gates_stay_closed(self):
        self.assertTrue(all(self.value[name] is False for name in firmware.GATES))
        self.assertIn('lsf_factory_selected_consumer(void)\n{\n    return NULL;',self.owned('factory-private.h'))
        self.assertIn('if (!lsf_factory_selected_consumer())\n        return error;',self.owned('factory.c'))
        self.assertNotIn('CONFIG_ACPI=n',inspect.getsource(firmware))
        self.assertNotIn('scripts/config',inspect.getsource(firmware))


if __name__=='__main__':unittest.main()
