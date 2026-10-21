"""Actual tap publication/RCU source fences; all normal recipients preserved."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_uevent as event


class KernelDeviceUeventSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = event.fixture()

    def setUp(self):
        self.saved_fixture = event.fixture
        cache = patch.object(event, 'fixture', return_value=self.value)
        cache.start()
        self.addCleanup(cache.stop)

    def test_exact_parent_wholes_definitions_and_all_uninstalled_gates(self):
        parent = event.prior.fixture()
        self.assertEqual((len(self.value['source']), len(self.value['sections'])), (88, 97))
        self.assertEqual({n: self.value['source'][n] for n in parent['source']}, parent['source'])
        self.assertEqual({n: self.value['sections'][n] for n in parent['sections']}, parent['sections'])
        self.assertEqual(set(self.value['source']) - set(parent['source']), event.EXTRAS)
        self.assertTrue(all(self.value[n] is False for n in event.GATES))

    def test_missing_duplicate_crlf_changed_function_or_struct_refuse(self):
        for name in event.DEFINITIONS:
            raw = self.value['sections'][name]['text']
            self.assertEqual(event.section(raw, name), raw)
            for wrong in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('{', '{ ', 1)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    event.section(wrong, name)
        with self.assertRaises(KeyError):
            event.section('', 'another_tap')
        with self.assertRaises(ValueError):
            event.authenticate({})

    def test_rehashed_members_or_enablement_assertion_are_not_accepted(self):
        variants = []
        for key in ('source', 'sections'):
            v = json.loads(json.dumps(self.value));v[key]['unreviewed'] = {};variants.append(v)
        for name in event.GATES:
            v = json.loads(json.dumps(self.value));v[name] = True;variants.append(v)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.json'
            for value in variants:
                path.write_bytes(json.dumps(value).encode())
                with patch.object(event, 'FIXTURE', path), self.assertRaises(ValueError):
                    self.saved_fixture()

    def test_add_reserves_before_pernet_mutex_and_publication_normal_body_projects_exactly(self):
        raw = self.value['sections']['netlink_add_tap']['text']
        selected = event.tap_add(raw)
        start = selected.index('#ifdef CONFIG_LSF_STREAM_FACTORY\n')
        end = selected.index('#endif\n', start) + len('#endif\n')
        self.assertLess(selected.index('ARPHRD_NETLINK'), start)
        self.assertLess(selected.index('lsf_factory_device_tap_admit(nt)'), selected.index('mutex_lock('))
        self.assertLess(selected.index('lsf_factory_device_tap_admit(nt)'), selected.index('list_add_rcu('))
        self.assertEqual(selected[:start] + selected[end:], raw)

    def test_remove_updates_only_success_after_actual_rcu_wait_normal_body_is_exact(self):
        raw = self.value['sections']['netlink_remove_tap']['text']
        selected = event.tap_remove(raw)
        start = selected.index('#ifdef CONFIG_LSF_STREAM_FACTORY\n')
        end = selected.index('#endif\n', start) + len('#endif\n')
        self.assertLess(selected.index('__netlink_remove_tap(nt)'), selected.index('synchronize_net();'))
        self.assertLess(selected.index('synchronize_net();'), selected.index('lsf_factory_device_tap_retired(nt)'))
        self.assertIn('if (!ret)', selected[start:end])
        self.assertEqual(selected[:start] + selected[end:], raw)

    def test_typed_marker_is_conditional_and_does_not_add_allocation_authority(self):
        raw = self.value['sections']['netlink_tap']['text']
        selected = event.tap_header(raw)
        start = selected.index('#ifdef CONFIG_LSF_STREAM_FACTORY\n')
        end = selected.index('#endif\n', start) + len('#endif\n')
        self.assertEqual(selected[:start] + selected[end:], raw)
        gate = (event.OWNED / 'factory-device-uevent-taps.c').read_text()
        for absent in ('mutex_lock(', 'alloc_pages(', 'synchronize_net(', 'dev_queue_xmit(', 'net_generic('):
            self.assertNotIn(absent, gate)
        self.assertNotIn('user_ns ==', gate)
        self.assertIn('lsf_device_uevent_taps.taps == U64_MAX', gate)
        self.assertIn('tap->lsf_device_uevent_admitted != 1', gate)

    def test_real_cross_namespace_recipient_and_tap_delivery_remain_in_original_definitions(self):
        rows = self.value['sections']
        broadcast = rows['do_one_broadcast']['text']
        for guard in ('LISTEN_ALL_NSID', 'peernet_has_id(', 'file_ns_capable('):
            self.assertIn(guard, broadcast)
        self.assertNotIn('sock_net(sk)->user_ns ==', broadcast)
        sendskb = rows['__netlink_sendskb']['text']
        self.assertLess(sendskb.index('netlink_deliver_tap(sock_net(sk), skb)'),
            sendskb.index('skb_queue_tail('))
        self.assertIn('ns_capable(sock_net(sk)->user_ns, CAP_NET_BROADCAST)',
            rows['netlink_setsockopt']['text'])
        self.assertIn('list_del_rcu(', rows['__netlink_remove_tap']['text'])

    def test_bank_fence_has_only_no_backing_allocation_failure_rollback(self):
        gate = (event.OWNED / 'factory-device-uevent-taps.c').read_text()
        self.assertEqual(gate.count('private_alive = 0;'), 1)
        rollback = gate[gate.index('static void lsf_factory_device_uevent_bank_allocation_failed('):]
        self.assertIn('!factory.pages', rollback)
        self.assertIn('!lsf_device_uevent_taps.taps', rollback)
        self.assertIn('lsf_device_uevent_taps.poisoned = 1;', rollback)
        source = Path(event.__file__).read_text()
        self.assertIn('sizeof(lsf_device_uevent_taps)', source)
        self.assertNotIn('LSF_BOOTSTRAP_CEILING *', source)
        self.assertNotIn('lsf_factory_device_uevent_bank_allocation_failed();',
            source[source.index('def derive('):])


if __name__ == '__main__':
    unittest.main()
