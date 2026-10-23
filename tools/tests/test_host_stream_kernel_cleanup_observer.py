"""Real observer publishers, error replies and prebirth retirement ordering."""
import re
import unittest
from tools import host_stream_kernel_cleanup_observer as source
from tools.host_stream_kernel_device_security import function


def ordinary(text):
    return re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', text, flags=re.S)


class CleanupObserverSource(unittest.TestCase):
    def test_exact_selected_sources_and_no_execution_or_consumer_claim(self):
        value = source.preimages()
        self.assertEqual(len(value['source']), 14)
        self.assertEqual(value['selected']['CONFIG_KRETPROBE_ON_RETHOOK'], 'y')
        for key in ('sealExecuted', 'factoryCallsObserverEnter', 'factoryCallsFullWorkerCreate',
                    'pendingConsumerCallsFullClone', 'physicalBackingReturned', 'observerClosure'):
            self.assertFalse(value[key])
        with self.assertRaisesRegex(ValueError, 'cleanup-observer-whole-membership'):
            source.transform({}, {})

    def test_tracepoint_publish_and_remove_project_to_full_ordinary_bodies(self):
        self.assertEqual(ordinary(source.trace_add()), source.definition('trace_add'))
        self.assertEqual(ordinary(source.trace_remove()), source.definition('trace_remove'))
        add = source.trace_add()
        self.assertLess(add.index('lsf_cleanup_tracepoint_state.sealed'), add.index('tp->regfunc'))
        self.assertLess(add.index('lsf_cleanup_tracepoint_state.sealed'), add.index('func_add('))
        self.assertGreater(add.index('lsf_cleanup_tracepoint_state.heads++'),
            add.rindex('rcu_assign_pointer(tp->funcs'))
        remove = source.trace_remove()
        self.assertGreater(remove.index('lsf_cleanup_tracepoint_state.heads--'),
            remove.rindex('rcu_assign_pointer(tp->funcs'))
        self.assertIn('if (old && !tp_funcs)', remove)
        self.assertIn('tp_funcs == old', remove) # Original stub-on-ENOMEM remains.

    def test_module_metadata_check_precedes_taint_skip_and_keeps_original_body(self):
        text = source.module_coming()
        self.assertLess(text.index('lsf_cleanup_tracepoint_module_check'),
            text.index('trace_module_has_bad_taint'))
        self.assertEqual(ordinary(text), source.definition('module_coming'))
        helper = (source.OWNED/'tracepoint-cleanup-observer.c').read_text()
        check = function(helper, 'static int lsf_cleanup_tracepoint_module_check(')
        self.assertLess(check.index('mutex_lock(&tracepoint_module_list_mutex)'),
            check.index('mutex_lock(&tracepoints_mutex)'))
        self.assertLess(check.index('error = -EOPNOTSUPP'), check.index('mutex_unlock(&tracepoints_mutex)'))
        self.assertNotIn('READ_ONCE', check)
        bad = check[check.index('if (trace_module_has_bad_taint(mod))'):
            check.index('for_each_tracepoint_in_module(mod,')]
        self.assertIn('error = -EOPNOTSUPP', bad)
        self.assertIn('lsf_cleanup_tracepoint_state.uncertain = 1u', bad)
        self.assertIn('goto out;', bad)
        self.assertNotIn('for_each_tracepoint', bad)
        self.assertLess(check.index('out:\n'), check.index('mutex_unlock(&tracepoints_mutex)'))

    def test_tracepoint_sync_outside_both_mutexes_then_locked_recheck(self):
        text = function((source.OWNED/'tracepoint-cleanup-observer.c').read_text(),
            'int lsf_cleanup_tracepoint_prebirth_seal(')
        before, after = text.split('tracepoint_synchronize_unregister();')
        self.assertLess(before.index('mutex_lock(&tracepoint_module_list_mutex)'),
            before.index('mutex_lock(&tracepoints_mutex)'))
        self.assertIn('mutex_unlock(&tracepoints_mutex)', before)
        self.assertIn('mutex_unlock(&tracepoint_module_list_mutex)', before)
        self.assertLess(after.index('mutex_lock(&tracepoints_mutex)'),
            after.index('lsf_cleanup_tracepoints_observed_locked()'))
        sync = source.definition('trace_sync')
        self.assertIn('synchronize_srcu(&tracepoint_srcu)', sync)
        self.assertIn('synchronize_rcu()', sync)

    def test_kprobe_rejects_under_actual_mutex_before_preparation_and_retains_out(self):
        text = source.register_kprobe()
        self.assertEqual(ordinary(text), source.definition('register_kprobe'))
        self.assertLess(text.index('mutex_lock(&kprobe_mutex)'), text.index('lsf_cleanup_kprobe_observers.sealed'))
        self.assertLess(text.index('lsf_cleanup_kprobe_observers.sealed'), text.index('register_aggr_kprobe('))
        self.assertLess(text.index('lsf_cleanup_kprobe_observers.sealed'), text.index('prepare_kprobe('))
        self.assertIn('module_put(probed_mod)', text)

    def test_complete_original_kretprobe_preparation_inside_real_extent(self):
        text = source.register_kretprobe()
        actual = function(text, 'static int lsf_cleanup_original_register_kretprobe(')
        actual = source.replace(actual,
            'static int lsf_cleanup_original_register_kretprobe(struct kretprobe *rp)\n',
            'int register_kretprobe(struct kretprobe *rp)\n')
        self.assertEqual(actual, source.definition('register_kretprobe'))
        wrapper = function(text, 'int register_kretprobe(')
        self.assertLess(wrapper.index('lsf_cleanup_kretprobe_prepare_begin()'),
            wrapper.index('lsf_cleanup_original_register_kretprobe(rp)'))
        self.assertLess(wrapper.index('lsf_cleanup_original_register_kretprobe(rp)'),
            wrapper.index('lsf_cleanup_kretprobe_prepare_end()'))
        self.assertIn('rethook_free(rp->rh)', actual)
        self.assertIn('free_rp_inst(rp)', actual)

    def test_unregister_retirement_extent_keeps_actual_rcu_rethook_and_arch_tails(self):
        for key, typ, arg in [('unregister_kprobes', 'struct kprobe', 'kps'),
                              ('unregister_kretprobes', 'struct kretprobe', 'rps')]:
            text = source.unregister(key, typ, arg)
            actual = function(text, f'static void lsf_cleanup_original_{key}(')
            actual = source.replace(actual,
                f'static void lsf_cleanup_original_{key}({typ} **{arg}, int num)\n',
                f'void {key}({typ} **{arg}, int num)\n')
            self.assertEqual(actual, source.definition(key))
            self.assertIn('synchronize_rcu()', actual)
            self.assertIn('__unregister_kprobe_bottom(', actual)
            wrapper = function(text, f'void {key}(')
            self.assertLess(wrapper.index('lsf_cleanup_kprobe_retire_begin()'),
                wrapper.index(f'lsf_cleanup_original_{key}({arg}, num)'))
            self.assertLess(wrapper.index(f'lsf_cleanup_original_{key}({arg}, num)'),
                wrapper.index('lsf_cleanup_kprobe_retire_end()'))
        self.assertIn('rethook_free(rps[i]->rh)', source.definition('unregister_kretprobes'))
        self.assertIn('rcu_assign_pointer(rh->handler, NULL)', source.definition('rethook_stop'))
        self.assertIn('if (handler)', source.definition('rethook_trampoline'))
        self.assertIn('text_poke_sync()', source.definition('arch_disarm'))
        self.assertIn('synchronize_rcu_tasks()', source.definition('optimizer'))

    def test_kprobe_seal_refuses_preparing_retiring_and_waits_outside_mutex(self):
        all_text = (source.OWNED/'kprobe-cleanup-observer.c').read_text()
        observed = function(all_text, 'static int lsf_cleanup_kprobes_observed_locked(')
        for field in ('preparing', 'retiring', 'uncertain'):
            self.assertIn('lsf_cleanup_kprobe_observers.' + field, observed)
        self.assertIn('hlist_empty(&kprobe_table[i])', observed)
        text = function(all_text, 'int lsf_cleanup_kprobe_prebirth_seal(')
        self.assertLess(text.index('mutex_unlock(&kprobe_mutex)'), text.index('wait_for_kprobe_optimizer()'))
        self.assertLess(text.index('wait_for_kprobe_optimizer()'), text.index('flush_delayed_work(&optimizing_work)'))
        self.assertLess(text.index('synchronize_rcu()'), text.rindex('lsf_cleanup_kprobes_observed_locked()'))
        self.assertLess(text.index('rcu_barrier()'), text.rindex('lsf_cleanup_kprobes_observed_locked()'))
        self.assertIn('!list_empty(&freeing_list)', text)

    def test_connector_listener_guard_and_real_unicast_unsupported_reply(self):
        text = source.connector_control()
        self.assertEqual(ordinary(text), source.definition('connector_ctl'))
        self.assertLess(text.index('mutex_lock(&lsf_cleanup_connector_state.mutex)'), text.index('kzalloc('))
        self.assertLess(text.index('lsf_cleanup_connector_state.sealed'),
            text.index('atomic_inc(&proc_event_num_listeners)'))
        refusal = text[text.index('if (mc_op == PROC_CN_MCAST_LISTEN'):text.index('\tif (nsp->sk)')]
        self.assertLess(refusal.index('mutex_unlock('), refusal.index('lsf_cleanup_cn_proc_reject(EOPNOTSUPP'))
        self.assertNotIn('atomic_inc', refusal)
        ack = source.connector_reject()
        self.assertIn('nsp->portid, 0, GFP_KERNEL, NULL, NULL', ack)
        self.assertNotIn('proc_event_num_listeners', ack)
        for field in ('msg->seq = rcvd_seq', 'msg->ack = rcvd_ack + 1',
                      'ev->what = PROC_EVENT_NONE', 'ev->event_data.ack.err = err'):
            self.assertIn(field, ack)
        # The original multicast ack remains unchanged in the transform.
        self.assertIn('atomic_read(&proc_event_num_listeners) < 1', source.definition('connector_ack'))

    def test_actual_static_geometry_prebank_rollback_and_unselected_entry(self):
        for name, state in [('tracepoint', 'lsf_cleanup_tracepoint_state'),
                            ('kprobe', 'lsf_cleanup_kprobe_observers'),
                            ('connector', 'lsf_cleanup_connector_state')]:
            text = (source.OWNED/f'{name}-cleanup-observer.c').read_text()
            self.assertIn(f'return sizeof({state});', text)
        factory = (source.OWNED/'factory-cleanup-observer.c').read_text()
        rollback = function(factory, 'static int __maybe_unused lsf_cleanup_observers_prebank_rollback(')
        self.assertLess(rollback.index('factory.pages || factory.opened || factory.device'),
            rollback.index('lsf_cleanup_connector_prebirth_rollback()'))
        fits = function(factory, 'static int lsf_cleanup_bootstrap_fits(')
        self.assertIn('sizeof(factory)', fits)
        self.assertIn('observers <= LSF_BOOTSTRAP_CEILING - fixed - irq', fits)
        self.assertIn('static int __maybe_unused lsf_cleanup_observers_prebank_enter', factory)


if __name__ == '__main__':
    unittest.main()
