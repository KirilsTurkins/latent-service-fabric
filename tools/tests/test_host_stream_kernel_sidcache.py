"""Maintained SID-cache publication, string ownership and policy lifetime."""
import hashlib
import re
import unittest

from tools import host_stream_kernel_sidcache as sid
from tools import host_stream_kernel_netport as netport


class KernelSidcache(unittest.TestCase):
    def original(self, name):
        return sid.fixture()['sections'][name]['text']

    def owned(self, name):
        return (sid.protocol.OWNED/name).read_text()

    def test_six_real_definitions_and_sixteen_whole_inputs_bind_original_archive(self):
        value = sid.fixture()
        self.assertEqual((len(value['source']), len(value['sections'])), (16, 6))
        self.assertEqual(sum(row['bytes'] for row in value['source'].values()), 1088758)
        for name, row in netport.fixture()['source'].items():
            self.assertEqual(value['source'][name], row)
        self.assertFalse(value['source'][sid.SIDTAB]['independentlyGitCorroborated'])
        for name, row in value['sections'].items():
            self.assertEqual(sid.section(row['text'], name), row['text'])
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(), row['sha256'])

    def test_changed_duplicate_crlf_unknown_or_missing_inputs_refuse(self):
        with self.assertRaises(ValueError): sid.authenticate({})
        with self.assertRaises(ValueError): sid.section('', 'not-a-function')
        for name in sid.NAMES:
            raw = self.original(name)
            for bad in (raw+raw, raw.replace('\n', '\r\n'), raw.replace('\n{\n', '\n{\n;\n')):
                with self.subTest(name=name), self.assertRaises(ValueError): sid.section(bad, name)

    def test_real_cache_keys_and_original_lru_hit_preserve_creator_without_new_birth(self):
        body = sid.private(self.original('sidtab_sid2str_put'), 'sidtab_sid2str_put')
        hit = body[body.index('if (cache) {'):body.index('cache = lsf_factory_child_allocate')]
        self.assertIn('list_move(&cache->lru_member, &s->cache_lru_list)', hit)
        self.assertNotIn('source->', hit)
        self.assertNotIn('publish(', hit)
        self.assertIn('if (entry->context.len)\n\t\treturn 0;', body)

    def test_new_cache_birth_precedes_copy_publication_and_original_cache_limit(self):
        body = sid.private(self.original('sidtab_sid2str_put'), 'sidtab_sid2str_put')
        self.assertNotIn('kmalloc(', body)
        self.assertLess(body.index('lsf_factory_child_allocate'), body.index('memcpy(cache->str'))
        self.assertLess(body.index('memcpy(cache->str'), body.index('lsf_factory_sidcache_publish'))
        self.assertLess(body.index('lsf_factory_sidcache_publish'), body.index('list_add('))
        self.assertIn('if (s->cache_free_slots == 0)', body)
        self.assertIn('result = -ENOMEM;', body)
        self.assertIn('return result;', body)

    def test_both_normal_and_private_eviction_queue_under_original_lock_before_unlink(self):
        original = self.original('sidtab_sid2str_put')
        for body in (sid.observed(original, 'sidtab_sid2str_put'),
                     sid.private(original, 'sidtab_sid2str_put')):
            self.assertLess(body.index('spin_lock_irqsave('), body.index('lsf_factory_sidcache_queue(victim)'))
            self.assertLess(body.index('lsf_factory_sidcache_queue(victim)'), body.index('list_del(&victim'))
            self.assertLess(body.index('spin_unlock_irqrestore('), body.index('lsf_prepaid_sidcache_retire(victim'))
        normal = sid.observed(original, 'sidtab_sid2str_put')
        self.assertNotIn('return -', normal)
        self.assertIn('rcu_assign_pointer(victim->parent->cache, NULL)', normal)
        self.assertIn('cache = kmalloc(struct_size(cache, str, str_len), GFP_ATOMIC)', normal)
        self.assertIn('#else\n\tkfree_rcu(victim, rcu_member);', normal)

    def test_cache_hit_output_uses_callers_real_string_child_and_actual_lru_update(self):
        body = sid.private(self.original('sidtab_sid2str_get'), 'sidtab_sid2str_get')
        self.assertNotIn('kmemdup(', body)
        self.assertIn('lsf_prepaid_audit_dup(source, cache->str, cache->len)', body)
        self.assertIn('lsf_prepaid_sid2str_put(s, entry, *out, *out_len, source)', body)
        self.assertLess(body.index('rcu_read_unlock()'), body.index('lsf_prepaid_sid2str_put('))
        self.assertIn('lsf_prepaid_audit_string_return(*out);', body)
        self.assertIn('*out = NULL;', body)

    def test_context_conversion_preserves_original_mls_policy_and_sid_search_semantics(self):
        original = self.original('context_struct_to_string')
        body = sid.private(original, 'context_struct_to_string')
        self.assertNotRegex(body, r'\b(kmalloc|kstrdup|kmemdup)\(')
        for token in ('mls_compute_context_len(p, context)', 'mls_sid_to_context(p, context, &scontextp)',
                      'sym_name(p, SYM_USERS, context->user - 1)', '*scontextp = 0;'):
            self.assertIn(token, body)
        body = sid.private(self.original('security_sid_to_context_core'), 'security_sid_to_context_core')
        for token in ('sidtab_search_entry_force(sidtab, sid)', 'sidtab_search_entry(sidtab, sid)',
                      'policy = rcu_dereference(selinux_state.policy)',
                      'if (only_invalid && !entry->context.len)', 'sid = SECINITSID_KERNEL'):
            self.assertIn(token, body)
        self.assertNotIn('kmemdup(', body)

    def test_actual_policy_destroy_routes_published_birth_before_original_table_is_freed(self):
        body = sid.observed(self.original('sidtab_destroy_entry'), 'sidtab_destroy_entry')
        self.assertIn('context_destroy(&entry->context);', body)
        self.assertIn('if (!lsf_prepaid_sidcache_destroy(rcu_dereference_raw(entry->cache)))', body)
        self.assertIn('kfree(rcu_dereference_raw(entry->cache));', body)
        factory = self.owned('factory.c')
        selected = factory[factory.index('int lsf_factory_sidcache_destroy('):factory.index('int lsf_factory_sidcache_candidate(')]
        self.assertLess(selected.index('lsf_prepaid_record_queue('), selected.index('lsf_prepaid_blob_finish('))
        self.assertLess(selected.index('spin_lock_irqsave('), selected.index('lsf_prepaid_record_queue('))
        self.assertLess(selected.index('lsf_prepaid_blob_finish('), selected.index('spin_unlock_irqrestore('))

    def test_close_compares_anchor_under_current_policy_rcu_before_any_table_dereference(self):
        body = self.owned('audit-string-private.c')
        body = body[body.index('void lsf_prepaid_sidcache_drain('):]
        self.assertIn('slot < LSF_ALLOCATION_SLOTS', body)
        self.assertLess(body.index('lsf_factory_sidcache_candidate('), body.index('rcu_read_lock()'))
        self.assertLess(body.index('policy = rcu_dereference('), body.index('policy->sidtab == anchor'))
        self.assertLess(body.index('policy->sidtab == anchor'), body.index('lsf_prepaid_sidcache_detach('))
        self.assertNotRegex(body, r'\(struct sidtab\s*\*\)\s*anchor')
        detach = self.owned('sidcache-private.c')
        detach = detach[detach.index('void lsf_prepaid_sidcache_detach('):]
        self.assertLess(detach.index('spin_lock_irqsave('), detach.index('lsf_factory_sidcache_current('))
        self.assertLess(detach.index('lsf_factory_sidcache_current('), detach.index('cache = address;'))
        self.assertLess(detach.index('lsf_factory_sidcache_queue('), detach.index('list_del('))
        self.assertLess(detach.index('spin_unlock_irqrestore('), detach.index('lsf_prepaid_sidcache_retire('))

    def test_real_callback_copies_original_birth_without_following_dead_parent(self):
        body = self.owned('sidcache-private.c')
        callback = body[body.index('static void lsf_prepaid_sidcache_callback('):body.index('static void lsf_prepaid_sidcache_retire(')]
        self.assertIn('lsf_factory_blob_lookup(cache, LSF_PREPAID_SIDCACHE, &birth)', callback)
        self.assertIn('lsf_factory_blob_finish(birth, LSF_PREPAID_SIDCACHE)', callback)
        self.assertNotIn('cache->', callback)
        self.assertNotIn('head->', callback)
        retire = body[body.index('static void lsf_prepaid_sidcache_retire('):body.index('static bool lsf_prepaid_sidcache_destroy(')]
        self.assertIn('else if (owned == 0)\n        kfree_rcu(cache, rcu_member);', retire)

    def test_same_birth_record_carries_generation_anchor_and_no_extra_quota_or_refund(self):
        body = self.owned('prepaid.h')
        publish = body[body.index('static inline int lsf_prepaid_sidcache_publish('):body.index('static inline int lsf_prepaid_sidcache_candidate(')]
        self.assertIn('record->owner_generation != key.generation', publish)
        self.assertIn('record->generation != ticket.generation', publish)
        self.assertLess(publish.index('record->cache_anchor = anchor;'), publish.index('record->deferred = LSF_PREPAID_PUBLISHED'))
        self.assertNotRegex(body, r'struct lsf_prepaid_ticket current\b')
        self.assertIn('records[LSF_ALLOCATION_SLOTS]', body)
        self.assertIn('LSF_BACKING_BYTES 524288u', body)
        self.assertIn('LSF_BOOTSTRAP_CEILING 1048576u', body)
        self.assertIn('return NULL;', self.owned('factory-private.h'))

    def test_reference_uses_real_factory_and_maintained_cache_bodies_without_geometry_claim(self):
        body = sid.reference_body().decode()
        for name in ('lsf_factory_sidcache_publish', 'lsf_factory_sidcache_current', 'lsf_factory_sidcache_destroy'):
            self.assertEqual(body.count('int '+name+'('), 1)
        self.assertIn(sid.observed(self.original('sidtab_destroy_entry'), 'sidtab_destroy_entry'), body)
        self.assertIn(sid.private(self.original('sidtab_sid2str_put'), 'sidtab_sid2str_put'), body)
        source = self.owned('sidcache-reference.c')
        self.assertIn('SIDCACHE_OLD general-cache-allocation RED', source)
        self.assertIn('assert(netport_reference_main() == 0);', source)
        self.assertEqual(len(re.findall(r'sid_observed\("', source)), 14)
        for field in ('kernelBuilt', 'actualLsmExecuted', 'completeAllocationClosure', 'productionInstallation'):
            self.assertIs(sid.fixture()[field], False)


if __name__ == '__main__':
    unittest.main()
