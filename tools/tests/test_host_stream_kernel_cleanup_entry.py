"""Private entry source/handshake guards; no executed Linux task claim."""
from pathlib import Path
import unittest
from tools import host_stream_kernel_cleanup_entry as source


class CleanupEntrySource(unittest.TestCase):
    def test_origin_and_claims_are_closed(self):
        value = source.preimages()
        self.assertEqual(len(value['sections']), 2)
        self.assertFalse(value['taskCreated'])
        self.assertFalse(value['fullConstructorClosure'])
        with self.assertRaisesRegex(ValueError, 'cleanup-entry-whole-membership'):
            source.transform({}, {})

    def test_actual_fixed_task_request_and_callback_identity_precede_reads(self):
        text = source.private_entry()
        guard = text.index('lsf_factory_cleanup_entry_current(&request_address, &metadata_address)')
        self.assertLess(guard, text.index('source = owned->source;'))
        self.assertLess(guard, text.index('threadfn = create->threadfn;'))
        for check in ('_create != &owned->create', 'owned->create.threadfn != kthread_worker_fn',
                'owned->create.data != &owned->worker', 'owned->create.full_name != owned->name',
                'current->vfork_done != &self->exited'):
            self.assertIn(check, text)

    def test_interrupted_creator_exits_without_giving_bank_storage_to_heap(self):
        old = source.preimages()['sections']['kthread']['text']
        self.assertIn('kfree(create->full_name);\n\t\tkfree(create);', old)
        text = source.private_entry()
        branch = text[text.index('\tdone = xchg(&create->done, NULL);'):
            text.index('\tself->full_name = create->full_name;')]
        self.assertIn('if (!done)', branch)
        self.assertIn('kthread_exit(-EINTR);', branch)
        self.assertNotIn('kfree(', text)
        self.assertNotIn('lsf_device_finish(', text)
        self.assertNotIn('complete(done)', branch)

    def test_entire_original_run_park_stop_scheduler_tail_is_exact(self):
        old = source.preimages()['sections']['kthread']['text']
        new = source.private_entry()
        anchor = '\tself->full_name = create->full_name;\n'
        self.assertEqual(old[old.index(anchor):], new[new.index(anchor):])
        tail = new[new.index(anchor):]
        self.assertIn('sched_setscheduler_nocheck(current, SCHED_NORMAL, &param);', tail)
        self.assertIn('set_cpus_allowed_ptr(current, housekeeping_cpumask(HK_TYPE_KTHREAD));', tail)
        self.assertIn('cgroup_kthread_ready();', tail)
        self.assertIn('__kthread_parkme(self);', tail)
        self.assertNotIn('create->', tail.split('\tcomplete(done);', 1)[1])

    def test_invalid_request_notifies_only_the_actual_owned_borrowed_completion(self):
        text = source.private_entry()
        branch = text[text.index('    if (_create != &owned->create'):
            text.index('    create = &owned->create;')]
        self.assertIn('done = xchg(&owned->create.done, NULL);', branch)
        self.assertIn('owned->create.result = ERR_PTR(-EIO);', branch)
        self.assertNotIn('owned->', branch.split('complete(done);', 1)[1])
        self.assertIn('kthread_exit(-EIO);', branch)

    def test_entry_claim_is_single_current_task_generation_bound_and_lock_scoped(self):
        text = (source.OWNED / 'factory-cleanup-entry.c').read_text()
        check = text.index('lsf_cleanup_lifecycle_identity_locked(source, current)')
        self.assertLess(check, text.index('current->worker_private'))
        self.assertIn('factory.device->cleanup_entry_started', text)
        self.assertIn('metadata->cache_anchor != source.task.generation', text)
        self.assertIn('metadata->deferred != LSF_PREPAID_PUBLISHED', text)
        self.assertNotIn('complete(', text)
        self.assertNotIn('wake_up_process(', text)
        self.assertNotIn('put_task_struct(', text)


if __name__ == '__main__':
    unittest.main()
