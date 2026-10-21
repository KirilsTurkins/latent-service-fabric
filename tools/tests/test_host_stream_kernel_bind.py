"""Maintained bind source closure, exact normal paths and conservative returns."""
import hashlib
import re
import unittest
from tools import host_stream_kernel_bind as bind


class KernelBind(unittest.TestCase):
    def setUp(self):self.fixture = bind.fixture()

    def original(self, name):return self.fixture['sections'][name]['text']

    def owned(self, name):return (bind.OWNED/name).read_text()

    def test_twenty_seven_complete_sources_and_twelve_definitions_are_exact(self):
        self.assertEqual(len(self.fixture['source']),27)
        self.assertEqual(sum(row['bytes'] for row in self.fixture['source'].values()),1724745)
        self.assertEqual(len(self.fixture['sections']),12)
        for name,row in self.fixture['sections'].items():
            self.assertEqual(bind.section(row['text'],name),row['text'])
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(),row['sha256'])
        for name,row in bind.audit.fixture()['source'].items():self.assertEqual(self.fixture['source'][name],row)

    def test_definition_edits_duplicates_crlf_and_unknown_names_refuse(self):
        with self.assertRaises(ValueError):bind.authenticate({})
        with self.assertRaises(ValueError):bind.section('', 'unknown')
        for name,row in self.fixture['sections'].items():
            raw=row['text']
            for bad in (raw+raw,raw.replace('\n','\r\n'),raw.replace('\n{\n','\n{\n;\n')):
                with self.subTest(name=name),self.assertRaises(ValueError):bind.section(bad,name)

    def test_every_original_normal_function_body_is_recovered_exactly(self):
        for name in bind.OBSERVED:
            original=self.original(name);selected=bind.observed(original,name)
            def normal(match):
                middle=match.group(1)
                return middle.split('#else\n',1)[1] if '#else\n' in middle else ''
            projected=re.sub(r'#ifdef LSF_STREAM_BIND_SOURCE\n(.*?)#endif\n',normal,selected,flags=re.S)
            self.assertEqual(projected,original,name)

    def test_original_bind_initializer_is_exact_except_prepaid_birth(self):
        original=self.original('inet_bind_bucket_create');selected=bind.private(original)
        self.assertNotIn('kmem_cache_alloc(',selected)
        self.assertIn('sizeof(struct inet_bind_bucket), LSF_PREPAID_BIND_BUCKET',selected)
        for text in ('write_pnet(&tb->ib_net, net)','tb->l3mdev    = l3mdev',
            'tb->fastreuse = 0','tb->fastreuseport = 0','INIT_HLIST_HEAD(&tb->bhash2)',
            'hlist_add_head(&tb->node, &head->chain)'):
            self.assertIn(text,selected)
        self.assertLess(selected.index('lsf_factory_child_allocate('),selected.index('hlist_add_head('))

    def test_all_owned_connect_and_get_port_misses_use_real_socket(self):
        for name in ('__inet_hash_connect','inet_csk_get_port'):
            selected=bind.observed(self.original(name),name)
            self.assertLess(selected.index('lsf_prepaid_bind_check(sk)'),selected.index('spin_lock'))
            self.assertIn('lsf_prepaid_bind_bucket_create(hinfo->bind_bucket_cachep,',selected)
            self.assertIn('net, head, port, l3mdev, sk)',selected)
            self.assertIn('inet_bind2_bucket_create(',selected)

    def test_real_port_authority_reuse_conflict_randomness_and_reschedule_are_preserved(self):
        selected=bind.observed(self.original('__inet_hash_connect'),'__inet_hash_connect')
        for token in ('inet_sk_get_local_port_range','inet_is_local_reserved_port',
            'get_random_sleepable_once(table_perturb','get_random_u32_below(8)',
            'check_established(death_row, sk','tb->fastreuse >= 0',
            'tb->fastreuseport >= 0','cond_resched()', 'inet_twsk_deschedule_put(tw)'):
            self.assertIn(token,selected)
        self.assertNotIn('lsf_prepaid_bind_bucket_create(',selected[:selected.index('inet_bind_bucket_for_each(')])

    def test_shared_bind2_constructor_and_saddr_preallocation_use_same_exact_producer(self):
        create=bind.observed(self.original('inet_bind2_bucket_create'),'inet_bind2_bucket_create')
        update=bind.observed(self.original('__inet_bhash2_update_saddr'),'__inet_bhash2_update_saddr')
        self.assertIn('lsf_prepaid_bind2_allocate(cachep, net, sk)',create)
        self.assertIn('lsf_prepaid_bind2_allocate(hinfo->bind2_bucket_cachep, net, sk)',update)
        self.assertLess(update.index('lsf_prepaid_bind2_allocate('),update.index('spin_lock_bh('))
        self.assertLess(update.index('tb2 != new_tb2 &&'),update.index('lsf_prepaid_bind_return(new_tb2,'))
        self.assertIn('inet_bind2_bucket_init(tb2, net, head2, inet_csk(sk)->icsk_bind_hash, sk)',update)

    def test_actual_empty_list_unlinks_precede_private_return_even_when_poisoned(self):
        for name,empty in (('inet_bind_bucket_destroy','tb->bhash2'),('inet_bind2_bucket_destroy','tb->owners')):
            selected=bind.observed(self.original(name),name)
            self.assertLess(selected.index('hlist_empty(&'+empty+')'),selected.index('lsf_prepaid_bind_return('))
            self.assertLess(selected.rindex('__hlist_del('),selected.index('lsf_prepaid_bind_return('))
            self.assertLess(selected.index('lsf_prepaid_bind_return('),selected.index('kmem_cache_free('))
            self.assertNotIn('if (owned >= 0)',selected)

    def test_socket_and_timewait_original_put_paths_keep_both_real_locks_and_destroy_calls(self):
        put=self.original('__inet_put_port');tw=self.original('inet_twsk_kill')
        for selected in (put,tw):
            self.assertIn('spin_lock(&head',selected.replace('bhead','head'))
        self.assertLess(put.index('spin_lock(&head->lock)'),put.index('spin_lock(&head2->lock)'))
        self.assertLess(put.index('inet_bind2_bucket_destroy('),put.index('spin_unlock(&head2->lock)'))
        self.assertLess(put.index('inet_bind_bucket_destroy('),put.index('spin_unlock(&head->lock)'))
        unhash=self.original('inet_twsk_bind_unhash')
        for token in ('__sk_del_bind_node','tw->tw_tb = NULL','tw->tw_tb2 = NULL',
            'inet_bind2_bucket_destroy(', 'inet_bind_bucket_destroy(', '__sock_put'):
            self.assertIn(token,unhash)

    def test_inherited_listener_participants_are_explicitly_unsupported_before_lookup(self):
        selected=bind.observed(self.original('__inet_inherit_port'),'__inet_inherit_port')
        for token in ('lsf_prepaid_bind_owned(sk) != 0','lsf_prepaid_bind_owned(child) != 0','return -EOPNOTSUPP;'):
            self.assertIn(token,selected)
        self.assertLess(selected.index('lsf_prepaid_bind_owned(sk)'),selected.index('spin_lock('))
        self.assertIn('inet_csk_update_fastreuse(tb, child)',selected)

    def test_source_is_actual_prior_socket_record_not_current_task_or_late_registration(self):
        source=self.owned('bind-private.c')
        for token in ('lsf_prepaid_netlabel_source((struct sock *)sk, source)',
            'sk->sk_family != AF_INET','sk->sk_protocol != IPPROTO_TCP','sk->sk_prot != &tcp_prot',
            'cachep != tcp_or_dccp_get_hashinfo(sk)->bind_bucket_cachep',
            'cachep != tcp_or_dccp_get_hashinfo(sk)->bind2_bucket_cachep','net != sock_net(sk)'):
            self.assertIn(token,source)
        for token in ('current->','register_owner','EXPORT_SYMBOL','alloc_pages','kmalloc('):self.assertNotIn(token,source)

    def test_no_normal_heap_fallback_after_owned_refusal_or_exhaustion(self):
        source=self.owned('bind-private.c')
        for name in ('lsf_prepaid_bind_bucket_create','lsf_prepaid_bind2_allocate'):
            start=source.index(name+'(');end=source.index('\n}\n',start)+3;body=source[start:end]
            self.assertIn('if (owned == 0)',body)
            self.assertIn('if (owned < 0)\n        return NULL;',body)
            self.assertNotIn('GFP_KERNEL',body)
        self.assertIn('return lsf_factory_child_allocate(source, sizeof(struct inet_bind2_bucket)',source)

    def test_unknown_or_duplicate_arena_return_never_reaches_normal_free_or_reads_pointer(self):
        source=self.owned('bind-private.c');body=source[source.index('bool lsf_prepaid_bind_return('):]
        self.assertIn('lsf_factory_blob_lookup(address, kind, &copy)',body)
        self.assertIn('if (owned == 0)\n        return false;',body)
        self.assertIn('return true;',body)
        self.assertNotIn('address->',body)
        self.assertNotIn('kmem_cache_free',body)
        self.assertLess(body.index('lsf_factory_blob_finish('),body.rindex('return true;'))

    def test_original_fixed_slots_byte_caps_and_backing_retirement_gate_remain(self):
        source=self.owned('prepaid.h')
        self.assertIn('#define LSF_BACKING_BYTES 524288u',source)
        self.assertIn('LSF_PREPAID_BIND_BUCKET || kind == LSF_PREPAID_BIND2_BUCKET',source)
        self.assertEqual(source.count('!lsf_prepaid_bind_kind(kind)'),3)
        self.assertIn('context->closed || context->live || context->continuations',source)
        self.assertIn('record->phase != LSF_PREPAID_RETURNED',source)
        self.assertIn('return NULL;',self.owned('factory-private.h'))


if __name__ == '__main__':unittest.main()
