"""Source provenance, ordinary-path preservation and changed lifetime boundaries."""
from pathlib import Path
import re
import unittest
from tools import host_stream_kernel_guarded_stack as source


class GuardedStackSource(unittest.TestCase):
    def test_whole_upstream_and_execution_claims_are_closed(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 6)
        self.assertEqual(len(value['sections']), 9)
        self.assertTrue(value['stackMappingSourceImplemented'])
        self.assertFalse(value['linuxMappingExecuted'])
        self.assertFalse(value['runningTaskStackRetirementImplemented'])
        self.assertFalse(value['productionInstallation'])
        with self.assertRaisesRegex(ValueError, 'guarded-stack-whole-membership'):
            source.transform({}, {})

    def test_original_mapping_and_lazy_free_definitions_are_not_replaced(self):
        raw = Path(source.__file__).read_text()
        self.assertNotIn("sections']['free_vmap_area_noflush']['text']", raw)
        self.assertNotIn("sections']['pte_map']['text']", raw)
        self.assertIn("sections']['remove_vm_area']['text']", raw)
        self.assertIn("sections']['alloc_vmap_area']['text']", raw)

    def test_va_return_does_not_give_bank_metadata_to_global_free_tree(self):
        text = (source.OWNED / 'cleanup-stack-vmap.c').read_text()
        restore = text[text.index('static int lsf_cleanup_stack_restore('):
            text.index('int lsf_prepaid_cleanup_stack_foreign_unmap(')]
        self.assertNotIn('merge_or_add_vmap_area', restore)
        self.assertNotIn('insert_vmap_area(', restore)
        self.assertIn('kmem_cache_free(vmap_area_cachep, right);', restore)
        self.assertIn('if (!left && !right)', restore)
        self.assertIn('if (result)\n        lsf_cleanup_stack_busy(stack, 1);', restore)

    def test_real_synchronous_unmap_precedes_view_finish_and_parent_abort(self):
        text = (source.OWNED / 'cleanup-stack-vmap.c').read_text()
        abort = text[text.index('int lsf_prepaid_cleanup_stack_abort_unpublished('):]
        self.assertLess(abort.index('lsf_cleanup_stack_unmap(stack);'),
            abort.index('lsf_factory_cleanup_stack_finish(source, stack)'))
        self.assertIn('vunmap_range(address, address + THREAD_SIZE);', text)
        self.assertNotIn('vfree(', text)
        self.assertNotIn('schedule_work(', text)
        self.assertNotIn('call_rcu(', text)
        self.assertNotIn('pte_alloc_kernel_track(', text)
        self.assertIn('pte_mkold(pte_mkclean(ptep_get(entry)))', text)

    def test_mailbox_outside_lock_load_has_single_copy_writers(self):
        creator = (source.OWNED / 'kernel-cleanup-worker.c').read_text()
        deriver = Path(source.prior.__file__).read_text()
        self.assertIn('WRITE_ONCE(lsf_cleanup_pending, owned);', creator)
        self.assertIn('WRITE_ONCE(lsf_cleanup_pending, NULL);', deriver)
        self.assertNotIn('lsf_cleanup_pending = owned;', creator)
        receiver = creator[creator.index('static void lsf_cleanup_create_kthread('):
            creator.index('int lsf_prepaid_cleanup_worker_create(void)')]
        self.assertNotIn('owned->', receiver.split('complete(done);', 1)[1])
        old = ('struct task_struct *kthreadd_task;\n' + source.prior.definition('kthreadd') +
            source.prior.definition('__kthread_create_worker'))
        new = source.prior.kthreadd_prefix(old)
        normal = re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', new, flags=re.S)
        self.assertEqual(re.findall(r'\w+|[^\s]', old), re.findall(r'\w+|[^\s]', normal))

    def test_no_runtime_enablement_or_racy_instrumentation_absence_shortcut(self):
        text = (source.OWNED / 'cleanup-stack-vmap.c').read_text()
        self.assertIn('trace_alloc_vmap_area(error ? VMALLOC_END', text)
        self.assertNotIn('trace_alloc_vmap_area_enabled(', text)
        self.assertNotIn('EXPORT_SYMBOL', text)
        self.assertNotIn('VM_NO_GUARD', text)
        self.assertNotIn('VM_MAP_PUT_PAGES', text)
        self.assertNotIn('kernel_clone(', text)
        self.assertNotIn('wake_up_new_task(', text)

    def test_actual_task_address_is_bound_before_any_abort_task_field_read(self):
        text = (source.OWNED / 'cleanup-stack-vmap.c').read_text()
        abort = text[text.index('int lsf_prepaid_cleanup_stack_abort_unpublished('):]
        self.assertLess(abort.index('lsf_factory_cleanup_stack_current(source, task)'),
            abort.index('stack->vm.addr != task->stack'))
        factory = (source.OWNED / 'factory-cleanup-stack.c').read_text()
        current = factory[factory.index('void *lsf_factory_cleanup_stack_current('):
            factory.index('int lsf_factory_cleanup_stack_finish(')]
        self.assertIn('actual_task != (const void *)((char *)page_address(factory.pages)', current)
        self.assertIn('source.task.generation', current)
        self.assertIn('record->deferred != LSF_PREPAID_PRIVATE', current)


if __name__ == '__main__':
    unittest.main()
