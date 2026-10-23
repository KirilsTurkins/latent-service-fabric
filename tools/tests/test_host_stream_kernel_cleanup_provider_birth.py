"""Focused source controls; these do not execute Linux IDR or create a pool."""
import unittest
from tools import host_stream_kernel_cleanup_provider_birth as source
from tools.host_stream_kernel_device_security import function


class CleanupProviderBirthSource(unittest.TestCase):
    def test_whole_fixed_source_and_closed_qualification(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 4)
        self.assertFalse(value['poolIdrAllocationExecuted'])
        self.assertFalse(value['taskCreated'])
        with self.assertRaisesRegex(ValueError, 'cleanup-provider-birth-whole-membership'):
            source.transform({}, {})

    def test_only_node_leaf_is_closed_without_preload_or_slab_fallback(self):
        text = source.private_radix()
        leaf = function(text, 'static struct radix_tree_node *\nlsf_provider_no_radix_node(')
        self.assertIn('return NULL;', leaf)
        for forbidden in ('radix_tree_preloads', 'kmem_cache_alloc', 'kmalloc(', 'radix_tree_node_alloc('):
            self.assertNotIn(forbidden, text)
        self.assertIn('return ERR_PTR(-ENOMEM);', text)

    def test_complete_original_extend_body_has_only_closed_leaf_redirect(self):
        text = function(source.private_radix(), 'static int lsf_provider_radix_extend(')
        text = text.replace('lsf_provider_radix_extend(', 'radix_tree_extend(')
        text = text.replace('lsf_provider_no_radix_node(', 'radix_tree_node_alloc(')
        self.assertEqual(text, source.definition('radix_tree_extend'))

    def test_original_idr_order_and_real_errors_preserved(self):
        text = source.private_idr()
        u32 = function(text, 'static int lsf_provider_pool_idr_alloc_u32(')
        self.assertLess(u32.index('lsf_prepaid_cleanup_provider_pool_idr_current('),
            u32.index('base = idr->idr_base'))
        self.assertLess(u32.index('IS_ERR(slot)'), u32.index('*nextid = iter.index + base'))
        self.assertLess(u32.index('*nextid = iter.index + base'), u32.index('radix_tree_iter_replace('))
        for token in ('PTR_ERR(slot)', 'radix_tree_iter_tag_clear(', 'return -ENOSPC;'):
            self.assertIn(token, u32)

    def test_real_static_idr_and_writer_lock_before_pool_field_access(self):
        text = (source.OWNED/'workqueue-cleanup-provider-birth.c').read_text()
        current = function(text, 'int lsf_prepaid_cleanup_provider_pool_idr_current(')
        self.assertIn('root != &worker_pool_idr.idr_rt', current)
        self.assertIn('lockdep_assert_held(&wq_pool_mutex)', current)
        assign = function(text, 'static int lsf_provider_pool_assign_id(')
        self.assertLess(assign.index('lsf_prepaid_cleanup_provider_pool_idr_current('),
            assign.index('pool->id != -1'))
        self.assertIn('return ret;', assign)

    def test_birth_admission_is_stricter_than_retained_physical_identity(self):
        text = (source.OWNED/'factory-cleanup-provider-birth.c').read_text()
        for token in ('lsf_factory_cleanup_task_source_locked(source)', 'factory.pool.poisoned',
                      'factory.device->cleanup_task_claimed', 'LSF_CLEANUP_UNINITIALIZED',
                      'current->mm != factory.mm', 'current_cred() != factory.cred',
                      'lsf_cleanup_provider_part_locked(source, LSF_PROVIDER_POOL, pool, 1)'):
            self.assertIn(token, text)
        self.assertNotIn('lsf_device_allocate(', text)


if __name__ == '__main__':
    unittest.main()
