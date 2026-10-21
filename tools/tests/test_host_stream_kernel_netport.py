"""Actual maintained cache path and original-owner deferred retirement."""
import hashlib
import re
import unittest

from tools import host_stream_kernel_netport as netport
from tools import host_stream_kernel_protocol as protocol
from tools import host_stream_kernel_maintained as maintained


class KernelNetport(unittest.TestCase):
    def setUp(self):
        self.fixture = netport.fixture()

    def original(self, name):
        return self.fixture['sections'][name]['text']

    def owned(self, name):
        return (protocol.OWNED/name).read_text()

    def test_fifteen_whole_preimages_and_nine_definitions_bind_maintained_archive(self):
        self.assertEqual(len(self.fixture['source']), 15)
        self.assertEqual(sum(row['bytes'] for row in self.fixture['source'].values()), 1074083)
        self.assertEqual(self.fixture['upstreamCommit'], maintained.COMMIT)
        self.assertEqual(len(self.fixture['sections']), 9)
        self.assertFalse(self.fixture['source'][netport.PORT]['independentlyGitCorroborated'])
        for name, row in self.fixture['sections'].items():
            self.assertEqual(netport.section(row['text'], name), row['text'])
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(), row['sha256'])
            self.assertIs(row['allocationClosureProven'], False)

    def test_unknown_duplicate_crlf_and_changed_definitions_or_whole_membership_refuse(self):
        with self.assertRaises(ValueError): netport.authenticate({})
        with self.assertRaises(ValueError): netport.section('', 'unknown')
        for name in netport.NAMES:
            raw = self.original(name)
            for bad in (raw+raw, raw.replace('\n', '\r\n'), raw.replace('\n{\n', '\n{\n;\n')):
                with self.subTest(name=name), self.assertRaises(ValueError): netport.section(bad, name)

    def test_old_optional_heap_cache_allocation_becomes_original_child_or_closed_error(self):
        raw = self.original('sel_netport_sid_slow')
        new = netport.private(raw, 'sel_netport_sid_slow')
        self.assertIn('new = kzalloc(sizeof(*new), GFP_ATOMIC);', raw)
        self.assertNotIn('kzalloc(', new)
        self.assertIn('lsf_factory_child_allocate(*source, sizeof(*new), LSF_PREPAID_NETPORT)', new)
        self.assertLess(new.index('if (!new)'), new.index('new->psec.port'))
        self.assertIn('ret = -ENOMEM;', new)
        self.assertIn('ret = security_port_sid(protocol, pnum, sid);', new)
        self.assertEqual(raw[raw.index('out:'):], new[new.index('out:'):])

    def test_actual_keys_policy_locks_and_original_sixteen_entry_eviction_remain(self):
        raw = self.original('sel_netport_insert')
        new = netport.private(raw, 'sel_netport_insert')
        for token in ('sel_netport_hashfn(port->psec.port)', 'SEL_NETPORT_HASH_BKT_LIMIT',
                      'list_tail_rcu(', 'list_del_rcu(&tail->list)', 'sel_netport_hash[idx].size++'):
            self.assertIn(token, new)
        self.assertLess(new.index('lsf_factory_netport_publish(port, idx)'), new.index('list_add_rcu('))
        slow = netport.private(self.original('sel_netport_sid_slow'), 'sel_netport_sid_slow')
        self.assertEqual(slow.count('spin_lock_bh(&sel_netport_lock)'), 1)
        self.assertEqual(slow.count('spin_unlock_bh(&sel_netport_lock)'), 2)
        self.assertIn('port = sel_netport_find(protocol, pnum);', slow)

    def test_normal_free_and_connect_remainders_are_preserved_under_explicit_owned_branches(self):
        for name in ('sel_netport_insert', 'sel_netport_flush'):
            raw = self.original(name)
            new = netport.observed(raw, name)
            stripped = re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', new, flags=re.S)
            self.assertEqual(re.sub(r'^\t+', '', stripped, flags=re.M),
                             re.sub(r'^\t+', '', raw, flags=re.M))
            self.assertIn('kfree_rcu(', new)
        raw = self.original('selinux_socket_connect_helper')
        new = netport.observed(raw, 'selinux_socket_connect_helper')
        stripped = re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', new, flags=re.S)
        self.assertEqual(re.sub(r'^\t+', '', stripped, flags=re.M),
                         re.sub(r'^\t+', '', raw, flags=re.M))
        for token in ('sock_has_perm(sk, SOCKET__CONNECT)', 'avc_has_perm(sksec->sid, sid,',
                      'ad.u.net->dport = htons(snum)', 'return -EAFNOSUPPORT'):
            self.assertIn(token, new)
        self.assertLess(new.index('if (owned < 0)'), new.index('if (owned)'))

    def test_shared_cache_reads_do_not_adopt_another_context_or_change_policy_results(self):
        new = netport.private(self.original('sel_netport_sid'), 'sel_netport_sid')
        self.assertIn('if (!source)', new)
        self.assertIn('return -EOPNOTSUPP;', new)
        self.assertIn('*sid = port->psec.sid;', new)
        self.assertIn('rcu_read_lock()', new)
        self.assertNotIn('lsf_factory_child_allocate', new)
        self.assertNotIn('source->context =', new)

    def test_existing_fixed_record_carries_bucket_before_publication_and_no_extra_table(self):
        source = self.owned('prepaid.h')
        self.assertIn('records[LSF_ALLOCATION_SLOTS]', source)
        self.assertIn('LSF_BACKING_BYTES 524288u', source)
        self.assertIn('LSF_BOOTSTRAP_CEILING 1048576u', source)
        selected = source[source.index('static inline int lsf_prepaid_netport_publish'):source.index('static inline int lsf_prepaid_netport_candidate')]
        for token in ('record->owner_generation != key.generation', 'record->generation != ticket.generation',
                      'record->deferred != LSF_PREPAID_PRIVATE', 'bucket >= 256u'):
            self.assertIn(token, selected)
        self.assertLess(selected.index('record->cache_bucket = bucket + 1u'), selected.index('record->deferred = LSF_PREPAID_PUBLISHED'))
        self.assertIn('sizeof(factory) + LSF_BACKING_BYTES < LSF_BOOTSTRAP_CEILING', self.owned('factory.c'))

    def test_drain_snapshots_pool_then_revalidates_under_cache_lock_before_dereferencing(self):
        source = self.owned('netport-private.c')
        drain = source[source.index('void lsf_prepaid_netport_drain'):]
        self.assertIn('slot < LSF_ALLOCATION_SLOTS', drain)
        self.assertLess(drain.index('lsf_factory_netport_candidate('), drain.index('spin_lock_bh('))
        self.assertLess(drain.index('spin_lock_bh('), drain.index('lsf_factory_netport_current('))
        self.assertLess(drain.index('lsf_factory_netport_current('), drain.index('struct sel_netport *port = address'))
        self.assertNotIn('list_for_each', drain)
        self.assertNotIn('synchronize_rcu', drain)
        factory = self.owned('factory.c')
        release = factory[factory.index('static int lsf_factory_release'):factory.index('static const struct file_operations')]
        self.assertLess(release.index('factory.pool.stopped = 1'), release.index('lsf_prepaid_netport_drain('))
        self.assertLess(release.index('spin_unlock_irqrestore'), release.index('lsf_prepaid_netport_drain('))

    def test_actual_callback_returns_only_queued_original_birth_without_post_return_reads(self):
        source = self.owned('netport-private.c')
        callback = source[source.index('static void lsf_prepaid_netport_callback'):source.index('static bool lsf_prepaid_netport_retire')]
        self.assertIn('lsf_factory_blob_lookup(port, LSF_PREPAID_NETPORT, &original)', callback)
        self.assertIn('lsf_factory_blob_finish(original, LSF_PREPAID_NETPORT)', callback)
        self.assertNotIn('port->', callback)
        retire = source[source.index('static bool lsf_prepaid_netport_retire'):source.index('void lsf_prepaid_netport_drain')]
        self.assertLess(retire.index('lsf_factory_netport_queue('), retire.index('call_rcu('))
        self.assertIn('if (owned == 0)\n        return false;', retire)
        self.assertIn('return true;', retire)

    def test_raw_policy_sid_and_mandatory_avc_audit_are_explicit_remaining_real_allocators(self):
        self.assertIn('sidtab_context_to_sid(sidtab, &c->context[index], &sid)', self.original('ocontext_to_sid'))
        self.assertIn('rc = ocontext_to_sid(sidtab, c, 0, out_sid)', self.original('security_port_sid'))
        self.assertIn('avc_has_perm(sksec->sid, sid, sksec->sclass, perm, &ad)', self.original('selinux_socket_connect_helper'))
        self.assertIn('return NULL;', self.owned('factory-private.h'))
        for field in ('kernelBuilt', 'actualLsmExecuted', 'completeAllocationClosure', 'productionInstallation'):
            self.assertIs(self.fixture[field], False)

    def test_reference_selects_ten_real_factory_functions_and_actual_upstream_cache_bodies(self):
        body = netport.reference_body().decode()
        for token in ('static struct lsf_factory_context *lsf_factory_context_current(',
                      'int lsf_factory_netport_current(', 'int lsf_factory_netport_publish(',
                      'static struct sel_netport *sel_netport_find('):
            self.assertEqual(body.count(token), 1)
        self.assertIn(self.original('sel_netport_sid_slow'), body)
        self.assertIn('#ifdef LSF_OLD_NETPORT', body)
        self.assertIn('lsf_prepaid_netport_drain(', body)


if __name__ == '__main__':
    unittest.main()
