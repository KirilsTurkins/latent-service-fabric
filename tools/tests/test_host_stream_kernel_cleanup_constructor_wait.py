"""Source ownership controls; these do not execute Linux Task/RCU lifetimes."""
import unittest
from pathlib import Path
from tools import host_stream_kernel_cleanup_constructor_wait as source
from tools.host_stream_kernel_device_security import function


class CleanupConstructorWaitSource(unittest.TestCase):
    def test_birth_completion_is_paid_and_no_unbounded_completion_fallback(self):
        text = (source.OWNED/'kthread-cleanup-provider-constructor.c').read_text()
        self.assertNotIn('ONSTACK', text)
        self.assertNotIn('wait_for_completion(', text)
        self.assertIn('owned->create.done = done;', text)
        self.assertLess(text.index('birth_wait_get('), text.index('provider_open_request('))
        self.assertLess(text.index('provider_submit('), text.index('WRITE_ONCE(lsf_cleanup_pending'))
        interrupted = text[text.index('    if (waited <= 0'):]
        self.assertLess(interrupted.index('!xchg(&owned->create.done, NULL)'),
            interrupted.index('birth_wait_put(control, 1)'))
        self.assertLess(interrupted.index('birth_wait_put(control, 1)'),
            interrupted.index('LSF_CLEANUP_REQUEST_OPENER'))

    def test_late_completer_retains_complete_graph_before_reader_drop(self):
        text = (source.OWNED/'workqueue-cleanup-provider-constructor.c').read_text()
        put = function(text, 'void lsf_prepaid_cleanup_provider_birth_wait_put(')
        self.assertLess(put.index('constructor_quarantined, 1'), put.index('provider_hold('))
        self.assertLess(put.index('provider_hold('), put.index('control_put(control)'))
        self.assertNotIn('preparing, 0', put)
        self.assertNotIn('part_finish(', put)
        get = function(text, 'void *lsf_prepaid_cleanup_provider_birth_wait_get(')
        self.assertLess(get.index('storage_current(source, LSF_PROVIDER_CONTROL'), get.index('&control->born'))
        self.assertLess(get.index('storage_current(source, LSF_PROVIDER_WORKER'), get.index('&control->born'))
        self.assertLess(get.index('waiter_current(source)'), get.index('&control->born'))

    def test_readiness_budget_only_narrows_and_timeout_closes_without_refund(self):
        text = (source.OWNED/'workqueue-cleanup-provider-constructor.c').read_text()
        wait = function(text, 'int lsf_prepaid_cleanup_provider_wait_ready(')
        self.assertIn('remaining > MAX_JIFFY_OFFSET', wait)
        self.assertIn('min(remaining, lsf_prepaid_cleanup_provider_birth_remaining(control))', wait)
        self.assertLess(wait.index('control_get(NULL)'), wait.index('control->source'))
        self.assertLess(wait.index('wait_for_completion_killable_timeout'), wait.index('control_put(control)'))
        self.assertIn('waiter_cancel(source)', wait)
        self.assertNotIn('part_finish(', wait)
        self.assertNotIn('put_task_struct(', wait)
        factory = (source.OWNED/'factory-cleanup-provider-constructor.c').read_text()
        cancel = function(factory, 'void lsf_factory_cleanup_provider_waiter_cancel(')
        self.assertLess(cancel.index('lsf_provider_original_opener_locked(source)'),
            cancel.index('cleanup_provider_close_requested = 1u'))
        self.assertLess(cancel.index('spin_unlock_irqrestore'), cancel.index('lsf_cleanup_admission_close()'))

    def test_termination_condition_reauthenticates_under_actual_lifetime_mutex(self):
        text = (source.OWNED/'acpi-cleanup-provider-constructor.c').read_text()
        condition = function(text, 'static bool lsf_acpi_provider_constructor_settled(')
        self.assertLess(condition.index('mutex_lock('), condition.index('lsf_acpi_provider_registration'))
        self.assertLess(condition.index('queue_pending('), condition.index('mutex_unlock('))
        terminate = function(text, 'static void lsf_prepaid_acpi_provider_terminate(')
        self.assertLess(terminate.index('queue_pending(control) == 0'), terminate.index('queue_unregister(control)'))
        self.assertLess(terminate.rindex('mutex_unlock('), terminate.index('wait_event('))
        self.assertNotIn('destroy_workqueue(', terminate)
        pending = function((source.OWNED/'workqueue-cleanup-provider-constructor.c').read_text(),
            'int lsf_prepaid_cleanup_provider_queue_pending(')
        self.assertIn('constructor_quarantined', pending)
        self.assertIn('completion_done(&control->unlinked_released)', pending)
        self.assertIn('READ_ONCE(control->wq) != NULL', pending)

    def test_original_open_publication_and_static_geometry_remain_explicit(self):
        tool = Path(source.__file__).read_text()
        self.assertIn("old.index('    factory.opened = 1;", tool)
        self.assertIn('mutex_unlock(&factory_lock);', tool)
        self.assertIn('mutex_lock(&factory_lock);', tool)
        self.assertIn('sizeof(lsf_acpi_provider_constructor_wait)', tool)
        self.assertIn('struct completion born;', tool)
        self.assertIn('unsigned long constructor_expires;', tool)
        self.assertIn('return -EINPROGRESS;', tool)
        value = source.preimages()
        for name in ('actualLinuxExecution','initialBirthBounded','consumerSelected',
            'completeAllocationClosure','productionInstallation'):
            self.assertFalse(value[name])


if __name__ == '__main__':
    unittest.main()
