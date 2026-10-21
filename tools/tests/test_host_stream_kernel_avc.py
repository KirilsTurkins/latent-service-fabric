"""Closed actual AVC preimages, original cache policy and private lifetime."""
import hashlib
import re
import unittest
from tools import host_stream_kernel_avc as avc


class KernelAvc(unittest.TestCase):
    def setUp(self):
        self.fixture=avc.fixture()

    def original(self,name):
        return self.fixture['sections'][name]['text']

    def private(self,name):
        return avc.private(self.original(name),name)

    def owned(self,name):
        return (avc.OWNED/name).read_text()

    def test_seventeen_actual_whole_inputs_and_nineteen_exact_definitions(self):
        direct=set(avc.netport.fixture()['source']) | {avc.AVC,avc.HEADER}
        self.assertEqual(len(direct),17)
        self.assertEqual(sum(self.fixture['source'][name]['bytes'] for name in direct),1110423)
        self.assertEqual(set(self.fixture['source']),direct | {avc.sidcache.SIDTAB})
        self.assertEqual(self.fixture['source'][avc.sidcache.SIDTAB],
                         avc.sidcache.fixture()['source'][avc.sidcache.SIDTAB])
        self.assertEqual(len(self.fixture['sections']),19)
        self.assertEqual(self.fixture['upstreamCommit'],avc.maintained.COMMIT)
        for name,row in self.fixture['sections'].items():
            self.assertEqual(avc.section(row['text'],name),row['text'])
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(),row['sha256'])

    def test_unknown_duplicate_changed_crlf_or_missing_whole_sources_refuse(self):
        with self.assertRaises(ValueError):avc.authenticate({})
        with self.assertRaises(ValueError):avc.section('', 'not-selected')
        for name,row in self.fixture['sections'].items():
            raw=row['text']
            for bad in (raw+raw,raw.replace('\n','\r\n'),raw.replace('\n{\n','\n{\n;\n')):
                with self.subTest(name=name),self.assertRaises(ValueError):avc.section(bad,name)

    def test_old_heap_producers_become_exact_typed_original_children(self):
        kinds={'avc_xperms_decision_alloc':('AVC_DECISION','AVC_DATA'),
            'avc_xperms_alloc':('AVC_XPERMS',),'avc_alloc_node':('AVC_NODE',)}
        for name,expected in kinds.items():
            raw=self.original(name);new=self.private(name)
            self.assertIn('kmem_cache_zalloc(',raw)
            self.assertNotIn('kmem_cache_zalloc(',new)
            self.assertIn('lsf_factory_child_allocate(*source,',new)
            for kind in expected:self.assertIn('LSF_PREPAID_'+kind,new)
        for name in avc.CLONES:self.assertNotRegex(self.private(name),r'\b(?:kmalloc|kzalloc|kmem_cache_zalloc)\(')

    def test_each_selected_private_call_inherits_explicit_source(self):
        for name in avc.CLONES:
            selected=self.private(name)
            self.assertIn('const struct lsf_factory_blob *source)',selected.split('\n{\n')[0])
            for target in avc.CLONES:self.assertNotRegex(selected,r'(?<!\w)'+target+r'\(')
        source=self.owned('avc-private.c')
        self.assertNotIn('current->',source)
        self.assertNotIn('kmalloc(',source)

    def test_all_six_normal_destructor_and_revocation_remainders_are_exact(self):
        for name in avc.OBSERVED:
            raw=self.original(name);new=avc.observed(raw,name)
            stripped=re.sub(r'#ifdef LSF_STREAM_AVC_SOURCE\n.*?#endif\n','',new,flags=re.S)
            self.assertEqual(stripped,raw,name)

    def test_poisoned_private_victim_never_prevents_normal_revocation_or_unlink(self):
        for name,unlink in (('avc_node_delete','hlist_del_rcu('),('avc_node_replace','hlist_replace_rcu(')):
            selected=avc.observed(self.original(name),name)
            self.assertLess(selected.index('lsf_prepaid_avc_node_queue('),selected.index(unlink))
            self.assertLess(selected.index(unlink),selected.index('if (owned >= 0)'))
            self.assertNotIn('return',selected)
            self.assertIn('atomic_dec(&selinux_avc.avc_cache.active_nodes)',selected)

    def test_private_replacement_preflights_both_records_before_any_publication(self):
        source=self.owned('prepaid.h')
        start=source.index('static inline int lsf_prepaid_avc_replace(')
        stop=source.index('static inline int lsf_prepaid_avc_publish(',start)
        selected=source[start:stop]
        for token in ('ticket.slot == old_ticket.slot','LSF_PREPAID_PRIVATE','LSF_PREPAID_PUBLISHED','prior->continuations >= LSF_ALLOCATION_SLOTS'):
            self.assertIn(token,selected)
        self.assertLess(selected.index('prior->continuations >= LSF_ALLOCATION_SLOTS'),selected.index('cache_bucket = bucket + 1u'))
        self.assertLess(selected.index('cache_bucket = bucket + 1u'),selected.index('prior->continuations++'))

    def test_private_cache_publication_retains_original_keys_lock_and_reclaim(self):
        insert=self.private('avc_insert')
        self.assertLess(insert.index('spin_lock_irqsave(lock, flag)'),insert.index('lsf_prepaid_avc_node_replace('))
        self.assertLess(insert.index('lsf_prepaid_avc_node_publish('),insert.index('hlist_add_head_rcu('))
        self.assertIn('return -EAGAIN;',insert)
        self.assertIn('return -ENOMEM;',insert)
        self.assertIn('avc_latest_notif_update(avd->seqno, 1)',insert)
        allocate=self.private('avc_alloc_node')
        self.assertIn('avc_reclaim_node();',allocate)
        self.assertIn('atomic_inc_return(&selinux_avc.avc_cache.active_nodes)',allocate)

    def test_permissive_grant_preserves_policy_updates_and_propagates_real_exhaustion(self):
        denied=self.private('avc_denied')
        for token in ('flags & AVC_STRICT','enforcing_enabled()','avd->flags & AVD_FLAGS_PERMISSIVE','AVC_CALLBACK_GRANT'):
            self.assertIn(token,denied)
        self.assertIn('return lsf_prepaid_avc_update_node(',denied)
        update=self.private('avc_update_node')
        for token in ('AVC_CALLBACK_REVOKE','AVC_CALLBACK_AUDITALLOW_DISABLE','AVC_CALLBACK_AUDITDENY_ENABLE','node->ae.avd.allowed &= ~perms'):
            self.assertIn(token,update)
        self.assertIn('rc = lsf_prepaid_avc_node_replace(node, orig, hvalue, source)',update)

    def test_cache_hit_keeps_original_rcu_and_does_not_adopt_or_allocate(self):
        selected=self.private('avc_has_perm_noaudit')
        for token in ('rcu_read_lock()','rcu_read_unlock()','avc_lookup(ssid, tsid, tclass)','memcpy(avd, &node->ae.avd, sizeof(*avd))'):
            self.assertIn(token,selected)
        self.assertNotIn('lsf_factory_child_allocate',selected)
        self.assertNotIn('source->context =',selected)

    def test_bounded_graph_checks_original_birth_before_reading_linked_fields(self):
        source=self.owned('avc-private.c')
        self.assertIn('seen[(LSF_ALLOCATION_SLOTS + 63u) / 64u]',source)
        selected=source[source.index('static bool lsf_prepaid_avc_xperms_graph'):source.index('static int lsf_prepaid_avc_node_graph')]
        self.assertLess(selected.index('lsf_prepaid_avc_member(walk, node,'),selected.index('cursor = node->xpd_head.next'))
        self.assertLess(selected.index('lsf_prepaid_avc_decision_graph(decision, walk)'),selected.index('decision->xpd_list.prev'))
        self.assertIn('copy->context != walk->context',source)
        self.assertIn('walk->seen[word] &',source)

    def test_partial_decision_failure_follows_actual_nonnull_pointers_not_used_mask(self):
        source=self.owned('avc-private.c')
        selected=source[source.index('static bool lsf_prepaid_avc_decision_graph'):source.index('static bool lsf_prepaid_avc_xperms_graph')]
        self.assertNotIn('xpd.used',selected)
        for field in ('allowed','auditallow','dontaudit'):
            self.assertIn('if (node->xpd.'+field+' &&',selected)
            self.assertIn('sizeof(*node->xpd.'+field+')',selected)

    def test_queued_callback_and_private_failure_have_distinct_original_phases(self):
        source=self.owned('avc-private.c')
        selected=source[source.index('static bool lsf_prepaid_avc_node_free'):source.index('static int lsf_prepaid_avc_node_queue')]
        self.assertIn('callback ? LSF_PREPAID_QUEUED : LSF_PREPAID_PRIVATE',selected)
        self.assertLess(selected.index('lsf_factory_avc_phase('),selected.index('lsf_prepaid_avc_xperms_finish('))
        self.assertLess(selected.index('lsf_prepaid_avc_xperms_finish('),selected.index('lsf_factory_blob_finish(copy, LSF_PREPAID_AVC_NODE)'))

    def test_drain_copies_identity_then_revalidates_under_original_slot_lock(self):
        source=self.owned('avc-private.c');selected=source[source.index('void lsf_prepaid_avc_drain'):]
        self.assertIn('slot < LSF_ALLOCATION_SLOTS',selected)
        self.assertLess(selected.index('lsf_factory_avc_candidate('),selected.index('spin_lock_irqsave('))
        self.assertLess(selected.index('spin_lock_irqsave('),selected.index('lsf_factory_avc_current('))
        self.assertLess(selected.index('lsf_factory_avc_current('),selected.index('avc_node_delete(address)'))
        self.assertNotIn('synchronize_rcu',selected)

    def test_both_connect_permission_paths_have_real_original_socket_source(self):
        source=avc.Path(avc.__file__).read_text()
        self.assertIn('lsf_prepaid_sock_has_perm(sk, SOCKET__CONNECT, &source)',source)
        self.assertIn('lsf_prepaid_avc_has_perm(sksec->sid, sid, sksec->sclass, perm, &ad, &source)',source)
        raw=self.original('sock_has_perm')
        for token in ('SECINITSID_KERNEL','SECINITSID_INIT','selinux_policycap_userspace_initial_context()','ad_net_init_from_sk','current_sid()'):
            self.assertIn(token,raw)

    def test_mandatory_audit_seam_keeps_result_and_never_falls_back_to_normal_allocators(self):
        selected=self.private('avc_has_perm')
        self.assertIn('lsf_prepaid_avc_audit(ssid, tsid, tclass, requested, &avd, rc,',selected)
        self.assertIn('auditdata, source)',selected)
        self.assertIn('if (rc2)\n\t\treturn rc2;',selected)
        self.assertNotRegex(selected,r'(?<!\w)avc_audit\(')
        self.assertIn('int lsf_prepaid_avc_audit(',self.owned('avc-private.h'))

    def test_old_selected_modes_do_not_include_avc_factory_and_limits_are_unchanged(self):
        source=self.owned('factory.c')
        self.assertIn('#ifdef LSF_STREAM_AVC_SOURCE\n#include "factory-avc.c"\n#endif',source)
        self.assertIn('#ifdef LSF_STREAM_AVC_SOURCE\n    for (i = 0; i < LSF_FACTORY_CONTEXTS; ++i)\n        lsf_prepaid_avc_drain(',source)
        prepaid=self.owned('prepaid.h')
        self.assertIn('#define LSF_BACKING_BYTES 524288u',prepaid)
        self.assertIn('#define LSF_BOOTSTRAP_CEILING 1048576u',prepaid)
        self.assertIn('records[LSF_ALLOCATION_SLOTS]',prepaid)
        self.assertIn('return NULL;',self.owned('factory-private.h'))

    def test_all_uninstalled_flags_stay_false_and_reserved_kinds_are_not_range_allowed(self):
        for key in ('kernelBuilt','actualLsmExecuted','completeAllocationClosure','productionInstallation'):
            self.assertIs(self.fixture[key],False)
        source=self.owned('prepaid.h')
        selected=source[source.index('static inline int lsf_prepaid_avc_kind'):source.index('enum lsf_prepaid_deferred')]
        self.assertNotIn('LSF_PREPAID_SIDCACHE',selected)
        self.assertNotIn('LSF_PREPAID_AUDIT_',selected)
        self.assertNotIn('kind <',selected)
        self.assertNotIn('kind >',selected)

    def test_same_translation_unit_private_helpers_do_not_redeclare_prepaid_core_names(self):
        pattern=r'^static(?: inline)? (?:int|bool|void)\s+(\w+)\('
        core=set(re.findall(pattern,self.owned('prepaid.h'),re.M))
        selected=set(re.findall(pattern,self.owned('avc-private.c'),re.M))
        self.assertTrue(core and selected)
        self.assertEqual(core & selected,set())
        self.assertIn('lsf_prepaid_avc_node_publish',selected)
        self.assertIn('lsf_prepaid_avc_node_replace',selected)


if __name__=='__main__':unittest.main()
