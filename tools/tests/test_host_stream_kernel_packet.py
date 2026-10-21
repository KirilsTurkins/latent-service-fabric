"""Draft maintained linear packet/source boundaries; no kernel execution."""
from pathlib import Path
import unittest
from tools import host_stream_kernel_packet as packet
from tools import host_stream_kernel_audit_skb as audit


class KernelLinearPacketSource(unittest.TestCase):
    def owned(self, name):
        return (packet.OWNED/name).read_text()

    def test_exact_parent_sources_and_primary_new_source_provenance(self):
        before = packet.prior.fixture()['source']
        value = packet.fixture()
        self.assertEqual(len(value['source']), 49)
        self.assertEqual(len(value['sections']), 22)
        self.assertEqual({name:row for name,row in value['source'].items() if name in before}, before)
        self.assertEqual(set(value['source'])-set(before), {
            'net/ipv4/tcp.c','include/net/tcp.h',
            'net/ipv4/tcp_output.c','net/ipv4/tcp_input.c'})
        maintained = packet.prior.route.bind.avc.maintained.manifest()['source']
        for name in set(value['source'])-set(before):
            self.assertTrue(value['source'][name]['independentlyGitCorroborated'])
            for key in ('bytes','sha256','gitBlob'):
                self.assertEqual(value['source'][name][key], maintained[name][key])
        self.assertTrue(all(value[name] is False for name in ('kernelBuilt',
            'actualPacketExchangeExecuted','actualLinuxRcuExecuted','completeAllocationClosure',
            'finalFreeCertified','productionInstallation')))

    def test_changed_duplicate_crlf_and_missing_whole_source_refuse(self):
        with self.assertRaises(ValueError):packet.authenticate({})
        for name,row in packet.fixture()['sections'].items():
            raw = row['text']
            self.assertEqual(packet.section(raw,name),raw)
            for changed in (raw+raw,raw.replace('\n','\r\n'),raw.replace('\n{\n','\n{\n;\n',1)):
                with self.subTest(name=name),self.assertRaises(ValueError):
                    packet.section(changed,name)

    def test_allocating_send_alternatives_refuse_before_original_calls(self):
        raw = packet.fixture()['sections']['tcp_sendmsg_locked']['text']
        selected = packet.private(raw,'tcp_sendmsg_locked')
        guard = selected.index('if (!sk->sk_lsf_factory || msg->msg_controllen || msg->msg_ubuf ||')
        refusal = selected.index('return -EOPNOTSUPP;',guard)
        self.assertLess(refusal,selected.index('msg_zerocopy_realloc('))
        self.assertLess(refusal,selected.index('tcp_sendmsg_fastopen('))
        self.assertIn('(flags & ~(MSG_DONTWAIT | MSG_NOSIGNAL | MSG_MORE | MSG_EOR))',selected)
        self.assertIn('inet_test_bit(DEFER_CONNECT, sk) || tp->repair || tcp_passive_fastopen(sk)',selected)
        self.assertEqual(selected.count('size_goal != mss_now'),2)
        self.assertEqual(selected.count('mss_now > (int)LSF_PACKET_LINEAR_BYTES'),2)
        with self.assertRaises(ValueError):packet.private(raw+'\n','tcp_sendmsg_locked')

    def test_copied_payload_uses_real_linear_copy_and_original_accounting_tail(self):
        raw = packet.fixture()['sections']['tcp_sendmsg_locked']['text']
        selected = packet.private(raw,'tcp_sendmsg_locked')
        start = selected.index('\t\tif (zc == 0) {')
        end = selected.index('\t\t} else if (zc == MSG_ZEROCOPY)',start)
        copied = selected[start:end]
        for forbidden in ('sk_page_frag','page_ref_inc','sk_mem_charge','sk_wmem_queued_add','alloc_pages'):
            self.assertNotIn(forbidden,copied)
        self.assertIn('skb_add_data_nocache(sk, skb, &msg->msg_iter, copy)',copied)
        self.assertLess(copied.index('lsf_prepaid_packet_linear('),copied.index('skb_add_data_nocache('))
        # Original TCP sequence, partial-prefix, push, error and wait tail remains.
        self.assertEqual(selected.split('\t\t} else if (zc == MSG_ZEROCOPY)',1)[1].replace(
            '\t\tif (mss_now <= 0 || size_goal != mss_now ||\n'
            '\t\t    mss_now > (int)LSF_PACKET_LINEAR_BYTES) {\n'
            '\t\t\terr = -EOPNOTSUPP;\n\t\t\tgoto do_error;\n\t\t}\n',''),
            raw.split('\t\t} else if (zc == MSG_ZEROCOPY)',1)[1])
        entail = packet.fixture()['sections']['tcp_skb_entail']['text']
        self.assertIn('sk_wmem_queued_add(sk, skb->truesize);',entail)
        self.assertIn('sk_mem_charge(sk, skb->truesize);',entail)

    def test_full_head_and_header_before_publication_and_no_generic_fallback(self):
        source = self.owned('packet-skb-private.c')
        constructor = source[source.index('struct sk_buff *lsf_prepaid_packet_skb_new('):
            source.index('bool lsf_prepaid_packet_linear(')]
        self.assertLess(constructor.index('lsf_factory_child_allocate('),constructor.index('__build_skb_around('))
        self.assertLess(constructor.index('lsf_prepaid_packet_head('),constructor.index('__build_skb_around('))
        for forbidden in ('kmalloc(', 'alloc_pages(', 'alloc_page(', '__alloc_skb('):
            self.assertNotIn(forbidden,source)
        linear = source[source.index('bool lsf_prepaid_packet_linear('):source.index('static struct sk_buff *lsf_prepaid_packet_clone(')]
        self.assertLess(linear.index('lsf_factory_packet_head_current('),linear.index('skb_shinfo(skb)->nr_frags'))
        self.assertIn('skb->data_len',linear);self.assertIn('skb->head_frag',linear)
        self.assertIn('skb_zcopy((struct sk_buff *)skb)',linear)

    def test_audit_and_normal_dispatchers_remain_distinct_from_packet(self):
        for name in audit.NAMES-{'__skb_clone'}:
            original = audit.fixture()['sections'][name]['text']
            old = audit.routed(original,name)
            selected = packet.packet_routing(old,name)
            self.assertIn('lsf_prepaid_audit_',selected)
            self.assertIn('lsf_prepaid_packet_',selected)
            self.assertEqual(selected.count('kmem_cache_free('),old.count('kmem_cache_free('))
            self.assertEqual(selected.count('__alloc_skb('),old.count('__alloc_skb('))
        clone = packet.packet_routing(audit.routed(audit.fixture()['sections']['skb_clone']['text'],'skb_clone'),'skb_clone')
        self.assertLess(clone.index('if (packet_owned)'),clone.index('lsf_factory_blob_lookup(skb, LSF_PREPAID_AUDIT_SKB'))
        self.assertIn('packet_owned < 0 ? NULL : lsf_prepaid_packet_clone',clone)

    def test_prior_birth_generation_and_closed_kind_routes_precede_any_use(self):
        source = self.owned('packet-factory.c')
        self.assertLess(source.index('value - base >= LSF_BACKING_BYTES'),source.index('factory.pool.records[i]'))
        self.assertIn('record->phase != LSF_PREPAID_LIVE',source)
        self.assertIn('factory.contexts[key.slot].key.generation != key.generation',source)
        self.assertIn('else if (kind == LSF_PREPAID_PACKET_HEAD)',source)
        self.assertIn('record->kind == audit_kind',source)
        self.assertIn('factory.pool.poisoned = 1;',source)
        self.assertIn('WRITE_ONCE(factory.uncertain, 1);',source)
        self.assertNotIn('lsf_prepaid_context_create(',source)
        self.assertNotIn('lsf_prepaid_allocate(',source)
        self.assertIn('return NULL;',self.owned('factory-private.h'))

    def test_control_packets_reserve_under_actual_sock_before_original_constructor(self):
        import re
        for name in packet.CONTROL_ALLOCATORS:
            raw = packet.fixture()['sections'][name]['text']
            selected = packet.control(raw,name)
            self.assertIn('if (sk->sk_lsf_factory)',selected)
            self.assertEqual(selected.count('lsf_prepaid_packet_alloc_sock(sk,'),1)
            self.assertLess(selected.index('lsf_prepaid_packet_alloc_sock('),
                selected.index('alloc_skb'))
            # Remove only the reviewed selector. Every original statement,
            # constructor size/flags and control/sequence/error tail stays exact.
            guards = re.findall(r'#ifdef LSF_STREAM_PACKET_SOURCE\n.*?#endif\n',selected,re.S)
            self.assertEqual(len(guards),5 if name=='tcp_collapse' else 1)
            self.assertEqual(re.sub(r'#ifdef LSF_STREAM_PACKET_SOURCE\n.*?#endif\n','',selected,flags=re.S),raw)
            with self.assertRaises(ValueError):packet.control(raw+'\n',name)

    def test_private_passive_fastopen_repair_and_receive_injection_refuse_first(self):
        for name in ('inet_listen','tcp_make_synack','tcp_send_syn_data','tcp_send_rcvq','tcp_connect'):
            raw = packet.fixture()['sections'][name]['text']
            selected = packet.unsupported_entry(raw,name)
            self.assertTrue(selected.endswith('#else\n'+raw+'#endif\n'))
            selected_body = selected.split('#else\n',1)[0]
            self.assertLess(selected_body.index('return '),selected_body.index('\t{\n'))
            self.assertTrue(selected_body.endswith(raw.split('\n{\n',1)[1]+'}\n'))
            if name == 'tcp_connect':
                for required in ('tcp_sk(sk)->fastopen_req','DEFER_CONNECT','tcp_sk(sk)->repair'):
                    self.assertIn(required,selected_body)
                self.assertIn('return -EOPNOTSUPP;',selected_body)
            with self.assertRaises(ValueError):packet.unsupported_entry(raw+'\n',name)

    def test_retransmit_copy_proves_linear_origin_and_checked_extent_before_new_birth(self):
        for name in packet.COPIES:
            raw=packet.fixture()['sections'][name]['text']
            selected=packet.copy_private(raw,name)
            self.assertNotIn('__alloc_skb(',selected)
            self.assertLess(selected.index('lsf_prepaid_packet_linear(skb, birth)'),
                selected.index('lsf_prepaid_packet_skb_new('))
            self.assertLess(selected.index('if (requested > LSF_TCP_BYTES)'),
                selected.index('lsf_prepaid_packet_skb_new('))
            self.assertIn('unsigned long requested;',selected)
            self.assertIn('skb_copy_header(n, skb);',selected)
            if name=='__pskb_copy_fclone':
                self.assertIn('headroom < 0',selected)
                self.assertEqual(selected.split('\tif (!n)\n',1)[1],
                    raw.split('\tif (!n)\n',1)[1])
            else:
                self.assertIn('newheadroom < 0 || newtailroom < 0',selected)
                self.assertEqual(selected.split('\tif (!n)\n',1)[1],
                    raw.split('\tif (!n)\n',1)[1])
            with self.assertRaises(ValueError):packet.copy_private(raw+'\n',name)

    def test_copy_dispatch_has_exact_normal_definition_and_no_stale_birth_fallback(self):
        for name in packet.COPIES:
            raw=packet.fixture()['sections'][name]['text']
            selected=packet.copy_routing(raw,name)
            self.assertTrue(selected.endswith('#else\n'+raw+'#endif\n'))
            active=selected.split('#else\n',1)[0]
            self.assertIn('return owned < 0 ? NULL : lsf_prepaid_'+name+'(',active)
            self.assertLess(active.index('lsf_factory_packet_birth('),active.index('\t{\n'))
            self.assertTrue(active.endswith(raw.split('\n{\n',1)[1]+'}\n'))
            with self.assertRaises(ValueError):packet.copy_routing(raw+'\n',name)

    def test_collapse_refuses_unknown_and_foreign_packet_before_lookup_or_copy(self):
        raw=packet.fixture()['sections']['tcp_collapse']['text']
        selected=packet.control(raw,'tcp_collapse')
        self.assertLess(selected.index('!lsf_prepaid_packet_for_sock(skb, sk)'),
            selected.index('n = tcp_skb_next(skb, list);'))
        self.assertLess(selected.index('!lsf_prepaid_packet_for_sock(n, sk)'),
            selected.index('skb_frags_readable(n)'))
        before,after=selected.split('__skb_queue_head_init(&tmp);',1)
        self.assertNotIn('goto end;',before)
        self.assertIn('!lsf_prepaid_packet_for_sock(skb, sk))\n\t\t\t\t\tgoto end;',after)
        source=self.owned('packet-skb-private.c')
        owned=source[source.index('bool lsf_prepaid_packet_for_sock('):source.index('static struct sk_buff *lsf_prepaid_packet_clone(')]
        self.assertLess(owned.index('lsf_factory_protocol_parent('),owned.index('lsf_factory_packet_birth('))
        self.assertLess(owned.index('source.context != parent.context'),owned.index('lsf_prepaid_packet_linear('))
        self.assertIn('lsf_factory_poison(parent.context);',owned)
        self.assertNotIn('allocate(',owned)


if __name__ == '__main__':unittest.main()
