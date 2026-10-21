"""Authenticated actual route lookup, allocator/refcount and closed policy boundaries."""
import hashlib
import re
import unittest
from tools import host_stream_kernel_route as route


def previous_shared(name, raw):
    """Closed projection of only this leaf's three shared source changes."""
    text=raw.decode()
    if name=='factory-private.h':
        text=route.replace(text,'int lsf_factory_route_queue(const void *);\n'
            'int lsf_factory_route_return(const void *);\n','')
    elif name=='factory.c':
        for symbol in ('lsf_factory_route_queue','lsf_factory_route_return'):
            prefix='int '+symbol+'(';require=route.require
            require(text.count(prefix)==1,'shared-projection-definition')
            start=text.index(prefix);end=text.index('\n}\n',start)+4
            text=text[:start]+text[end:]
    else:
        route.require(name=='prepaid.h','shared-projection-name')
        text=route.replace(text,'    LSF_PREPAID_BIND_BUCKET, LSF_PREPAID_BIND2_BUCKET,\n'
            '    LSF_PREPAID_ROUTE\n','    LSF_PREPAID_BIND_BUCKET, LSF_PREPAID_BIND2_BUCKET\n')
        text=route.replace(text,'!lsf_prepaid_bind_kind(kind) &&\n         kind != LSF_PREPAID_ROUTE)',
            '!lsf_prepaid_bind_kind(kind))',3)
        start=text.index('/* Only after the original dst rcuref reached zero, immediately BEFORE the\n')
        end=text.index('static inline int lsf_prepaid_blob_queue(',start)
        text=text[:start]+text[end:]
        text=route.replace(text,'kind != LSF_PREPAID_AVC_NODE && kind != LSF_PREPAID_ROUTE && record->deferred) ||\n'
            '        (kind == LSF_PREPAID_ROUTE && record->deferred == LSF_PREPAID_PUBLISHED) ||\n',
            'kind != LSF_PREPAID_AVC_NODE && record->deferred) ||\n')
    return text.encode()


