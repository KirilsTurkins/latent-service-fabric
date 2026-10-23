"""Actual pinned perf selector and pre-allocation private-target refusal."""
import unittest
from tools import host_stream_kernel_cleanup_perf as source
from tools.host_stream_kernel_device_security import function


class CleanupPerfSource(unittest.TestCase):
    def test_primary_source_and_explicit_unsupported_operations(self):
        value = source.preimages()
        self.assertEqual(len(value['sections']), 7)
        self.assertEqual(len(value['unsupportedOperations']), 2)
        self.assertFalse(value['actualPerfExecution'])
        self.assertFalse(value['fullConstructorClosure'])
        with self.assertRaisesRegex(ValueError, 'cleanup-perf-whole-membership'):
            source.transform({}, {})

    def test_real_original_group_selector_precedes_unsupported_return(self):
        original = source.definition('inherit_task_group')
        original = original[original.index('\tif (!event->attr.inherit ||\n'):
            original.index('\n\tchild_ctx = child->perf_event_ctxp;\n')]
        actual = function(source.private_perf(), 'static int lsf_cleanup_perf_select_group(')
        self.assertIn(original, actual)
        self.assertLess(actual.index('lockdep_assert_held(&parent_ctx->mutex)'),
            actual.index('if (!event->attr.inherit'))
        self.assertLess(actual.index('return 0;'), actual.index('return -EOPNOTSUPP;'))
        for forbidden in ('alloc_perf_context(', 'inherit_group(', 'perf_event_alloc(',
                'kmalloc(', 'kzalloc(', 'kmem_cache_alloc('):
            self.assertNotIn(forbidden, actual)

    def test_actual_context_lifetime_and_both_group_walks(self):
        text = function(source.private_perf(), 'static int lsf_cleanup_perf_init_context(')
        self.assertNotIn('likely(!parent->perf_event_ctxp)', text)
        self.assertLess(text.index('parent_ctx = perf_pin_task_context(parent)'),
            text.index('if (!parent_ctx)'))
        self.assertLess(text.index('mutex_lock(&parent_ctx->mutex)'),
            text.index('perf_event_groups_for_each(event, &parent_ctx->pinned_groups)'))
        self.assertEqual(text.count('lsf_cleanup_perf_select_group('), 2)
        self.assertIn('perf_event_groups_for_each(event, &parent_ctx->flexible_groups)', text)
        out = text[text.index('out_unlock:\n'):]
        self.assertLess(out.index('if (rotation_changed)'), out.index('mutex_unlock(&parent_ctx->mutex)'))
        self.assertLess(out.index('raw_spin_lock_irqsave(&parent_ctx->lock, flags)'),
            out.index('parent_ctx->rotate_disable = saved_rotation'))
        self.assertLess(out.index('mutex_unlock(&parent_ctx->mutex)'), out.index('perf_unpin_context(parent_ctx)'))
        self.assertLess(out.index('perf_unpin_context(parent_ctx)'), out.index('put_ctx(parent_ctx)'))
        pin = source.definition('perf_pin_task_context')
        self.assertIn('perf_lock_task_context(task, &flags)', pin)
        locked = source.definition('perf_lock_task_context')
        self.assertIn('rcu_dereference(task->perf_event_ctxp)', locked)
        self.assertIn('refcount_inc_not_zero(&ctx->refcount)', locked)

    def test_full_task_init_and_error_cleanup_project_to_original(self):
        actual = function(source.private_perf(), 'int lsf_prepaid_cleanup_perf_event_init_task(')
        actual = source.replace(actual,
            'int lsf_prepaid_cleanup_perf_event_init_task(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *child, u64 clone_flags)\n',
            'int perf_event_init_task(struct task_struct *child, u64 clone_flags)\n')
        actual = source.replace(actual, '\n\tif (clone_flags != LSF_CLEANUP_CLONE_FLAGS ||\n'
            '\t    !lsf_factory_cleanup_constructor_current(source, child))\n\t\treturn -EOPNOTSUPP;\n', '')
        actual = source.replace(actual, 'lsf_cleanup_perf_init_context(child, clone_flags)',
            'perf_event_init_context(child, clone_flags)')
        self.assertEqual(actual, source.definition('perf_event_init_task'))

    def test_central_target_guard_precedes_actual_event_and_pmu_allocation(self):
        original = source.definition('perf_event_alloc')
        self.assertLess(original.index('node = (cpu >= 0)'), original.index('kmem_cache_alloc_node('))
        # This insertion point precedes the complete real allocator body;
        # callers with ordinary targets and all NULL per-CPU targets retain it.
        text = (source.OWNED / 'factory-cleanup-perf.c').read_text()
        target = function(text, 'int lsf_factory_cleanup_perf_target(')
        self.assertIn('result = 0;', target)
        self.assertLess(target.index('if (at < base || at - base >= LSF_BACKING_BYTES)'),
            target.index('lsf_cleanup_child_source_locked('))
        self.assertIn('target != task', target)
        for forbidden in ('target->', 'task->', 'get_task_struct(', 'put_task_struct('):
            self.assertNotIn(forbidden, target)


if __name__ == '__main__':
    unittest.main()
