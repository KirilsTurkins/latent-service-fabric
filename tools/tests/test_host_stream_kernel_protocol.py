"""Maintained constructor/error/LSM lifetime derivation, without a kernel build."""
import hashlib
import json
import unittest

from tools import host_stream_kernel_protocol as protocol
from tools import host_stream_kernel_maintained as maintained


class KernelProtocol(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(protocol.FIXTURE.read_bytes())

    def original(self, name):
        return self.fixture['sections'][name]['text']

    def owned(self, name):
        return (protocol.OWNED / name).read_text()

    def test_six_whole_sources_and_all_twenty_one_definitions_bind_maintained_commit(self):
        value = maintained.manifest()
        self.assertEqual(self.fixture['upstreamCommit'], maintained.COMMIT)
        self.assertEqual(self.fixture['source'], {name: value['source'][name] for name in protocol.SOURCES})
        self.assertEqual(sum(row['bytes'] for row in self.fixture['source'].values()), 597298)
        self.assertEqual(len(self.fixture['sections']), 21)
        for name, row in self.fixture['sections'].items():
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(), row['sha256'])
            self.assertEqual(protocol.section(row['text'], name), row['text'])
            self.assertIs(row['allocationClosureProven'], False)

    def test_unknown_full_or_partial_sources_duplicate_or_line_ending_drift_refuse(self):
        with self.assertRaises(ValueError):
            protocol.derive({})
        for name in protocol.SECTIONS:
            raw = self.original(name)
            for changed in (raw + raw, raw.replace('\n', '\r\n'), raw.replace('\n{\n', '\n{\n;\n')):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    protocol.section(changed, name)

    def test_actual_original_lsm_allocator_is_a_general_allocation_counterexample(self):
        raw = self.original('lsm_inode_alloc')
        self.assertIn('kmem_cache_zalloc(lsm_inode_cache, gfp)', raw)
        self.assertNotIn('lsf_factory', raw)
        private = self.owned('security-private.c')
        for kind in ('LSF_PREPAID_INODE_BLOB', 'LSF_PREPAID_SOCK_BLOB'):
            self.assertIn(kind, private)
        self.assertNotIn('kmem_cache_zalloc(', private)
        self.assertNotIn('kzalloc(', private)
        self.assertIn('gfp != GFP_NOFS', private)

    def test_private_security_allocators_preserve_original_hook_and_error_bodies_exactly(self):
        for name, allocation in (('security_inode_alloc', 'lsm_inode_alloc(inode, gfp)'),
                                 ('security_sk_alloc', 'lsm_sock_alloc(sk, priority)')):
            raw = self.original(name)
            derived = protocol.private(raw, name)
            self.assertEqual(raw[raw.index('\n\tif (unlikely(rc))'):], derived[derived.index('\n\tif (unlikely(rc))'):])
            self.assertNotIn('= ' + allocation, derived)
        self.assertIn('security_inode_free(inode)', protocol.private(self.original('security_inode_alloc'), 'security_inode_alloc'))
        self.assertIn('security_sk_free(sk)', protocol.private(self.original('security_sk_alloc'), 'security_sk_alloc'))

    def test_private_inode_preserves_actual_initialization_and_original_nofs_priority(self):
        raw = self.original('inode_init_always_gfp')
        derived = protocol.private(raw, 'inode_init_always_gfp')
        self.assertEqual(raw[raw.index('\n{'):].replace('security_inode_alloc(inode, gfp)',
            'lsf_prepaid_security_inode_alloc(inode, gfp, context)'), derived[derived.index('\n{'):])
        alloc = protocol.private(self.original('alloc_inode'), 'alloc_inode')
        self.assertIn('lsf_prepaid_inode_init(sb, inode, GFP_NOFS, context)', alloc)
        self.assertIn('i_callback(&inode->i_rcu)', alloc)

    def test_private_protocol_preserves_security_module_and_failed_allocation_cleanup(self):
        derived = protocol.private(self.original('sk_prot_alloc'), 'sk_prot_alloc')
        self.assertIn('try_module_get(prot->owner)', derived)
        self.assertIn('out_free_sec:\n\tsecurity_sk_free(sk);', derived)
        self.assertIn('out_free:\n\tif (!lsf_prepaid_protocol_return(sk))', derived)
        self.assertNotIn('kmalloc(', derived)
        self.assertNotIn('kmem_cache_alloc(', derived)
        self.assertLess(derived.index('lsf_prepaid_protocol_allocate('), derived.index('lsf_prepaid_security_sk_alloc('))

    def test_current_passive_netns_memcg_cgroup_and_owner_cleanup_remain_original(self):
        raw = self.original('sk_alloc')
        derived = protocol.private(raw, 'sk_alloc')
        tail = raw[raw.index('\t\tif (likely(sk->sk_net_refcnt))'):]
        self.assertEqual(tail.replace('\t\tsk_tx_queue_clear(sk);',
            '\t\tsk_tx_queue_clear(sk);\n\t\tsock_set_flag(sk, SOCK_RCU_FREE);'), derived[derived.index('\t\tif (likely(sk->sk_net_refcnt))'):])
        for token in ('net_passive_inc(net)', 'mem_cgroup_sk_alloc(sk)', 'cgroup_sk_alloc(', 'sock_update_classid('):
            self.assertIn(token, derived)
        freed = protocol.observed(self.original('sk_prot_free'), 'sk_prot_free')
        self.assertLess(freed.index('sk_owner_put(sk)'), freed.index('lsf_prepaid_protocol_return(sk)'))
        self.assertLess(freed.index('owner = prot->owner'), freed.index('lsf_prepaid_protocol_return(sk)'))
        self.assertIn('module_put(owner)', freed)

    def test_private_inet_requires_real_static_tcp_family_and_keeps_full_error_tail(self):
        raw = self.original('inet_create')
        derived = protocol.private(raw, 'inet_create')
        for token in ('family != &inet_family_ops', 'answer->prot != &tcp_prot', 'answer->ops != &inet_stream_ops'):
            self.assertIn(token, derived)
        self.assertNotIn('request_module(', derived)
        self.assertEqual(raw[raw.index('\tif (!sk)'):], derived[derived.index('\tif (!sk)'):])
        created = protocol.private(self.original('__sock_create'), '__sock_create')
        self.assertLess(created.index('security_socket_create('), created.index('lsf_outer_sock_alloc('))
        self.assertLess(created.index('!lsf_prepaid_protocol_family(pf)'), created.index('try_module_get(pf->owner)'))
        self.assertNotIn('pf->create(', created)
        self.assertNotIn('request_module(', created)
        self.assertEqual(self.original('__sock_create')[self.original('__sock_create').index('\tif (err < 0)'):],
                         created[created.index('\tif (err < 0)'):])

    def test_blob_original_rcu_callback_copies_owner_before_hooks_and_returns_after_hooks(self):
        queued = protocol.observed(self.original('security_inode_free'), 'security_inode_free')
        self.assertLess(queued.index('call_void_hook(inode_free_security,'), queued.index('lsf_factory_blob_queue('))
        self.assertLess(queued.index('lsf_factory_blob_queue('), queued.index('call_rcu('))
        callback = protocol.observed(self.original('inode_free_by_rcu'), 'inode_free_by_rcu')
        self.assertLess(callback.index('lsf_factory_blob_lookup('), callback.index('call_void_hook(inode_free_security_rcu,'))
        self.assertLess(callback.index('call_void_hook(inode_free_security_rcu,'), callback.index('lsf_factory_blob_finish('))
        self.assertNotIn('struct inode *', callback)
        self.assertIn('kmem_cache_free(lsm_inode_cache, head)', callback)
        freed = protocol.observed(self.original('security_sk_free'), 'security_sk_free')
        self.assertLess(freed.index('call_void_hook(sk_free_security,'), freed.index('lsf_factory_blob_finish('))
        self.assertLess(freed.index('lsf_factory_blob_finish('), freed.index('sk->sk_security = NULL'))

    def test_fixed_birth_record_kind_and_deferred_owner_do_not_add_a_new_registration_table(self):
        raw = self.owned('prepaid.h')
        self.assertIn('records[LSF_ALLOCATION_SLOTS]', raw)
        self.assertIn('contexts[LSF_OWNER_SLOTS]', raw)
        self.assertIn('record->kind != LSF_PREPAID_OBJECT || record->deferred', raw)
        self.assertIn('record->deferred ||', raw)
        self.assertIn('context->continuations++', raw)
        self.assertIn('context->continuations--', raw)
        self.assertIn('record->owner_generation != key.generation', raw)
        self.assertIn('LSF_BACKING_BYTES 524288u', raw)

    def test_return_classification_never_reads_an_unproven_pointer_or_calls_a_fallback_allocator(self):
        raw = self.owned('factory.c')
        start = raw.index('static int lsf_factory_blob_lookup_locked(')
        end = raw.index('int lsf_factory_blob_lookup(', start)
        selected = raw[start:end]
        self.assertIn('value < base || value - base >= LSF_BACKING_BYTES', selected)
        self.assertIn('lsf_prepaid_blob_find(', selected)
        self.assertNotIn('->', selected[:selected.index('copy->context')])
        self.assertNotIn('container_of(', selected)
        self.assertNotIn('EXPORT_SYMBOL', raw)

    def test_complete_consumer_and_kernel_qualification_remain_unavailable(self):
        self.assertIn('return NULL;', self.owned('factory-private.h'))
        self.assertIn('lsm_for_each_hook(scall, socket_post_create) { return false; }', self.owned('outer-security.c'))
        for key in ('kernelBuilt', 'actualKernelExecuted', 'productionInstallation'):
            self.assertIs(self.fixture[key], False)
        self.assertNotIn('static_branch_disable', self.owned('security-private.c'))


if __name__ == '__main__':
    unittest.main()