class KernelRoute(unittest.TestCase):
    def setUp(self):self.fixture=route.fixture()
    def original(self,name):return self.fixture['sections'][name]['text']
    def owned(self,name):return (route.OWNED/name).read_text()

    def test_whole_maintained_sources_and_complete_function_preimages_are_bound(self):
        self.assertEqual(len(self.fixture['source']),42)
        self.assertEqual(sum(r['bytes'] for r in self.fixture['source'].values()),2429600)
        self.assertEqual(len(self.fixture['sections']),28)
        for name,row in self.fixture['sections'].items():
            self.assertEqual(route.section(row['text'],name),row['text'])
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(),row['sha256'])
        for name,row in route.bind.fixture()['source'].items():self.assertEqual(self.fixture['source'][name],row)

    def test_changed_duplicate_crlf_unknown_or_missing_preimages_refuse(self):
        with self.assertRaises(ValueError):route.authenticate({})
        with self.assertRaises(ValueError):route.section('', 'unknown')
        for name,row in self.fixture['sections'].items():
            for bad in (row['text']*2,row['text'].replace('\n','\r\n'),
                        row['text'].replace('\n{\n','\n{\n;\n')):
                with self.subTest(name=name),self.assertRaises(ValueError):route.section(bad,name)

    def test_three_shared_extensions_project_to_exact_previous_full_source(self):
        self.assertEqual(set(self.fixture['previousOwned']),{'factory-private.h','factory.c','prepaid.h'})
        for name,row in self.fixture['previousOwned'].items():
            raw=previous_shared(name,(route.OWNED/name).read_bytes())
            self.assertEqual(len(raw),row['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256'])

    def test_every_original_normal_body_is_recovered_exactly(self):
        for name in route.OBSERVED:
            raw=self.original(name);selected=route.observed(raw,name)
            def normal(match):
                content=match.group(1)
                return content.split('#else\n',1)[1] if '#else\n' in content else ''
            self.assertEqual(re.sub(r'#ifdef LSF_STREAM_ROUTE_SOURCE\n(.*?)#endif\n',
                normal,selected,flags=re.S),raw,name)

    def test_owned_flow_keeps_initial_and_final_port_lookups_and_real_security(self):
        connect=route.observed(self.original('ip_route_connect'),'ip_route_connect')
        flow=route.observed(self.original('ip_route_output_flow'),'ip_route_output_flow')
        for token in ('ip_route_connect_init(', 'ip_rt_put(rt)',
            'flowi4_update_output(fl4, oif, fl4->daddr, fl4->saddr)', 'security_sk_classify_flow('):
            self.assertIn(token,connect)
        self.assertIn('lsf_prepaid_route_key(net, fl4, sk)',connect)
        self.assertIn('lsf_prepaid_route_key(net, flp4, sk)',flow)
        self.assertIn('lsf_prepaid_route_xfrm(net, rt, flp4, sk)',flow)
        newports=self.original('ip_route_newports')
        for token in ('fl4->fl4_dport = dport','fl4->fl4_sport = sport','ip_rt_put(rt)',
            'security_sk_classify_flow(', 'ip_route_output_flow(sock_net(sk), fl4, sk)'):
            self.assertIn(token,newports)

    def test_private_rcu_lookup_keeps_actual_fib_rules_path_selection_and_errors(self):
        raw=self.original('ip_route_output_key_hash_rcu');selected=route.private(raw,'ip_route_output_key_hash_rcu')
        changed=selected.split('\n{\n',1)[1].replace(route.NAMES['__mkroute_output']+
            '(res, fl4, orig_oif, dev_out, flags, source)', '__mkroute_output(res, fl4, orig_oif, dev_out, flags)')
        self.assertEqual(changed,raw.split('\n{\n',1)[1])
        for token in ('fib_lookup(net, fl4, res, 0)','fib_select_path(net, res, fl4, skb)',
            'dev_get_by_index_rcu(net, fl4->flowi4_oif)','fl4->saddr = res->fi->fib_prefsrc',
            'orig_oif = FIB_RES_OIF(*res)','rth = ERR_PTR(err)'):
            self.assertIn(token,selected)
        scope=route.private(self.original('ip_route_output_key_hash'),'ip_route_output_key_hash')
        self.assertLess(scope.index('rcu_read_lock()'),scope.index('lsf_prepaid_route_key_hash_rcu_owned('))
        self.assertLess(scope.index('lsf_prepaid_route_key_hash_rcu_owned(net'),scope.index('rcu_read_unlock()'))

    def test_actual_cache_hit_and_publication_bodies_are_preserved_without_transfer(self):
        selected=route.private(self.original('__mkroute_output'),'__mkroute_output')
        for token in ('find_exception(nhc, fl4->daddr)','raw_cpu_ptr(nhc->nhc_pcpu_rth_output)',
            'rth = rcu_dereference(*prth)','rt_cache_valid(rth) && dst_hold_safe(&rth->dst)',
            'rt_set_nexthop(rth, fl4->daddr, res, fnhe, fi, type, 0, do_cache)'):
            self.assertIn(token,selected)
        self.assertLess(selected.index('return rth;'),selected.index('lsf_prepaid_route_alloc_owned('))
        cache=self.original('rt_cache_route');exception=self.original('rt_bind_exception')
        for token in ('dst_hold(&rt->dst)','cmpxchg(p, orig, rt)', 'dst_release(&orig->dst)',
            'dst_release(&rt->dst)'):self.assertIn(token,cache)
        for token in ('spin_lock_bh(&fnhe_lock)','rcu_assign_pointer(*porig, rt)',
            'dst_dev_put(&orig->dst)','dst_release(&orig->dst)'):self.assertIn(token,exception)

    def test_prepaid_miss_keeps_full_original_rtable_initialization(self):
        raw=self.original('rt_dst_alloc');selected=route.private(raw,'rt_dst_alloc')
        body=selected.split('\n{\n',1)[1].replace(
            'lsf_prepaid_route_allocate(dev, (noxfrm ? DST_NOXFRM : 0), source)',
            'dst_alloc(&ipv4_dst_ops, dev, DST_OBSOLETE_FORCE_CHK,\n\t\t       (noxfrm ? DST_NOXFRM : 0))')
        self.assertEqual(body,raw.split('\n{\n',1)[1])
        source=self.owned('route-private.c')
        self.assertIn('lsf_factory_child_allocate(*source, sizeof(*rt), LSF_PREPAID_ROUTE)',source)
        self.assertIn('dst_init(&rt->dst, &ipv4_dst_ops, dev, DST_OBSOLETE_FORCE_CHK, flags)',source)
        self.assertNotIn('GFP_KERNEL',source)
        self.assertNotIn('kmem_cache_alloc(',source)

    def test_actual_ipv4_metrics_refcounts_and_fib_final_cleanup_stay_original(self):
        self.assertIn('WARN_ON(1);\n\treturn NULL;',self.original('ipv4_cow_metrics'))
        self.assertIn('refcount_inc(&fib_metrics->refcnt)',self.original('ip_dst_init_metrics'))
        self.assertIn('refcount_dec_and_test(&p->refcnt)',self.original('ip_dst_metrics_put'))
        self.assertIn('ip_dst_init_metrics(&rt->dst, fi->fib_metrics)',self.original('rt_set_nexthop'))
        self.assertIn('ip_dst_metrics_put(dst)',self.original('ipv4_dst_destroy'))
        for name in ('rt_fibinfo_free','rt_fibinfo_free_cpus'):
            self.assertIn('dst_release_immediate(&rt->dst)',self.original(name))
        self.assertIn('free_nh_exceptions(nhc)',self.original('fib_nh_common_release'))
        self.assertNotIn('dst_cow_metrics_generic(',self.owned('route-private.c'))

    def test_source_comes_from_actual_socket_not_current_task_or_late_pointer_registration(self):
        source=self.owned('route-private.c')
        for token in ('sk_const_to_full_sk(sk)','lsf_prepaid_netlabel_source((struct sock *)sk, source)',
            'sk->sk_family != AF_INET','sk->sk_protocol != IPPROTO_TCP','sk->sk_prot != &tcp_prot',
            'net != sock_net(sk)'):self.assertIn(token,source)
        for token in ('current->','EXPORT_SYMBOL','alloc_pages(', 'register_owner'):
            self.assertNotIn(token,source)

    def test_clone_derives_same_original_route_birth_and_does_not_adopt_normal_cache_hits(self):
        source=self.owned('route-private.c');start=source.index('static void *lsf_prepaid_route_clone_allocate(')
        end=source.index('\n}\n',start);body=source[start:end]
        self.assertIn('lsf_factory_blob_lookup(original, LSF_PREPAID_ROUTE, &source)',body)
        self.assertIn('if (owned == 0)\n        return dst_alloc(',body)
        self.assertIn('if (owned < 0)\n        return NULL;',body)
        self.assertIn('original->dst.ops != &ipv4_dst_ops || original->dst.lwtstate',body)
        self.assertIn('lsf_prepaid_route_allocate(dev, original->dst.flags, &source)',body)
        selected=route.observed(self.original('rt_dst_clone'),'rt_dst_clone')
        for token in ('READ_ONCE(rt->dst.input)','READ_ONCE(rt->dst.output)',
            'new_rt->dst.error = rt->dst.error','lwtstate_get(rt->dst.lwtstate)'):
            self.assertIn(token,selected)

    def test_final_rcuref_precedes_queue_and_actual_callback_precedes_view_return(self):
        release=route.observed(self.original('dst_release'),'dst_release')
        self.assertLess(release.index('rcuref_put('),release.index('lsf_factory_route_queue(dst)'))
        self.assertLess(release.index('dst_count_dec(dst)'),release.index('lsf_factory_route_queue(dst)'))
        self.assertLess(release.index('lsf_factory_route_queue(dst)'),release.index('call_rcu_hurry('))
        destroy=route.observed(self.original('dst_destroy'),'dst_destroy')
        for token in ('child = xdst->child','dst->ops->destroy(dst)',
            'netdev_put(dst->dev, &dst->dev_tracker)','lwtstate_put(dst->lwtstate)'):
            self.assertLess(destroy.index(token),destroy.index('lsf_factory_route_return(dst)'))
        self.assertLess(destroy.index('lsf_factory_route_return(dst)'),destroy.index('dst = child;'))
        self.assertIn('dst_release_immediate(dst)',destroy)
        self.assertIn('dst_destroy(dst)',self.original('dst_destroy_rcu'))

    def test_unknown_duplicate_or_poisoned_private_dst_never_reaches_normal_slub(self):
        source=self.owned('factory.c');start=source.index('int lsf_factory_route_return(')
        body=source[start:source.index('\n}\n',start)]
        self.assertIn('lsf_factory_blob_lookup_locked(address, LSF_PREPAID_ROUTE, &copy)',body)
        self.assertIn('copy.ticket, LSF_PREPAID_ROUTE)',body)
        self.assertIn('result = -1;',body)
        self.assertNotIn('address->',body)
        self.assertIn('if (lsf_factory_route_return(dst) == 0)',route.observed(self.original('dst_destroy'),'dst_destroy'))

    def test_no_policy_fast_path_keeps_socket_precedence_and_default_block(self):
        original=self.original('xfrm_lookup_with_ifid');source=self.owned('route-private.c')
        self.assertLess(original.index('sk && sk->sk_policy[XFRM_POLICY_OUT]'),original.index('dst_orig->flags & DST_NOXFRM'))
        self.assertLess(source.index('rcu_access_pointer(sk->sk_policy[XFRM_POLICY_OUT])'),source.index('rt->dst.flags & DST_NOXFRM'))
        for token in ('net->xfrm.policy_count[XFRM_POLICY_OUT]',
            'net->xfrm.policy_default[XFRM_POLICY_OUT]', 'XFRM_USERPOLICY_BLOCK',
            'rt->dst.dev->flags & IFF_LOOPBACK', 'return ERR_PTR(-EPERM)'):
            self.assertIn(token,source)
        self.assertNotIn('flags |= DST_NOXFRM',source)
        self.assertNotIn('policy_default[XFRM_POLICY_OUT] =',source)
        self.assertIn('return dst_rtable(xfrm_lookup_route(net, &rt->dst,',source)
        self.assertEqual(source.count('xfrm_lookup_route('),1)

    def test_unclosed_transform_tracker_and_lwt_producers_are_refused_before_allocation(self):
        source=self.owned('route-private.c');key=source[source.index('struct rtable *lsf_prepaid_route_key('):]
        self.assertLess(key.index('IS_ENABLED(CONFIG_NET_DEV_REFCNT_TRACKER)'),key.index('lsf_prepaid_route_key_hash_owned('))
        selected=route.private(self.original('__mkroute_output'),'__mkroute_output')
        self.assertLess(selected.index('if (nhc->nhc_lwtstate)'),selected.index('find_exception('))
        xfrm=source[source.index('struct rtable *lsf_prepaid_route_xfrm('):]
        self.assertIn('return ERR_PTR(-EOPNOTSUPP)',xfrm)
        self.assertNotIn('xfrm_tmpl_resolve(',xfrm)
        self.assertNotIn('xfrm_bundle_lookup(',xfrm)

    def test_original_caps_single_record_owner_and_closed_installation_are_preserved(self):
        source=self.owned('prepaid.h')
        self.assertIn('#define LSF_BACKING_BYTES 524288u',source)
        self.assertIn('records[LSF_ALLOCATION_SLOTS]',source)
        self.assertEqual(source.count('kind != LSF_PREPAID_ROUTE)'),3)
        queue=source[source.index('static inline int lsf_prepaid_route_queue('):source.index('static inline int lsf_prepaid_blob_queue(')]
        for token in ('record->owner_generation != key.generation','record->generation != ticket.generation',
            'record->deferred != LSF_PREPAID_PRIVATE','context->continuations == LSF_ALLOCATION_SLOTS',
            'record->deferred = LSF_PREPAID_QUEUED','context->continuations++'):
            self.assertIn(token,queue)
        self.assertIn('kind == LSF_PREPAID_ROUTE && record->deferred == LSF_PREPAID_PUBLISHED',source)
        self.assertIn('context->closed || context->live || context->continuations',source)
        self.assertIn('return NULL;',self.owned('factory-private.h'))
        for field in ('completeAllocationClosure','finalFreeCertified','productionInstallation'):
            self.assertIs(self.fixture[field],False)


if __name__=='__main__':unittest.main()
