"""Publication/return source controls. No actual Task, WQ or RCU execution."""
import unittest
from pathlib import Path
from tools import host_stream_kernel_cleanup_provider_queue as source
from tools.host_stream_kernel_device_security import function


class CleanupProviderQueueSource(unittest.TestCase):
    def test_prebirth_guard_and_exact_source_only_status(self):
        text = (source.OWNED/'kthread-cleanup-provider-queue.c').read_text()
        create = function(text, 'int lsf_prepaid_cleanup_provider_create_full(')
        self.assertLess(create.index('lsf_factory_cleanup_provider_profile_ready('),
            create.index('lsf_factory_cleanup_task_reserve('))
        self.assertLess(create.index('lsf_prepaid_cleanup_provider_queue_available('),
            create.index('lsf_factory_cleanup_task_reserve('))
        self.assertLess(create.index('lsf_factory_cleanup_provider_storage_reserve('),
            create.index('lsf_prepaid_cleanup_provider_queue_prepare('))
        for key in ('taskCreated','actualRcuExecution','compiledGeometryFits','consumerSelected'):
            self.assertFalse(source.preimages()[key])

    def test_reader_authentication_publication_and_last_borrow_seal(self):
        text = (source.OWNED/'factory-cleanup-provider-queue.c').read_text()
        get = function(text, 'void *lsf_factory_cleanup_provider_control_get(')
        self.assertLess(get.index('spin_lock_irqsave('), get.index('control_retiring'))
        self.assertLess(get.index('LSF_PREPAID_PUBLISHED'), get.index('control_readers++'))
        self.assertIn('record->deferred != LSF_PREPAID_QUEUED', get)
        seal = function(text, 'int lsf_factory_cleanup_provider_control_seal(')
        self.assertLess(seal.index('control_retiring = 1u'), seal.index('!factory.device->cleanup_provider_control_readers'))
        put = function(text, 'void lsf_factory_cleanup_provider_control_put(')
        self.assertLess(put.index('control_readers--'), put.index('retirement_kick_held('))

    def test_actual_original_queue_registration_and_termination_order(self):
        text = (source.OWNED/'acpi-cleanup-provider-queue.c').read_text()
        acquire = function(text, 'int lsf_prepaid_acpi_provider_queue_acquire(')
        self.assertLess(acquire.index('control_get('), acquire.index('mutex_lock('))
        self.assertIn('*queue = kacpi_hotplug_wq', acquire)
        unregister = function(text, 'void lsf_prepaid_acpi_provider_queue_unregister(')
        self.assertLess(unregister.index('registration = NULL'), unregister.index('control_put(candidate)'))
        terminate = function(text, 'static void lsf_prepaid_acpi_provider_terminate(')
        self.assertLess(terminate.index('queue_state(false)'), terminate.index('queue_terminate(control)'))
        self.assertNotIn('destroy_workqueue(', terminate)  # original caller retains all three destroys

    def test_same_release_worker_barrier_and_actual_control_last_access(self):
        text = (source.OWNED/'workqueue-cleanup-provider-queue.c').read_text()
        prepare = function(text, 'int lsf_prepaid_cleanup_provider_queue_prepare(')
        self.assertLess(prepare.index('part_publish('), prepare.index('queue_acquire('))
        self.assertLess(prepare.index('put_pwq_unlocked(private)'),
            prepare.index('kthread_queue_work(pwq_release_worker, &control->release_barrier)'))
        self.assertIn('wait_for_completion(&control->unlinked_released)', prepare)
        retire = function(text, 'static void lsf_provider_retire_handoff(struct kthread_work *work)\n')
        for token in ('control_seal(', 'kthread_flush_work(&control->handoff)',
                      'kthread_flush_work(&control->release_barrier)', 'atomic_set(&control->retire_pending, 2)'):
            self.assertLess(retire.index(token), retire.index('LSF_PROVIDER_CONTROL, control'))
        self.assertLess(retire.index('LSF_PROVIDER_CONTEXT, context'), retire.index('LSF_PROVIDER_CONTROL, control'))

    def test_original_pwq_keeps_original_provider_reference_and_bootstrap_sum(self):
        tool = Path(source.__file__).read_text()
        for token in ('original->plugged = true', 'link_pwq(original)',
                      'control->private->pwqs_node.next != &original->pwqs_node',
                      'original->pwqs_node.next != &wq->pwqs'):
            self.assertIn(token, tool)
        self.assertIn('LSF_BACKING_BYTES + 2u * sizeof(void *) + lsf_prepaid_acpi_provider_bootstrap_bytes()', tool)
        static = (source.OWNED/'acpi-cleanup-provider-queue.c').read_text()
        for token in ('sizeof(lsf_acpi_provider_lifetime_mutex)', 'sizeof(lsf_acpi_provider_registration)',
                      'sizeof(lsf_acpi_reference_queue_lock)', 'sizeof(lsf_acpi_reference_queue_live)'):
            self.assertIn(token, static)


if __name__ == '__main__':
    unittest.main()
