"""Actual association geometry, opener authority and wake outside locks."""
import unittest
from tools import host_stream_kernel_cleanup_association as source


class CleanupAssociationSource(unittest.TestCase):
    def test_genuine_constructor_tail_and_unselected_gates(self):
        value = source.preimages()
        original = value['sections']['worker_constructor']['text']
        self.assertIn('worker->flags = flags;\n\tworker->task = task;\n\twake_up_process(task);', original)
        self.assertFalse(value['factoryCallsFullWorkerCreate'])
        self.assertFalse(value['pendingConsumerCallsFullClone'])
        self.assertFalse(value['fullConstructorClosure'])
        with self.assertRaisesRegex(ValueError, 'cleanup-association-whole-membership'):
            source.transform({}, {})

    def test_actual_request_offset_and_worker_size(self):
        text = (source.OWNED/'kernel-cleanup-association.c').read_text()
        self.assertIn('sizeof(struct lsf_cleanup_request)', text)
        self.assertIn('offsetof(struct lsf_cleanup_request, worker)', text)
        self.assertIn('sizeof(struct kthread_worker)', text)

    def test_birth_and_actor_before_first_foreign_field(self):
        text = (source.OWNED/'factory-cleanup-association.c').read_text()
        for guard in ('lsf_cleanup_lifecycle_identity_locked(source, task)',
                      'current->mm != factory.mm', 'current_cred() != factory.cred',
                      '(void *)worker != (char *)request_address + worker_offset'):
            self.assertLess(text.index(guard), text.index('refcount_read(&task->usage)'))
        self.assertLess(text.index('refcount_read(&task->usage)'), text.index('worker->task = task'))
        self.assertIn('cleanup_worker_associated = 1', text)
        self.assertNotIn('wake_up_process(', text)


if __name__ == '__main__':
    unittest.main()
