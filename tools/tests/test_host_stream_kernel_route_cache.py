"""Closed maintained source, actual reference owners and cache-fence placement."""
from pathlib import Path
import unittest
from tools import host_stream_kernel_route_cache as cache


class KernelRouteCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs={n:(Path(__file__).parent/'fixtures'/n).read_bytes() for n in ()}
        # Tests authenticate the complete declared functions from their frozen
        # fixture without acquiring or executing a kernel/archive.
        cls.value=cache.fixture()
        cls.route=cls.value['sections']

    def owned(self,name):return (cache.OWNED/name).read_bytes().decode()

    def test_exact_maintained_prefix_membership_and_no_independent_extra_git_claim(self):
        old=cache.route.fixture()['source'];v=self.value
        self.assertEqual((len(v['source']),len(v['sections'])),(45,42))
        self.assertEqual(sum(r['bytes'] for r in v['source'].values()),2548737)
        self.assertEqual({n:r for n,r in v['source'].items() if n in old},old)
        self.assertEqual(set(v['source'])-set(old),{'include/net/nexthop.h','include/linux/rcuref.h','net/ipv4/nexthop.c'})
        self.assertTrue(all(not v['source'][n]['independentlyGitCorroborated'] for n in set(v['source'])-set(old)))

    def test_private_cache_copies_preserve_original_cleanup_and_refusal_preimages(self):
        for name in cache.CLONES:
            raw=self.route[name]['text'];self.assertEqual(cache.section(raw,name),raw)
            selected=cache.private(raw,name);self.assertIn(cache.NAMES[name]+'(',selected)
            with self.assertRaises(ValueError):cache.private(raw.replace('\n{\n','\n{\n/* changed */\n',1),name)
        selected=cache.private(self.route['rt_cache_route']['text'],'rt_cache_route')
        cleanup=self.route['rt_cache_route']['text'].split('\tif (prev == orig) {',1)[1]
        self.assertEqual(selected.split('\tif (prev == orig) {',1)[1],cleanup)
        self.assertIn('cpu = get_cpu();',selected);self.assertIn('per_cpu_ptr(nhc->nhc_pcpu_rth_output, cpu)',selected)
        self.assertEqual(selected.count('put_cpu();'),2)

    def test_actual_parent_reference_precedes_record_transfer_and_failed_transfer_put(self):
        source=self.owned('route-cache-private.c')
        attach=source[source.index('static int lsf_prepaid_route_parent_attach('):source.index('/* The parent reference is still held')]
        self.assertLess(attach.index('fib_info_hold_safe(fi)'),attach.index('lsf_factory_route_parent_attach(rt, &owner)'))
        self.assertLess(attach.index('nexthop_get(nh)'),attach.index('rcu_dereference(nh->nh_info) != info'))
        self.assertIn('lsf_prepaid_route_parent_put(owner);\n        return -EOPNOTSUPP;',attach)
        self.assertIn('nhc != &fi->fib_nh[res->nh_sel].nh_common',attach)
        self.assertIn('info = container_of(nhc, struct nh_info, fib_nhc);',attach)

    def test_closed_root_fence_and_real_publication_share_the_same_pool_lock(self):
        source=self.owned('route-cache-factory.c');source=source[source.index('int lsf_factory_route_cache_publish('):source.index('int lsf_factory_route_current(')]
        self.assertLess(source.index('spin_lock_irqsave'),source.index('factory.pool.contexts[record->owner].closed'))
        self.assertLess(source.index('factory.pool.contexts[record->owner].closed'),source.index('dst_hold(&rt->dst)'))
        self.assertLess(source.index('dst_hold(&rt->dst)'),source.index('cmpxchg('))
        self.assertLess(source.index('rcu_assign_pointer(*cell, rt)'),source.index('spin_unlock_irqrestore'))
        self.assertNotIn('dst_release(',source);self.assertNotIn('fib_info_put(',source)
        self.assertIn('record->route_cache.cache_kind = kind;',source)

    def test_a_live_birth_cannot_revive_a_dst_after_its_real_final_put(self):
        source=self.owned('route-cache-factory.c');source=source[source.index('int lsf_factory_route_current('):source.index('int lsf_factory_route_parent_take(')]
        self.assertLess(source.index('record->phase != LSF_PREPAID_LIVE'),source.index('page_address(factory.pages)'))
        self.assertLess(source.index('record->owner_generation != context->key.generation'),source.index('dst_hold_safe(&rt->dst)'))
        self.assertLess(source.index('dst_hold_safe(&rt->dst)'),source.index('*route = rt'))
        self.assertLess(source.index('*route = rt'),source.index('spin_unlock_irqrestore'))
        self.assertIn('record->deferred != LSF_PREPAID_PRIVATE',source)

    def test_replaceable_nexthop_aba_never_reuses_a_saved_cache_cell_pointer(self):
        source=self.owned('route-cache-private.c');current=source[source.index('static struct fib_nh_common *lsf_prepaid_route_parent_current('):]
        self.assertLess(current.index('rcu_dereference(nh->nh_info)'),current.index('nhc = &info->fib_nhc'))
        self.assertIn('(lsf_u64)(unsigned long)nhc != owner->nhc',current)
        self.assertIn('per_cpu_ptr(nhc->nhc_pcpu_rth_output, owner->cpu)',current)
        self.assertNotIn('owner->cell',source)
        header=self.owned('route-cache-owner.h');self.assertNotIn('cell;',header)

    def test_exception_search_uses_the_real_lock_key_and_finite_original_chain_bound(self):
        source=self.owned('route-cache-private.c')
        self.assertIn('spin_lock_bh(&fnhe_lock);',source)
        self.assertIn('hash[fnhe_hashfun((__be32)owner->daddr)].chain',source)
        self.assertIn('depth++ < 2u * FNHE_RECLAIM_DEPTH',source)
        self.assertIn('rcu_dereference_protected(*cell, lockdep_is_held(&fnhe_lock)) == rt',source)
        self.assertIn('rcu_assign_pointer(*cell, NULL);\n                        dst_dev_put(&rt->dst);\n                        dst_release(&rt->dst);',source)
        self.assertIn('depth > 2u * FNHE_RECLAIM_DEPTH',source)
        self.assertNotIn('find_exception(',source)

    def test_exact_cache_reference_and_independent_drain_reference_are_distinct(self):
        source=self.owned('route-cache-private.c');drain=source[source.index('void lsf_prepaid_route_cache_drain('):source.index('int lsf_prepaid_route_cache_return(')]
        self.assertIn('slot < LSF_ALLOCATION_SLOTS',drain)
        self.assertLess(drain.index('lsf_factory_route_current('),drain.index('rcu_read_lock()'))
        self.assertLess(drain.index('rcu_read_unlock()'),drain.index('dst_release(&rt->dst)'))
        self.assertIn('cmpxchg((struct rtable **)cell, rt, NULL) == rt',source)
        self.assertIn('rt_add_uncached_list(rt);\n            dst_release(&rt->dst);',source)

    def test_real_parent_put_precedes_actual_view_finish_and_unknown_kind_is_closed(self):
        source=self.owned('route-cache-private.c');tail=source[source.index('int lsf_prepaid_route_cache_return('):]
        self.assertLess(tail.index('lsf_factory_route_parent_take('),tail.index('lsf_prepaid_route_parent_put(owner)'))
        self.assertLess(tail.index('lsf_prepaid_route_parent_put(owner)'),tail.index('lsf_factory_route_return(address)'))
        factory=self.owned('route-cache-factory.c')
        self.assertIn('record->deferred >= LSF_PREPAID_PUBLISHED',factory)
        self.assertIn('record->route_cache.cache_kind > LSF_ROUTE_CACHE_EXCEPTION_OUTPUT',factory)
        self.assertIn('record->route_cache = (struct lsf_route_cache_owner){0};',factory)
        self.assertIn('!lsf_route_cache_empty(&record->route_cache)',(cache.FIXTURE.parents[2]/'host_stream_kernel_route_cache.py').read_text())

    def test_original_fib_nexthop_and_exception_retirement_algorithms_remain_authenticated(self):
        for name in ('free_fib_info_rcu','fib_nh_common_release','rt_fibinfo_free','rt_fibinfo_free_cpus','free_nh_exceptions',
            'nexthop_get','nexthop_put','nexthop_free_rcu','nexthop_free_single','replace_nexthop_single','update_or_create_fnhe'):
            self.assertEqual(cache.section(self.route[name]['text'],name),self.route[name]['text'])
        self.assertIn('refcount_inc_not_zero(&nh->refcnt)',self.route['nexthop_get']['text'])
        self.assertIn('rcu_assign_pointer(old->nh_info, newi);',self.route['replace_nexthop_single']['text'])
        self.assertIn('dst_release_immediate(&rt->dst)',self.route['rt_fibinfo_free']['text'])


    def test_reference_extracts_actual_original_get_put_and_selected_cache_bodies(self):
        raw=cache.reference_body().decode()
        for name in ('fib_info_hold_safe','fib_info_put','nexthop_get','nexthop_put','fnhe_flush_routes'):
            self.assertIn(self.route[name]['text'],raw)
        for name in cache.CLONES[:2]:
            self.assertIn(cache.private(self.route[name]['text'],name),raw)
        self.assertIn('#include "route-cache-factory.c"',raw)
        self.assertIn('#include "route-cache-private.c"',raw)
        original=(cache.OWNED/'factory.c').read_text()
        for name,prefix in (('lsf_factory_context_current','static struct lsf_factory_context *'),
            ('lsf_factory_blob_lookup_locked','static int '),('lsf_factory_route_return','int '),
            ('lsf_factory_poison','void ')):
            start=original.index(prefix+name+'(');end=original.index('\n}\n',start)+3
            self.assertIn(original[start:end],raw)

    def test_reference_keeps_faithful_compare_exchange_and_explicit_serialized_scope(self):
        raw=self.owned('route-cache-reference.c')
        self.assertLess(raw.index('if(competing_route){*cell=competing_route;'),raw.index('old=*cell;if(old==expected)'))
        self.assertIn('int fnhe_genid;',raw)
        self.assertIn('lsf_prepaid_child_allocate(&factory.pool',raw)
        self.assertNotIn('static bool nexthop_get(',raw)
        self.assertNotIn('static inline void fib_info_put(',raw)
        self.assertIn('nh-info-address-aba-recomputes-current-percpu-allocation',raw)
        self.assertIn('dead-dst-live-birth-is-not-revived-or-refunded',raw)
        self.assertIn('unknown-long-exception-chain-poisons-and-retains-owners',raw)
        self.assertIn('SERIALIZED types, refcounts, locks and',raw)


    def test_all_production_and_actual_execution_flags_remain_false(self):
        self.assertTrue(all(self.value[n] is False for n in ('kernelBuilt','actualRouteOrXfrmExecuted','actualLinuxRcuExecuted',
            'completeAllocationClosure','finalFreeCertified','productionInstallation')))
        source=(cache.OWNED/'factory-private.h').read_text();body=source[source.index('static inline const struct lsf_factory_consumer *lsf_factory_selected_consumer('):]
        self.assertIn('return NULL;',body)
        state=self.owned('route-cache-owner.h');self.assertNotIn('malloc(',state);self.assertNotIn('alloc_pages(',state)
        self.assertIn('LSF_ROUTE_PARENT_FIB',state);self.assertIn('LSF_ROUTE_PARENT_NH',state)


if __name__=='__main__':unittest.main()
