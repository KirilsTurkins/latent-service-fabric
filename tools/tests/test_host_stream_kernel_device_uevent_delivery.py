"""Source-origin, preallocation and original callback/retirement boundaries."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_uevent_delivery as delivery


class KernelDeviceUeventDeliverySource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = delivery.fixture()

    def setUp(self):
        self.saved_fixture = delivery.fixture
        cache = patch.object(delivery, 'fixture', return_value=self.value)
        cache.start()
        self.addCleanup(cache.stop)

    def raw(self, name):
        return self.value['sections'][name]['text']

    def test_exact_wholes_definitions_parent_projections_and_false_gates(self):
        parent = delivery.prior.fixture()
        self.assertEqual((len(self.value['source']), len(self.value['sections'])), (92, 135))
        for key in ('source', 'sections'):
            self.assertEqual({n: self.value[key][n] for n in parent[key]}, parent[key])
        self.assertEqual(set(self.value['source']) - set(parent['source']), delivery.EXTRAS)
        self.assertTrue(all(self.value[n] is False for n in delivery.GATES))

    def test_unknown_changed_duplicate_and_crlf_definitions_fail_closed(self):
        for name in delivery.DEFINITIONS:
            raw = self.raw(name)
            self.assertEqual(delivery.section(raw, name), raw)
            for wrong in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('{', '{ ', 1)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    delivery.section(wrong, name)
        with self.assertRaises(KeyError):
            delivery.section('', 'unreviewed_hook')
        with self.assertRaises(ValueError):
            delivery.authenticate({})

    def test_rehashed_members_and_enablement_claims_refuse(self):
        variants = []
        for key in ('source', 'sections', 'priorProjectedSections'):
            v = json.loads(json.dumps(self.value));v[key]['unreviewed'] = {};variants.append(v)
        for name in delivery.GATES:
            v = json.loads(json.dumps(self.value));v[name] = True;variants.append(v)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.json'
            for value in variants:
                path.write_bytes(json.dumps(value).encode())
                with patch.object(delivery, 'FIXTURE', path), self.assertRaises(ValueError):
                    self.saved_fixture()

    def test_projected_config_off_duplicates_are_exact_originals(self):
        for name, row in self.value['priorProjectedSections'].items():
            text = row['text']
            if row['prefixOccurrences'] == 2:
                text += self.raw(name)
            self.assertEqual(delivery.section(text, name, projected=True), row['text'])
            self.assertIn('lsf_factory_device_uevent_', delivery.skb_dispatch(row['text'], name))
            with self.subTest(name=name), self.assertRaises(ValueError):
                delivery.skb_dispatch(row['text'].replace('{', '{ ', 1), name)
            with self.assertRaises(ValueError):
                delivery.section(text + self.raw(name), name, projected=True)

    def test_main_event_validates_actual_origin_before_any_array_deref_callback_or_allocation(self):
        selected = delivery.private_env(self.raw('kobject_uevent_env'))
        self.assertLess(selected.index('(unsigned int)action >= ARRAY_SIZE'),
            selected.index('action_string = kobject_actions[action]'))
        self.assertLess(selected.index('lsf_factory_device_uevent_current(source)'),
            selected.index('kobj->state_remove_uevent_sent = 1'))
        self.assertLess(selected.index('kobj->state_remove_uevent_sent = 1'),
            selected.index('IS_ENABLED(CONFIG_UEVENT_HELPER)'))
        self.assertLess(selected.index('lsf_prepaid_device_uevent_device(kobj)'),
            selected.index('uevent_ops->filter(kobj)'))
        self.assertLess(selected.index('lsf_prepaid_device_uevent_ops_known(uevent_ops)'),
            selected.index('uevent_ops->filter(kobj)'))
        self.assertIn('source.address != actual.address', selected)
        self.assertIn('source.pci_generation != actual.pci_generation', selected)
        self.assertIn('envp_ext ||', selected)
        self.assertIn('depth > LSF_DEVICE_UEVENT_MAX_ANCESTORS', selected)

    def test_real_filter_name_uevent_sequence_and_broadcast_are_still_called(self):
        selected = delivery.private_env(self.raw('kobject_uevent_env'))
        for actual in ('uevent_ops->filter(kobj)', 'uevent_ops->name(kobj)',
                'uevent_ops->uevent(kobj, env)', 'atomic64_inc_return(&uevent_seqnum)',
                'kobject_uevent_net_broadcast(kobj, env, action_string,'):
            self.assertEqual(selected.count(actual), 1)
        self.assertNotIn('kzalloc(', selected)
        self.assertNotIn('kfree(devpath)', selected)
        self.assertNotIn('kfree(env)', selected)
        self.assertIn('lsf_factory_device_uevent_return(devpath, LSF_DEVICE_UEVENT_KIND_PATH) != 1', selected)
        self.assertIn('lsf_factory_device_uevent_return(env, LSF_DEVICE_UEVENT_KIND_ENV) != 1', selected)

    def test_env_and_actual_path_span_are_checked_before_string_read_and_skb_birth(self):
        selected = delivery.private_alloc_skb(self.raw('alloc_uevent_skb'))
        for precondition in ('source.kind != LSF_DEVICE_UEVENT_KIND_ENV', 'source.address != env',
                'lsf_factory_device_uevent_current(source) != 1',
                'lsf_factory_device_uevent_path_bytes(devpath, &path_source, &path_bytes) != 1',
                'path_source.pci_generation != source.pci_generation'):
            self.assertLess(selected.index(precondition), selected.index('strnlen(devpath, path_bytes)'))
        self.assertLess(selected.index('path_length == path_bytes'),
            selected.index('lsf_prepaid_device_uevent_skb_new('))
        self.assertIn('LSF_DEVICE_UEVENT_MAX_HEAD_BYTES - env->buflen', selected)
        for original in ('parms = &NETLINK_CB(skb)', 'parms->creds.uid = GLOBAL_ROOT_UID',
                'parms->creds.gid = GLOBAL_ROOT_GID', 'parms->dst_group = 1',
                'parms->portid = 0'):
            self.assertIn(original, selected)
        self.assertNotIn('skb = alloc_skb(', selected)

    def test_filter_refusal_does_not_bypass_real_lsm_and_socket_filter_is_checked_under_rcu(self):
        selected = delivery.filter_guard(self.raw('sk_filter_trim_cap'))
        self.assertLess(selected.index('IS_ENABLED(CONFIG_BPF_SYSCALL)'),
            selected.index('BPF_CGROUP_RUN_PROG_INET_INGRESS(sk, skb)'))
        self.assertLess(selected.index('security_sock_rcv_skb(sk, skb)'),
            selected.index('rcu_read_lock()'))
        self.assertLess(selected.index('rcu_read_lock()'),
            selected.index('filter = rcu_dereference(sk->sk_filter)'))
        point = selected.index('if (uevent_owned) {', selected.index('rcu_read_lock()'))
        self.assertLess(point, selected.index('bpf_prog_run_save_cb('))
        self.assertIn('rcu_read_unlock();\n\t\t\treturn -EOPNOTSUPP;', selected[point:])

    def test_real_active_lsm_identities_are_checked_before_original_mandatory_dispatch(self):
        selected = delivery.security_guard(self.raw('security_sock_rcv_skb'))
        self.assertLess(selected.index('sk->sk_family != PF_NETLINK'),
            selected.index('lsm_for_each_hook(scall, socket_sock_rcv_skb)'))
        self.assertLess(selected.index('lsf_prepaid_device_selinux_socket_hook('),
            selected.index('return call_int_hook(socket_sock_rcv_skb, sk, skb)'))
        actual = self.raw('selinux_socket_sock_rcv_skb')
        self.assertLess(actual.index('family != PF_INET && family != PF_INET6'),
            actual.index('selinux_policycap_netpeer()'))
        self.assertEqual(selected.count('return call_int_hook(socket_sock_rcv_skb, sk, skb)'), 1)

    def test_wrappers_preserve_entire_ordinary_bodies_and_unsupported_operations_refuse_early(self):
        for name, operation in [('kobject_uevent_env', delivery.env_dispatch),
                ('alloc_uevent_skb', delivery.alloc_skb_dispatch),
                ('security_sock_rcv_skb', delivery.security_guard)]:
            raw = self.raw(name);selected = operation(raw)
            self.assertIn(raw.split('\n{\n', 1)[1][:-2], selected)
        for name, expression in [('kobject_synth_uevent', 'kobj'),
                ('kobject_rename', 'kobj'), ('kobject_move', 'kobj'), ('uevent_show', '&dev->kobj')]:
            raw = self.raw(name)
            selected = delivery.unsupported_kobject_operation(raw, name, expression)
            self.assertIn(raw.split('\n{\n', 1)[1][:-2], selected)
            self.assertLess(selected.index('lsf_factory_device_uevent_kobject('),
                selected.index('\t{\n#endif\n'))

    def test_copy_and_retirement_dispatch_precede_old_shape_and_allocator_access(self):
        for name, row in self.value['priorProjectedSections'].items():
            selected = delivery.skb_dispatch(row['text'], name)
            self.assertIn(row['text'].split('\n{\n', 1)[1][:-2], selected)
            if name not in ('skb_kfree_head', 'kfree_skbmem'):
                self.assertLess(selected.index('lsf_factory_device_uevent_birth(skb,'),
                    selected.index('\t{\n#endif\n'))
        for name in ('skb_copy', '__pskb_copy_fclone', 'skb_copy_expand'):
            selected = delivery.private_copy(self.raw(name), name)
            self.assertLess(selected.index('lsf_prepaid_device_uevent_linear(skb, source)'),
                selected.index('lsf_prepaid_device_uevent_skb_new(source,'))
            self.assertNotIn('__alloc_skb(', selected)
            self.assertIn('skb_copy_header(n, skb)', selected)
        self.assertIn('|| fclone || headroom < 0', delivery.private_copy(
            self.raw('__pskb_copy_fclone'), '__pskb_copy_fclone'))

    def test_new_births_retain_original_bank_parent_even_after_descriptor_close(self):
        source = (delivery.OWNED / 'factory-device-uevent.c').read_text()
        start = source.index('static int lsf_factory_device_uevent_current_locked(')
        end = source.index('\nint lsf_factory_device_uevent_kobject(', start)
        current = source[start:end]
        self.assertLess(current.index('factory.pool.poisoned'), current.index('source.kind == LSF_DEVICE_UEVENT_SKB'))
        self.assertLess(current.index('if (source.kind == LSF_DEVICE_UEVENT_SKB)\n            return 1;'),
            current.index('!READ_ONCE(factory.uncertain)'))
        self.assertIn('factory.device->core_tail_task == current', current)
        self.assertIn('source.slot != actual.slot || source.generation != actual.generation', current)
        self.assertIn('lsf_device_allocate(&factory.pool, factory.device->key, bytes, kind,', source)
        self.assertIn('parent, &ticket, &offset)', source)
        self.assertLess(source.index('lsf_device_queue(&factory.pool'),
            source.index('lsf_device_finish(&factory.pool'))
        self.assertLess(source.index('spin_unlock_irqrestore(&pool_lock, flags);',
            source.index('int lsf_factory_device_uevent_return(')),
            source.index('lsf_factory_device_firmware_schedule();'))

    def test_shape_is_authenticated_before_shared_info_or_new_head_allocation(self):
        source = (delivery.OWNED / 'device-uevent-skb.c').read_text()
        start = source.index('static bool lsf_prepaid_device_uevent_linear(')
        linear = source[start:source.index('\nstatic struct sk_buff *lsf_prepaid_device_uevent_clone(', start)]
        self.assertLess(linear.index('source.address != skb'), linear.index('skb->head'))
        self.assertLess(linear.index('lsf_factory_device_uevent_head_current('),
            linear.index('skb_shinfo(skb)->nr_frags'))
        for guard in ('data < head', 'tail > skb_end_offset(skb)', 'skb->len != tail - (data - head)',
                'head_birth.pci_generation != source.pci_generation'):
            self.assertIn(guard, linear)
        expand = source[source.index('static int lsf_prepaid_device_uevent_expand('):]
        self.assertLess(expand.index('lsf_prepaid_device_uevent_linear(skb, source)'),
            expand.index('osize = skb_end_offset(skb)'))
        self.assertLess(expand.index('requested > (long)LSF_DEVICE_UEVENT_MAX_HEAD_BYTES'),
            expand.index('data = lsf_prepaid_device_uevent_head('))
        self.assertIn('return __skb_clone(copy, skb)', source)
        self.assertIn('skb_release_data(skb, SKB_CONSUMED)', expand)

    def test_no_caller_selected_actor_or_ordinary_callback_substitution(self):
        callbacks = (delivery.OWNED / 'device-uevent-callbacks.c').read_text()
        for guard in ('kobj->ktype != &device_ktype', 'kobj->kset != devices_kset',
                'dev->class || dev->devt || dev_of_node(dev)',
                'lsf_prepaid_device_uevent_pci_bus_known(dev->bus)',
                'lsf_prepaid_device_uevent_pci_type_known(dev->type)',
                'kobj->parent->ktype->child_ns_type', 'devices_kset->kobj.parent'):
            self.assertIn(guard, callbacks)
        self.assertNotIn('constructor_task =', callbacks)
        path = (delivery.OWNED / 'device-uevent-kobject.c').read_text()
        for bound in ('depth > LSF_DEVICE_UEVENT_MAX_ANCESTORS', 'strnlen(name, NAME_MAX + 1)',
                'length > PATH_MAX - size - 1', 'size >= remaining', 'if (remaining)'):
            self.assertIn(bound, path)
        self.assertNotIn('kzalloc(', path)
        self.assertNotIn('kobject_get_path(', path)


if __name__ == '__main__':
    unittest.main()
