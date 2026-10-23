"""Actual maintained fork/error ordering and source-only owner boundaries."""
import unittest
from tools import host_stream_kernel_cleanup_constructor as source


class CleanupConstructorSource(unittest.TestCase):
    def test_fixed_source_membership_and_runtime_gates(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 9)
        self.assertEqual(len(value['sections']), 21)
        self.assertEqual(len(value['parentDerived']), 15)
        for name in ('taskCreated', 'executorReady', 'creatorCallsFullConstructor',
                'taskLsmAllocationClosure', 'perfInheritanceClosure', 'enabledAuditClosure',
                'numaPolicyClosure', 'fullConstructorClosure', 'completeAllocationClosure'):
            self.assertFalse(value[name])
        with self.assertRaisesRegex(ValueError, 'cleanup-constructor-whole-membership'):
            source.transform({}, {})

    def test_original_error_actions_and_labels_stay_in_exact_order(self):
        original = source.definition('copy_process')
        actual = source.full_constructor().split('struct task_struct *lsf_prepaid_cleanup_copy_process(', 1)[1]
        # This whole original region includes PID unlink, architecture, mm,
        # blocking fs/files cleanup, LSM, audit, perf, NUMA, delay and cred tails.
        begin = 'bad_fork_core_free:\n'
        end = '\tWRITE_ONCE(p->__state, TASK_DEAD);\n'
        self.assertEqual(actual[actual.index(begin):actual.index(end)],
            original[original.index(begin):original.index(end)])
        # Preserve original delayed multiprocess-signal cleanup on every exit.
        self.assertEqual(actual[actual.index('fork_out:\n'):], original[original.index('fork_out:\n'):])

    def test_vm_preparation_precedes_locks_and_atomic_commit_precedes_visibility(self):
        text = source.full_constructor()
        prepare = text.index('retval = lsf_prepaid_cleanup_constructor_prepare(source, p);')
        tasklock = text.index('write_lock_irq(&tasklist_lock);')
        commit = text.index('if (!lsf_factory_cleanup_task_publish(source, p))')
        nofail = text.index('/* No more failure paths after this point. */')
        publish = text.index('list_add_tail_rcu(&p->tasks, &init_task.tasks);')
        self.assertLess(prepare, tasklock)
        self.assertLess(tasklock, commit)
        self.assertLess(commit, nofail)
        self.assertLess(nofail, publish)
        self.assertIn('goto bad_fork_core_free;', text[commit:nofail])
        self.assertEqual(text.count('lsf_factory_cleanup_task_publish(source, p)'), 1)

    def test_usage_one_abort_has_real_stack_return_and_original_delayed_free(self):
        text = source.full_constructor()
        tail = text[text.index('bad_fork_free:\n'):text.index('fork_out:\n')]
        self.assertEqual(tail.count('exit_task_stack_account(p);'), 1)
        self.assertEqual(tail.count('delayed_free_task(p);'), 1)
        self.assertNotIn('put_task_stack(p);', tail)
        self.assertLess(tail.index('lsf_factory_cleanup_task_abort_begin'),
            tail.index('exit_task_stack_account(p)'))
        self.assertLess(tail.index('lsf_prepaid_cleanup_constructor_abort_stack'),
            tail.index('delayed_free_task(p)'))
        abort = source.ABORT_STACK
        self.assertLess(abort.index('lsf_factory_cleanup_lifecycle_source('),
            abort.index('refcount_read(&task->usage)'))
        self.assertIn('refcount_read(&task->usage) != 1', abort)
        self.assertEqual(abort.count('refcount_dec_and_test(&task->stack_refcount)'), 1)
        for forbidden in ('put_task_struct(', 'get_task_struct(', 'refcount_set(',
                'put_task_stack(', 'irq_work_queue('):
            self.assertNotIn(forbidden, abort)

    def test_full_numa_copy_projects_exactly_to_original(self):
        text = source.private_mpol()
        text = 'struct mempolicy *lsf_prepaid_cleanup_mpol_dup(' + text.split(
            'struct mempolicy *lsf_prepaid_cleanup_mpol_dup(', 1)[1]
        text = source.replace(text,
            'struct mempolicy *lsf_prepaid_cleanup_mpol_dup(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *task, struct mempolicy *old)\n',
            'struct mempolicy *__mpol_dup(struct mempolicy *old)\n')
        text = source.replace(text, '\tstruct mempolicy *new;\n\n'
            '\tif (!old || current != kthreadd_task)\n\t\treturn ERR_PTR(-EOPNOTSUPP);\n'
            '\tnew = lsf_factory_cleanup_child_new(source, task, LSF_CLEANUP_MPOL, task);\n',
            '\tstruct mempolicy *new = kmem_cache_alloc(policy_cache, GFP_KERNEL);\n')
        self.assertEqual(text, source.definition('mpol_dup'))

    def test_task_lsm_full_dispatch_and_error_free_remain_real(self):
        text = source.private_task_security()
        text = 'int lsf_prepaid_cleanup_security_task_alloc(' + text.split(
            'int lsf_prepaid_cleanup_security_task_alloc(', 1)[1]
        text = source.replace(text,
            'int lsf_prepaid_cleanup_security_task_alloc(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *task, unsigned long clone_flags)\n',
            'int security_task_alloc(struct task_struct *task, unsigned long clone_flags)\n')
        begin = text.index('\tint rc = 0;\n')
        end = text.index('\n\tif (rc)\n', begin)
        text = source.replace(text, text[begin:end], '\tint rc = lsm_task_alloc(task);\n')
        self.assertEqual(text, source.definition('security_task_alloc'))
        self.assertIn('blob_sizes.lbs_task', source.private_task_security())

    def test_abort_drain_never_replays_destructors_or_revives_refcount(self):
        text = (source.OWNED / 'factory-cleanup-constructor.c').read_text()
        drain = text.split('void lsf_factory_cleanup_abort_drain(void)', 1)[1]
        self.assertIn('refcount_read(&task->usage) != 1', drain)
        self.assertLess(drain.index('lsf_cleanup_final_children_locked()'), drain.index('lsf_device_finish('))
        for forbidden in ('put_task_struct(', 'get_task_struct(', 'refcount_set(',
                'free_task(', 'exit_creds(', 'security_task_free('):
            self.assertNotIn(forbidden, drain)


if __name__ == '__main__':
    unittest.main()
