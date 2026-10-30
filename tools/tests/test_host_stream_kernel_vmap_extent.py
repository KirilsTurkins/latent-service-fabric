"""Finite source selection controls, not kernel/PTE execution evidence."""
import hashlib
import re
import unittest

from tools import host_stream_kernel_vmap_extent as source
from tools.host_stream_kernel_cleanup_native import function
from tools.tests.test_host_stream_kernel_stack_alignment import selected, actual_carve_arithmetic


def lookup(nodes, index, lower, body):
    """Source-bound traversal model; do not relabel this as Linux execution."""
    bound = int(re.search(r'while \(node && visited < (\d+)u\)',body)[1])
    if ('if (area->va_start >= VMALLOC_START)' not in body or
            'first = area;\n            node = node->rb_left;' not in body or
            '} else {\n            node = node->rb_right;' not in body or
            'if (node)\n        return NULL;' not in body):
        raise ValueError('unknown-selection-source')
    first = None;visited = 0
    while index is not None and visited < bound:
        row = nodes[index];visited += 1
        if row['start'] >= lower:
            first = index;index = row['left']
        else:
            index = row['right']
    return (None if index is not None else first),visited


class VmapExtentSource(unittest.TestCase):
    def test_actual_2460_preimage_only_selection_changes_and_foreign_source_refuses(self):
        before = selected();raw = before[source.NAME]
        self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),source.PREIMAGE)
        after = source.transform(before)
        self.assertEqual(set(before),set(after))
        self.assertEqual([n for n in before if before[n] != after[n]],[source.NAME])
        old = raw.decode();new = after[source.NAME].decode()
        for signature in ('static int lsf_cleanup_stack_restore(',
                'static void lsf_cleanup_stack_busy(', 'static int lsf_cleanup_stack_unmap(',
                'static pte_t *lsf_cleanup_existing_pte_observed('):
            self.assertEqual(function(old,signature),function(new,signature))
        self.assertEqual(old.split('int lsf_prepaid_cleanup_stack_create_observed(',1)[1],
                         new.split('int lsf_prepaid_cleanup_stack_create_observed(',1)[1])
        for changed in ({}, {**before,source.NAME:raw+b'\n'}, after):
            with self.assertRaisesRegex(ValueError,'compiled-2460-preimage'):
                source.transform(changed)

    def test_domain_lower_bound_is_one_original_extent_and_never_next_fit(self):
        text = source.transform(selected())[source.NAME].decode()
        body = function(text,'static struct vmap_area *lsf_cleanup_stack_extent(')
        nodes = {
            'small':{'start':0x104000,'end':0x108000,'left':'outside','right':'large'},
            'outside':{'start':1,'end':0x102000,'left':None,'right':None},
            'large':{'start':0x120000,'end':0x180000,'left':None,'right':None}}
        self.assertEqual(lookup(nodes,'small',0x100000,body),('small',2))
        first = nodes['small']
        self.assertIsNone(actual_carve_arithmetic(text,first['start'],first['end']))
        self.assertIsNotNone(actual_carve_arithmetic(text,nodes['large']['start'],nodes['large']['end']))
        self.assertEqual(lookup(nodes,'outside',0x100000,body),(None,1))
        # A candidate ending beyond the fixed window is refused, never clipped.
        self.assertIsNone(actual_carve_arithmetic(text,0x104000,0x200001))
        carve = function(text,'static int lsf_cleanup_stack_carve(')
        self.assertEqual(carve.count('lsf_cleanup_stack_extent()'),1)
        self.assertLess(carve.index('lsf_cleanup_stack_extent()'),carve.index('start = free->va_start;'))
        self.assertLess(carve.index('spin_lock_irqsave('),carve.index('lsf_cleanup_stack_extent()'))
        self.assertNotIn('list_first_entry',carve)
        self.assertNotIn('for (',carve)
        self.assertNotIn('while (',carve)
        for forbidden in ('rb_next(', 'kmem_cache_', 'preload', 'purge_', 'node_alloc(', 'va_clip('):
            self.assertNotIn(forbidden,body)

    def test_exact_64_visit_boundary_refuses_unfinished_walk_and_cyclic_input(self):
        text = source.transform(selected())[source.NAME].decode()
        body = function(text,'static struct vmap_area *lsf_cleanup_stack_extent(')
        self.assertIn('visited < 64u',body)
        # A descending left chain has a known final lower bound at its leaf.
        for count,expected in ((64,63),(65,None)):
            nodes={i:{'start':0x100000+(count-i)*4096,'left':i+1 if i+1<count else None,
                      'right':None} for i in range(count)}
            with self.subTest(count=count):
                self.assertEqual(lookup(nodes,0,0x100000,body),(expected,64))
        self.assertEqual(lookup({0:{'start':0x100000,'left':0,'right':None}},0,0x100000,body),
                         (None,64))
        self.assertEqual(lookup({},None,0x100000,body),(None,0))


if __name__ == '__main__':
    unittest.main()
