"""Maintained PID/IDR statement, ancestry and lock boundaries; source only."""
import unittest
from tools import host_stream_kernel_cleanup_pid as source


class CleanupPidSource(unittest.TestCase):
    def test_fixed_primary_origins_and_complete_profile_gates_remain_false(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 3)
        self.assertEqual(len(value['sections']), 4)
        self.assertEqual(len(value['radixDefinitions']), 7)
        for name in ('taskCreated', 'executorReady', 'fullConstructorClosure',
                'sharedPidBootstrapOwnerQualified', 'actualRcuExecution',
                'completeAllocationClosure', 'productionInstallation'):
            self.assertFalse(value[name])
        with self.assertRaisesRegex(ValueError, 'cleanup-pid-whole-membership'):
            source.transform({}, {})

    def test_complete_private_pid_projects_to_original_success_and_every_error_action(self):
        text = source.private_pid().split('struct pid *lsf_prepaid_cleanup_alloc_pid(', 1)[1]
        text = 'struct pid *lsf_prepaid_cleanup_alloc_pid(' + text
        text = source.replace(text,
            'struct pid *lsf_prepaid_cleanup_alloc_pid(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *task, struct pid_namespace *ns, pid_t *set_tid, size_t set_tid_size)\n',
            'struct pid *alloc_pid(struct pid_namespace *ns, pid_t *set_tid,\n\t\t      size_t set_tid_size)\n')
        text = source.replace(text,
            '\n\t/* Exact actual kernel_thread namespace/argument subset. No supplied\n'
            '\t * namespace is dereferenced until exact init namespace membership. */\n'
            '\tif (current != kthreadd_task || ns != &init_pid_ns || ns->level ||\n'
            '\t    set_tid || set_tid_size)\n\t\treturn ERR_PTR(-EOPNOTSUPP);\n', '')
        text = source.replace(text,
            '\tpid = lsf_factory_cleanup_child_new(source, task, LSF_CLEANUP_PID, task);\n',
            '\tpid = kmem_cache_alloc(ns->pid_cachep, GFP_KERNEL);\n')
        text = source.replace(text,
            '\t\tretval = lsf_prepaid_cleanup_pid_preload(source, task, pid, &tmp->idr);\n'
            '\t\tif (retval)\n\t\t\tgoto out_free;\n', '\t\tidr_preload(GFP_KERNEL);\n')
        text = source.replace(text,
            '\t\t\tnr = lsf_prepaid_cleanup_pid_idr_alloc_cyclic(source, task, pid, &tmp->idr, NULL, pid_min,\n',
            '\t\t\tnr = idr_alloc_cyclic(&tmp->idr, NULL, pid_min,\n')
        text = source.replace(text,
            '\t/* Original error order and real IDR unlink ran above. The original\n'
            '\t * bank is retained on any callback/origin uncertainty. */\n'
            '\t(void)lsf_factory_cleanup_child_finish(pid, LSF_CLEANUP_PID);\n',
            '\tkmem_cache_free(ns->pid_cachep, pid);\n')
        self.assertEqual(text, source.definition('alloc_pid'))

    def test_pid_geometry_includes_actual_flexible_upid_and_final_rcu_stays_real(self):
        text = source.private_pid()
        self.assertIn('*bytes = struct_size_t(struct pid, numbers, 1);', text)
        self.assertNotIn('*bytes = sizeof(struct pid);', text)
        delayed = source.definition('delayed_put_pid')
        self.assertIn('container_of(rhp, struct pid, rcu)', delayed)
        self.assertIn('put_pid(pid);', delayed)
        self.assertIn('call_rcu(&pid->rcu, delayed_put_pid);', source.definition('free_pid'))
        self.assertIn('put_pid_ns(ns);', source.definition('put_pid'))

    def test_real_preload_lock_extent_has_no_percpu_node_cache_borrow(self):
        text = source.private_radix()
        preload = text.split('int lsf_prepaid_cleanup_pid_preload(', 1)[1]
        preload = preload.split('static struct radix_tree_node *', 1)[0]
        self.assertIn('local_lock(&radix_tree_preloads.lock);', preload)
        self.assertLess(preload.index('lsf_factory_cleanup_pid_constructing('), preload.index('local_lock('))
        for forbidden in ('preempt_disable(', 'this_cpu_ptr(', 'rtp->', 'kmem_cache_alloc(',
                '__radix_tree_preload(', 'idr_preload('):
            self.assertNotIn(forbidden, preload)
        node = text.split('lsf_cleanup_pid_radix_node_alloc(', 1)[1]
        node = node.split('static int lsf_cleanup_pid_radix_extend(', 1)[0]
        self.assertIn('radix_tree_node_ctor(ret);', node)
        self.assertIn('lsf_factory_cleanup_pid_radix_publish(source, task, pid, ret)', node)
        self.assertNotIn('rtp->', node)
        self.assertNotIn('kmem_cache_alloc(', node)

    def test_cyclic_wrap_and_both_original_attempts_are_preserved_exactly(self):
        text = source.private_idr().split('int lsf_prepaid_cleanup_pid_idr_alloc_cyclic(', 1)[1]
        text = 'int lsf_prepaid_cleanup_pid_idr_alloc_cyclic(' + text
        text = source.replace(text,
            'int lsf_prepaid_cleanup_pid_idr_alloc_cyclic(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *task, const struct pid *pid, struct idr *idr, void *ptr, int start, int end, gfp_t gfp)',
            'int idr_alloc_cyclic(struct idr *idr, void *ptr, int start, int end, gfp_t gfp)')
        text = source.replace(text,
            '\n\tif (ptr || idr != &init_pid_ns.idr ||\n'
            '\t    !lsf_factory_cleanup_pid_constructing(source, task, pid))\n\t\treturn -EOPNOTSUPP;\n', '')
        self.assertEqual(text.count('lsf_cleanup_pid_idr_alloc_u32(source, task, pid, idr, ptr, &id, max, gfp)'), 2)
        text = text.replace('lsf_cleanup_pid_idr_alloc_u32(source, task, pid, idr, ptr, &id, max, gfp)',
            'idr_alloc_u32(idr, ptr, &id, max, gfp)')
        self.assertEqual(text, source.radix_definition('idr_alloc_cyclic'))

    def test_shared_node_parent_and_final_authentication_do_not_borrow_task_lifetime(self):
        text = (source.OWNED / 'factory-cleanup-pid.c').read_text()
        new = text.split('void *lsf_factory_cleanup_pid_radix_new(', 1)[1]
        new = new.split('/* Classify a typed bank birth', 1)[0]
        self.assertIn('source.root, &ticket, &offset)', new)
        self.assertNotIn('source.task, &ticket, &offset)', new)
        self.assertLess(new.index('lsf_device_allocate('), new.index('memset(result, 0, bytes)'))
        find = text.split('static int lsf_cleanup_pid_radix_find_locked(', 1)[1]
        find = find.split('int lsf_factory_cleanup_pid_radix_publish(', 1)[0]
        self.assertIn('factory.device->root.generation', find)
        self.assertIn('record->kind != LSF_DEVICE_CLEANUP_PID_RADIX', find)
        for forbidden in ('cleanup_task', 'task->', 'worker_private', 'LSF_CLEANUP_TASK_RETURNED'):
            self.assertNotIn(forbidden, find)
        finish = text.split('int lsf_factory_cleanup_pid_radix_return_finish(', 1)[1]
        self.assertLess(finish.index('actual.allocation.generation != source.allocation.generation'),
            finish.index('lsf_device_finish('))
        self.assertNotIn('get_task_struct(', finish)
        self.assertNotIn('put_task_struct(', finish)


if __name__ == '__main__':
    unittest.main()
