"""Changed source/lifetime boundaries; no Linux/runtime execution claim."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_cleanup_lifecycle as source


class CleanupLifecycleSource(unittest.TestCase):
    def test_origin_whole_membership_and_runtime_claims_fail_closed(self):
        value = source.preimages()
        self.assertEqual((len(value['source']), len(value['sections'])), (11, 14))
        for field in ('taskCreated', 'executorReady', 'runningTaskStackRetirementExecuted',
                'completeAllocationClosure', 'productionInstallation'):
            self.assertFalse(value[field])
        with self.assertRaisesRegex(ValueError, 'cleanup-lifecycle-whole-membership'):
            source.transform({}, {})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            path.write_bytes(json.dumps(dict(value, taskCreated=True)).encode())
            with patch.object(source, 'FIXTURE', path), self.assertRaisesRegex(ValueError,
                    'cleanup-lifecycle-fixed-source'):
                source.preimages()

    def test_original_post_stack_initialization_is_preserved_in_order(self):
        old = source.definition('dup_task_struct')
        new = source.initialized_task()
        begin = old.index('#ifdef CONFIG_THREAD_INFO_IN_TASK')
        end = old.index('\treturn tsk;\n')
        original_tail = old[begin:end]
        selected_tail = original_tail.replace('\tdup_user_cpus_ptr(tsk, orig, node);\n',
            '\terr = lsf_cleanup_dup_empty_user_cpus(tsk, orig);\n'
            '\tif (err)\n\t\tgoto free_stack;\n')
        self.assertIn(selected_tail, new)
        self.assertIn('account_kernel_stack(tsk, 1);', selected_tail)
        self.assertIn('get_random_canary();', selected_tail)
        self.assertIn('kcov_task_init(tsk);', selected_tail)
        self.assertIn('kmap_local_fork(tsk);', selected_tail)
        self.assertLess(new.index('refcount_set(&tsk->usage, 1);'),
            new.index('lsf_factory_cleanup_task_initialized(source, tsk)'))

    def test_affinity_subset_uses_actual_pi_lock_instead_of_racy_allocation(self):
        original = source.definition('dup_user_cpus_ptr')
        self.assertIn('data_race(!src->user_cpus_ptr)', original)
        self.assertIn('user_mask = alloc_user_cpus_ptr(node);', original)
        self.assertIn('raw_spin_lock_irqsave(&src->pi_lock, flags);', original)
        private = source.AFFINITY
        lock = private.index('raw_spin_lock_irqsave(&src->pi_lock, flags);')
        test = private.index('error = src->user_cpus_ptr ? -EOPNOTSUPP : 0;')
        unlock = private.index('raw_spin_unlock_irqrestore(&src->pi_lock, flags);')
        self.assertLess(lock, test)
        self.assertLess(test, unlock)
        self.assertNotIn('alloc_user_cpus_ptr(', private)

    def test_enabled_instrumentation_refuses_before_born_task_claim(self):
        text = source.initialized_task()
        for field in ('CONFIG_SCS', 'CONFIG_KCOV', 'CONFIG_KMSAN', 'CONFIG_DEBUG_LOCK_ALLOC'):
            self.assertLess(text.index('IS_ENABLED(' + field + ')'),
                text.index('tsk = lsf_factory_cleanup_task_claim(source);'))
        self.assertNotIn('#undef CONFIG_', text)

    def test_private_metadata_preserves_original_completion_initialization(self):
        original = source.definition('set_kthread_struct')
        body = (source.OWNED / 'kernel-cleanup-lifecycle.c').read_text()
        init = original[original.index('\tinit_completion(&kthread->exited);'):
            original.index('\treturn true;')].replace('\t', '    ').replace('\n\n', '\n')
        selected = body[body.index('    init_completion(&kthread->exited);'):
            body.index('    return 0;', body.index('    init_completion'))]
        self.assertEqual(init, selected)
        self.assertLess(body.index('lsf_factory_cleanup_kthread_reserve('),
            body.index('init_completion(&kthread->exited);'))

    def test_publication_owns_real_task_reference_before_possible_rcu_drop(self):
        text = (source.OWNED / 'factory-cleanup-lifecycle.c').read_text()
        publish = text[text.index('int lsf_factory_cleanup_task_publish('):
            text.index('int lsf_factory_cleanup_stack_capture(')]
        self.assertLess(publish.index('lsf_cleanup_lifecycle_identity_locked(source, task)'),
            publish.index('tryget_task_struct(task)'))
        self.assertLess(publish.index('tryget_task_struct(task)'),
            publish.index('lsf_device_publish('))
        capture = text[text.index('int lsf_factory_cleanup_stack_capture('):
            text.index('int lsf_factory_cleanup_stack_enqueue(')]
        self.assertNotIn('tryget_task_struct(', capture)
        self.assertIn('factory.device->cleanup_retire_task != task', capture)
        self.assertIn('refcount_read(&task->stack_refcount) != 0', capture)

    def test_exact_task_and_vm_are_checked_before_detach_and_pending_publication(self):
        text = (source.OWNED / 'cleanup-stack-retire.c').read_text()
        release = text[text.index('int lsf_prepaid_cleanup_stack_release('):
            text.index('int lsf_prepaid_cleanup_stack_retire(')]
        self.assertLess(release.index('lsf_factory_cleanup_lifecycle_source(task'),
            release.index('lsf_cleanup_stack_release_match(stack, source, task)'))
        self.assertLess(release.index('lsf_factory_cleanup_stack_capture(source, task, stack)'),
            release.index('task->stack = NULL;'))
        self.assertLess(release.index('task->stack_vm_area = NULL;'),
            release.index('lsf_factory_cleanup_stack_enqueue(source, task)'))
        self.assertLess(release.index('lsf_factory_cleanup_stack_enqueue(source, task)'),
            release.index('wake_up_process(kthreadd_task);'))
        self.assertNotIn('spin_lock(&kthread_create_lock)', text)
        for forbidden in ('call_rcu(', 'schedule_work(', 'vfree(', 'kfree('):
            self.assertNotIn(forbidden, text)

    def test_consumer_put_is_after_actual_vm_return_and_outside_all_locks(self):
        text = (source.OWNED / 'kernel-cleanup-lifecycle.c').read_text()
        drain = text[text.index('void lsf_prepaid_cleanup_retire_one(void)'):]
        self.assertLess(drain.index('lsf_prepaid_cleanup_stack_retire(source, task)'),
            drain.index('put_task_struct(task);'))
        self.assertNotIn('spin_lock', drain)
        self.assertNotIn('task->', drain.split('put_task_struct(task);', 1)[1])
        vm = (source.OWNED / 'cleanup-stack-retire.c').read_text()
        retire = vm[vm.index('int lsf_prepaid_cleanup_stack_retire('):vm.index('#else')]
        self.assertLess(retire.index('lsf_cleanup_stack_unmap(stack)'),
            retire.index('lsf_factory_cleanup_stack_returned(source, task, stack)'))
        self.assertNotIn('exit_task_stack_account(', retire)

    def test_final_cache_guard_does_not_confuse_stack_return_with_task_return(self):
        text = (source.OWNED / 'factory-cleanup-lifecycle.c').read_text()
        final = text[text.index('int lsf_factory_cleanup_task_final('):]
        self.assertIn('cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED', final)
        self.assertIn('refcount_read(&task->usage) != 0', final)
        self.assertIn('task->worker_private', final)
        self.assertIn('lsf_device_finish(&factory.pool, source.owner, source.task', final)
        self.assertNotIn('source.request, LSF_DEVICE_CLEANUP_REQUEST', final)
        self.assertNotIn('context->cursor', final)
        self.assertNotIn('put_task_struct(', final)

    def test_partial_creation_never_publishes_or_claims_worker_success(self):
        text = (source.OWNED / 'kernel-cleanup-lifecycle.c').read_text()
        prepare = text[text.index('static struct task_struct *lsf_cleanup_prepare_unpublished('):
            text.index('void lsf_prepaid_cleanup_retire_one(void)')]
        self.assertIn('lsf_factory_cleanup_task_abort_begin(owned->source, task)', prepare)
        self.assertIn('lsf_prepaid_cleanup_abort_initialized(owned->source, task)', prepare)
        self.assertIn('return ERR_PTR(error ? error : -EOPNOTSUPP);', prepare)
        self.assertNotIn('lsf_factory_cleanup_task_publish(', prepare)
        self.assertNotIn('lsf_prepaid_cleanup_stack_publish(', prepare)
        self.assertNotIn('wake_up_new_task(', prepare)
        self.assertNotIn('kernel_clone(', prepare)

    def test_source_record_and_slot_limits_are_unchanged(self):
        text = (source.OWNED / 'factory-cleanup-lifecycle.c').read_text()
        self.assertNotIn('alloc_pages(', text)
        self.assertNotIn('kmalloc(', text)
        self.assertNotIn('context->cursor -=', text)
        self.assertNotIn('LSF_BOOTSTRAP_CEILING =', text)
        self.assertEqual(hashlib.sha256(source.FIXTURE.read_bytes()).hexdigest(), source.FIXTURE_SHA)


if __name__ == '__main__':
    unittest.main()
