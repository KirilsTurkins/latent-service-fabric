"""Retain actual recipient selection, irreversible transfer, and security source."""
import re
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_delivery as delivery


class KernelDeviceDeliverySource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = delivery.fixture()
        cls.inputs = {}
        for row in cls.value['sections'].values():
            cls.inputs[row['source']] = cls.inputs.get(row['source'], b'') + row['text'].encode()

    def setUp(self):
        cache = patch.object(delivery, 'fixture', return_value=self.value)
        cache.start()
        self.addCleanup(cache.stop)

    def test_whole_original_parent_and_all_qualification_gates_stay_closed(self):
        parent = delivery.prior.fixture()
        self.assertEqual((len(self.value['source']), len(self.value['sections'])), (105, 189))
        for key in ('source', 'sections'):
            self.assertEqual({name: self.value[key][name] for name in parent[key]}, parent[key])
        self.assertTrue(all(self.value[key] is False for key in delivery.GATES))

    def test_changed_duplicate_crlf_and_unknown_definitions_refuse(self):
        for name in delivery.DEFINITIONS:
            raw = self.value['sections'][name]['text']
            self.assertEqual(delivery.section(raw, name), raw)
            for wrong in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('(', '( ', 1)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    delivery.section(wrong, name)
        with self.assertRaises(KeyError):
            delivery.section('', 'unselected_hook')

    def test_transfer_tail_never_dereferences_skb_or_changes_positive_delivery_to_error(self):
        body = delivery.private_sender(self.inputs)
        send = delivery.prior.prior.function(body, 'static int lsf_prepaid_device_netlink_sendskb(')
        before, after = send.split('\tskb_queue_tail(&sk->sk_receive_queue, skb);', 1)
        self.assertLess(before.index('lsf_factory_device_recipient_packet(source, sk, skb)'),
            before.index('len = skb->len'))
        self.assertIn('netlink_deliver_tap(sock_net(sk), skb);', before)
        executable = re.sub(r'/\*.*?\*/', '', after, flags=re.S)
        self.assertNotRegex(executable, r'\bskb\b')
        self.assertIn('*notification_error = lsf_prepaid_device_socket_notify(source, sk, false);', after)
        self.assertIn('return len;', after)
        self.assertNotIn('return -', after)
        one = delivery.prior.prior.function(body, 'static void lsf_prepaid_device_one_broadcast(')
        self.assertLess(one.index('p->delivered = 1;'), one.index('if (notification_error < 0)'))
        self.assertLess(one.index('p->skb2 = NULL;', one.index('p->delivered = 1;')),
            one.index('if (notification_error < 0)'))

    def test_original_rmem_and_congestion_thresholds_and_transfer_owner_remain_real(self):
        body = delivery.private_sender(self.inputs)
        raw = delivery.prior.prior.function(body, 'static int lsf_prepaid_device_broadcast_deliver(')
        self.assertLess(raw.index('lsf_factory_device_recipient_packet(source, sk, skb)'),
            raw.index('atomic_add_return(skb->truesize, &sk->sk_rmem_alloc)'))
        for actual in ['rcvbuf = READ_ONCE(sk->sk_rcvbuf);',
            '(rmem == skb->truesize || rmem <= rcvbuf)',
            '!test_bit(NETLINK_S_CONGESTED, &nlk->state)',
            'netlink_skb_set_owner_r(skb, sk);', 'return rmem > (rcvbuf >> 1);',
            'atomic_sub(skb->truesize, &sk->sk_rmem_alloc);']:
            self.assertIn(actual, raw)
        self.assertNotIn('skb_get(', raw)
        self.assertEqual(raw.count('atomic_sub('), 1)

    def test_namespace_credential_audit_requires_admitted_original_work(self):
        body = delivery.private_sender(self.inputs)
        one = delivery.prior.prior.function(body, 'static void lsf_prepaid_device_one_broadcast(')
        for original in ['if (p->exclude_sk == sk)', '!test_bit(p->group - 1, nlk->groups)',
                         '!nlk_test_bit(LISTEN_ALL_NSID, sk)', '!peernet_has_id(sock_net(sk), p->net)']:
            self.assertLess(one.index(original), one.index('lsf_factory_device_recipient_begin('))
        self.assertLess(one.index('lsf_factory_device_recipient_begin('),
            one.index('lsf_prepaid_device_file_ns_capable(source, sk->sk_socket->file,'))
        self.assertNotIn('!file_ns_capable(', one)
        self.assertLess(one.index('sock_put(sk);'), one.index('finish:'))
        tail = one[one.index('finish:'):]
        self.assertNotIn('sk->', tail)
        self.assertNotIn('p->skb', tail)
        self.assertIn('lsf_factory_device_recipient_finish(source)', tail)

    def test_unsupported_filter_is_not_a_silent_recipient_drop_or_callback(self):
        one = delivery.prior.prior.function(delivery.private_sender(self.inputs),
            'static void lsf_prepaid_device_one_broadcast(')
        self.assertNotIn('p->tx_filter(', one)
        start = one.index('if (p->tx_filter)')
        self.assertIn('lsf_factory_device_uevent_poison();', one[start:start + 160])
        self.assertIn('p->delivery_failure = 1;', one[start:start + 160])
        filter_start = one.index('val = sk_filter(sk, p->skb2);')
        start = one.index('if (val == -EOPNOTSUPP)', filter_start)
        drop = one.index('if (val) {', filter_start)
        self.assertLess(start, drop)
        self.assertIn('p->delivery_failure = 1;', one[start:drop])

    def test_capability_dispatch_preserves_actual_hook_order_and_finite_options(self):
        raw = delivery.private_security_capability()
        loops = [m.start() for m in re.finditer(r'lsm_for_each_hook\(scall, capable\)', raw)]
        self.assertEqual(len(loops), 2)
        self.assertLess(raw.index('lsf_factory_device_uevent_poison();'), loops[1])
        self.assertGreater(raw.index('rc = cap_capable(cred, ns, cap, opts);'), loops[1])
        self.assertIn('rc = LSM_RET_DEFAULT(capable)', raw)
        self.assertIn('if (rc != LSM_RET_DEFAULT(capable))', raw)
        self.assertIn('cap != CAP_NET_BROADCAST || opts != CAP_OPT_NONE', raw)
        self.assertIn('lsf_factory_device_recipient_blob(source, &owner) != 1', raw)
        private = delivery.private_selinux_capability(self.inputs)
        original = self.value['sections']['cred_has_capability']['text']
        selection = original[original.index('\tad.type ='):original.index('\trc = avc_has_perm_noaudit')]
        self.assertIn(selection, private)
        self.assertLess(private.index('opts != CAP_OPT_NONE'), private.index('CAP_TO_MASK(cap)'))
        self.assertIn('lsf_prepaid_avc_has_perm(sid, sid, sclass, av, &ad, source)', private)
        self.assertIn('ns == &init_user_ns', private)
        file_check = delivery.private_capability(self.inputs)
        self.assertLess(file_check.index('lsf_factory_device_recipient_current(source, NULL)'),
            file_check.index('file->f_cred'))

    def test_receiver_admits_before_copy_and_finishes_after_original_skb_free_and_wake(self):
        code = delivery.private_receiver(self.inputs)
        body = delivery.prior.prior.function(code, 'int lsf_prepaid_device_recvmsg_tail(')
        self.assertNotIn('skb_recv_datagram(', body)
        self.assertNotIn('skb_get(', body)
        self.assertLess(body.index('lsf_factory_device_recipient_begin(skb, sk, &source)'),
            body.index('data_skb = skb;'))
        original = self.value['sections']['netlink_recvmsg']['text']
        retained = original[original.index('\tdata_skb = skb;'):original.index('\tskb_free_datagram(sk, skb);')]
        self.assertIn(retained + '\tskb_free_datagram(sk, skb);', body)
        after = body.split('\tskb_free_datagram(sk, skb);', 1)[1]
        self.assertNotRegex(re.sub(r'/\*.*?\*/', '', after, flags=re.S), r'\b(?:data_skb|skb)\b')
        self.assertLess(after.index('lsf_prepaid_device_scm_recv(source'),
            after.index('lsf_prepaid_device_netlink_rcv_wake(source'))
        self.assertLess(after.index('lsf_prepaid_device_netlink_rcv_wake(source'),
            after.index('lsf_factory_device_recipient_finish(source)'))
        self.assertIn('atomic_read(&sk->sk_rmem_alloc) <= sk->sk_rcvbuf / 2', after)
        self.assertNotIn('ret = netlink_dump(', after)
        dump = after[after.index('READ_ONCE(nlk->cb_running)'):after.index('lsf_prepaid_device_scm_recv')]
        self.assertIn('lsf_factory_device_uevent_poison();', dump)
        self.assertIn('err = -EOPNOTSUPP;', dump)

    def test_netlink_scm_retains_credentials_and_guards_exact_zero_pid_file_cookie(self):
        code = delivery.private_scm(self.inputs)
        common = delivery.prior.prior.function(code, 'static int lsf_prepaid_device_scm_common(')
        self.assertLess(common.index('!scm || scm->pid || scm->fp || !sock || !msg'),
            common.index('if (!msg->msg_control)'))
        original = self.value['sections']['__scm_recv_common']['text']
        credentials = original[original.index('\tif (test_bit(SOCK_PASSCRED'):original.index('\tscm_passec')]
        self.assertIn(credentials, common)
        self.assertIn('scm_destroy(scm);', common)
        self.assertIn('scm_detach_fds(msg, scm);', common)
        self.assertNotIn('scm_pidfd_recv(', code)
        passec = delivery.prior.prior.function(code.split('#else\n', 1)[0],
            'static int lsf_prepaid_device_scm_passec(')
        self.assertIn('if (test_bit(SOCK_PASSSEC, &sock->flags))', passec)
        self.assertIn('put_cmsg(msg, SOL_SOCKET, SCM_SECURITY, seclen, secdata);', passec)
        self.assertLess(passec.index('lsf_prepaid_device_security_secctx(source'),
            passec.index('lsf_prepaid_device_security_release_secctx(source'))
        self.assertIn('else if (err == -EOPNOTSUPP)', passec)

    def test_label_hook_pair_preflight_and_same_owner_finish_prevent_unowned_context_free(self):
        code = delivery.private_security_secctx()
        self.assertIn('gets == 1 && releases == 1', code)
        self.assertLess(code.index('lsm_for_each_hook(scall, release_secctx)'),
            code.index('int lsf_prepaid_device_security_secctx('))
        self.assertIn('lsf_factory_device_recipient_blob(source, &owner) != 1', code)
        self.assertIn('lsf_prepaid_device_security_secctx_hooks()', code)
        private = delivery.private_selinux_secctx(self.inputs)
        self.assertIn('lsf_prepaid_security_sid_to_context(secid, secdata, seclen, 0, source)', private)
        self.assertNotIn('kfree(secdata)', private)
        release = delivery.prior.prior.function(private, 'int lsf_prepaid_device_selinux_release_secctx(')
        self.assertLess(release.index('lsf_factory_blob_same_owner(*source, birth)'),
            release.index('lsf_prepaid_audit_string_return(secdata)'))
        self.assertLess(release.index('lsf_factory_device_recipient_current(source->device, NULL)'),
            release.index('lsf_factory_blob_lookup(secdata'))


if __name__ == '__main__':
    unittest.main()
