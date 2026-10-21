"""Maintained audit-SKB allocator provenance and original-path preservation."""
import hashlib
import unittest

from tools import host_stream_kernel_audit_skb as audit
from tools import host_stream_kernel_sidcache as sid


class KernelAuditSkb(unittest.TestCase):
    def original(self, name):
        return audit.fixture()['sections'][name]['text']

    def test_whole_source_and_all_selected_definitions_have_exact_original_preimages(self):
        value = audit.fixture()
        self.assertEqual((len(value['source']), len(value['sections'])), (21, 9))
        self.assertEqual(sum(row['bytes'] for row in value['source'].values()), 1537920)
        for name, row in sid.fixture()['source'].items():
            self.assertEqual(value['source'][name], row)
        self.assertFalse(value['source']['net/netlink/af_netlink.c']['independentlyGitCorroborated'])
        for name, row in value['sections'].items():
            self.assertEqual(audit.section(row['text'], name), row['text'])
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(), row['sha256'])

    def test_missing_changed_duplicate_or_crlf_source_refuses_before_derivation(self):
        with self.assertRaises(ValueError):
            audit.authenticate({})
        for name in audit.NAMES:
            raw = self.original(name)
            for changed in (raw + raw, raw.replace('\n', '\r\n'), raw.replace('\n{\n', '\n{\n;\n')):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    audit.section(changed, name)

    def test_every_observed_function_has_its_exact_original_config_off_projection(self):
        for name in audit.NAMES - {'__skb_clone'}:
            original = self.original(name)
            text = audit.routed(original, name)
            normal = []
            selected = False
            for line in text.splitlines():
                if line == '#ifdef CONFIG_LSF_STREAM_FACTORY':
                    self.assertFalse(selected)
                    selected = True
                elif line == '#endif' and selected:
                    selected = False
                elif not selected:
                    normal.append(line)
            self.assertFalse(selected)
            with self.subTest(name=name):
                self.assertEqual(' '.join('\n'.join(normal).split()), ' '.join(original.split()))

    def test_private_returns_route_before_each_normal_allocator_cache(self):
        for name, allocator in (('skb_kfree_head', 'kfree(head)'),
                ('kfree_skbmem', 'kmem_cache_free('),
                ('napi_skb_cache_put', 'kasan_mempool_poison_object(')):
            text = audit.routed(self.original(name), name)
            self.assertLess(text.index('lsf_prepaid_audit_return('), text.index(allocator))
        bulk = audit.routed(self.original('kfree_skb_add_bulk'), 'kfree_skb_add_bulk')
        self.assertLess(bulk.index('skb_release_all('), bulk.index('lsf_prepaid_audit_return('))
        self.assertLess(bulk.index('lsf_prepaid_audit_return('), bulk.index('sa->skb_array['))

    def test_private_clone_and_copy_cannot_reach_original_heap_on_failed_birth(self):
        clone = audit.routed(self.original('skb_clone'), 'skb_clone')
        self.assertLess(clone.index('if (owned)'), clone.index('skb_orphan_frags('))
        self.assertIn('return owned < 0 ? NULL : lsf_prepaid_audit_clone(skb, birth)', clone)
        copy = audit.routed(self.original('skb_copy'), 'skb_copy')
        self.assertLess(copy.index('!lsf_prepaid_audit_linear'), copy.index('skb_frags_readable('))
        self.assertIn('if (owned)\n\t\tn = lsf_prepaid_audit_skb_new(birth, size);\n\telse', copy)

    def test_expansion_routes_before_any_original_allocation_or_data_mutation(self):
        text = audit.routed(self.original('pskb_expand_head'), 'pskb_expand_head')
        self.assertLess(text.index('lsf_prepaid_audit_expand('), text.index('BUG_ON('))
        self.assertLess(text.index('lsf_prepaid_audit_expand('), text.index('kmalloc_reserve('))
        self.assertIn('return owned < 0 ? -EOPNOTSUPP', text)

    def test_private_shared_info_requires_original_capacity_and_alignment_before_dereference(self):
        path = audit.maintained.ROOT/'research/standard-outbound/linux-6.12-lineage/audit-skb-private.c'
        text = path.read_text()
        begin = text.index('static bool lsf_prepaid_audit_linear(')
        end = text.index('static struct sk_buff *lsf_prepaid_audit_clone(', begin)
        linear = text[begin:end]
        self.assertLess(linear.index('lsf_factory_audit_head_current('), linear.index('skb_shinfo('))
        self.assertLess(linear.index('% SKB_DATA_ALIGN(1)'), linear.index('skb_shinfo('))
        self.assertIn('head_birth.context != source.context', linear)

    def test_reference_contains_real_clone_and_final_free_cases_without_kernel_claim(self):
        text = (audit.maintained.ROOT/'research/standard-outbound/linux-6.12-lineage/audit-skb-reference.c').read_text()
        self.assertIn('clone-header-escapes-original-owner RED', text)
        for case in ('actual-clone-inherits-birth-and-real-dataref',
                'last-dataref-and-header-return-before-recycle-without-backing-refund',
                'actual-multicast-copy-retains-new-header-and-head',
                'actual-bulk-final-free-never-inserts-private-header-in-slab-array',
                'actual-napi-final-free-routes-before-normal-cache-poisoning',
                'actual-stolen-head-final-free-retains-head-independently',
                'ordinary-outside-arena-clone-and-free-preserve-original-allocator'):
            self.assertIn(case, text)
        self.assertIn('not Linux geometry', text)


if __name__ == '__main__':
    unittest.main()
