"""Writer/absence and original-body controls, not execution qualification."""
import unittest
from tools import host_stream_kernel_cleanup_exit_observer as source
from tools.host_stream_kernel_device_security import function


class CleanupExitObserverSource(unittest.TestCase):
    def test_whole_original_bodies_preserved_in_wrappers(self):
        original = source.definition('register_taskstats')
        renamed = original.replace('cmd_attr_register_cpumask(', 'lsf_cleanup_taskstats_register_original(', 1)
        self.assertTrue(source.register_taskstats().startswith(renamed))
        original = source.definition('sys_acct')
        renamed = original.replace('SYSCALL_DEFINE1(acct, const char __user *, name)',
            'static long lsf_cleanup_acct_original(const char __user *name)', 1)
        self.assertTrue(source.enable_accounting().startswith(renamed))
        # Actual allocating writer is the sole REGISTER producer in whole source.
        self.assertEqual(source.definition('add_del_listener').count('list_add('), 1)
        self.assertIn('mask, REGISTER)', source.definition('register_taskstats'))
        self.assertIn('mask, DEREGISTER)', source.definition('deregister_taskstats'))
        self.assertFalse(source.preimages()['actualObserverExecution'])

    def test_taskstats_possible_cpu_heads_and_preparation_are_serialized(self):
        text = (source.OWNED/'taskstats-cleanup-observer.c').read_text()
        seal = function(text, 'int lsf_cleanup_taskstats_prebirth_seal(')
        for token in ('preparing', 'uncertain', 'READ_ONCE(family_registered)',
                      'for_each_possible_cpu(cpu)', 'down_write(&listeners->sem)',
                      'list_empty(&listeners->list)', 'up_write(&listeners->sem)'):
            self.assertIn(token, seal)
        self.assertLess(seal.index('mutex_lock('), seal.index('preparing'))
        self.assertLess(seal.index('list_empty('), seal.index('state.sealed = 1u'))
        wrapper = source.register_taskstats()[source.register_taskstats().index('\nstatic int cmd_attr_register_cpumask('):]
        self.assertLess(wrapper.index('prepare_begin('), wrapper.index('register_original('))
        self.assertLess(wrapper.index('register_original('), wrapper.index('prepare_end('))
        self.assertNotIn('list_del(', text)

    def test_accounting_actual_writer_mutex_and_namespace_extent(self):
        text = (source.OWNED/'acct-cleanup-observer.c').read_text()
        seal = function(text, 'int lsf_cleanup_acct_prebirth_seal(')
        self.assertIn('mutex_lock(&acct_on_mutex)', seal)
        self.assertIn('!READ_ONCE(init_pid_ns.bacct)', seal)
        self.assertIn('!lsf_cleanup_acct_state.preparing', seal)
        wrapper = source.enable_accounting()
        self.assertIn('name && task_active_pid_ns(current) == &init_pid_ns', wrapper)
        self.assertNotIn('pin_kill(', text)
        self.assertIn('acct_on(tmp)', source.definition('sys_acct'))

    def test_exit_hooks_remain_real_and_single_worker_no_tgid_allocation(self):
        original = source.definition('tgid_alloc')
        self.assertLess(original.index('thread_group_empty(tsk)'), original.index('kmem_cache_zalloc('))
        exit_body = source.definition('taskstats_exit')
        self.assertIn('taskstats_tgid_alloc(tsk)', exit_body)
        self.assertLess(exit_body.index('list_empty('), exit_body.index('prepare_reply('))
        self.assertIn('slow_acct_process(', source.definition('acct_process'))

    def test_preparing_and_active_registration_interleavings_source_model(self):
        # The mutex orders begin/seal; actual source retains the count through
        # original writer cleanup. This finite model does not execute Linux.
        for existing in (False, True):
            for begin_first in (False, True):
                sealed, preparing, error = False, 0, False
                if begin_first:
                    preparing += 1
                if existing or preparing:
                    error = True
                else:
                    sealed = True
                if not begin_first:
                    admitted = not sealed
                    self.assertEqual(admitted, existing)
                else:
                    self.assertTrue(error)
                    preparing -= 1
                self.assertFalse(sealed and (existing or preparing))


if __name__ == '__main__':
    unittest.main()
