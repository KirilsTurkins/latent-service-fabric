"""Source-preserve actual waiter algorithms; no Linux callback execution claim."""
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_notifications as notification


class KernelDeviceNotificationSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = notification.fixture()

    def setUp(self):
        cache = patch.object(notification, 'fixture', return_value=self.value)
        cache.start()
        self.addCleanup(cache.stop)

    def raw(self, name):
        return self.value['sections'][name]['text']

    def test_original_parent_and_all_uninstalled_callback_gates_are_exact(self):
        parent = notification.prior.fixture()
        self.assertEqual((len(self.value['source']), len(self.value['sections'])), (101, 172))
        for key in ('source', 'sections'):
            self.assertEqual({name: self.value[key][name] for name in parent[key]}, parent[key])
        self.assertTrue(all(self.value[key] is False for key in notification.GATES))

    def test_duplicate_changed_crlf_and_unknown_preimages_refuse(self):
        for name in notification.DEFINITIONS:
            raw = self.raw(name)
            self.assertEqual(notification.section(raw, name), raw)
            for wrong in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('(', '( ', 1)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    notification.section(wrong, name)
        with self.assertRaises(KeyError):
            notification.section('', 'unknown_callback')

    def test_poll_barrier_task_and_original_wake_algorithm_are_exact(self):
        private = notification.private_poll({'fs/select.c':
            (self.raw('__pollwake') + self.raw('pollwake')).encode()})
        inner = notification.prior.function(private, 'static int lsf_prepaid_device_pollwake_inner(')
        self.assertEqual(inner.replace('lsf_prepaid_device_pollwake_inner(', '__pollwake('), self.raw('__pollwake'))
        outer = notification.prior.function(private, 'int lsf_prepaid_device_pollwake(')
        guard = ('\n\t/* The real waitqueue lock still protects this entry/function. */\n'
            '\tif (!lsf_factory_device_recipient_current(source, NULL))\n'
            '\t\treturn -EOPNOTSUPP;\n'
            '\tif (wait->func != pollwake) {\n'
            '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
        self.assertLess(outer.index(guard), outer.index('entry = container_of'))
        outer = outer.replace(guard, '').replace('int lsf_prepaid_device_pollwake('
            'struct lsf_device_registration_source source, ', 'static int pollwake(')
        outer = outer.replace('lsf_prepaid_device_pollwake_inner(', '__pollwake(')
        self.assertEqual(outer, self.raw('pollwake'))

    def test_callback_preflight_is_inside_original_lock_before_any_dispatch(self):
        private = notification.private_wait({'kernel/sched/wait.c':
            (self.raw('__wake_up_common') + self.raw('__wake_up_common_lock')).encode()})
        common = notification.prior.function(private, 'static int lsf_prepaid_device_wake_common(')
        self.assertLess(common.index('lockdep_assert_held(&wq_head->lock)'),
            common.index('list_for_each_entry(curr, &wq_head->head, entry)'))
        self.assertLess(common.index('*error = -EOPNOTSUPP;'), common.index('ret = curr->func('))
        self.assertLess(common.index('lsf_factory_device_uevent_poison();'), common.index('ret = curr->func('))
        self.assertIn('curr->func != default_wake_function', common)
        self.assertIn('curr->func != autoremove_wake_function', common)
        self.assertIn('!lsf_prepaid_device_pollwake_matches(curr->func)', common)
        self.assertIn('!lsf_prepaid_device_epoll_matches(curr->func)', common)
        self.assertNotIn('io_poll_wake', common)
        self.assertFalse(self.value['completeWaitCallbackSet'])
        wrapper = notification.prior.function(private, 'int lsf_prepaid_device_wake(')
        self.assertLess(wrapper.index('spin_lock_irqsave'), wrapper.index('lsf_prepaid_device_wake_common'))
        self.assertLess(wrapper.index('lsf_prepaid_device_wake_common'), wrapper.index('spin_unlock_irqrestore'))
        self.assertIn('return error ? error : nr_exclusive - remaining;', wrapper)

    def test_epoll_keeps_actual_notifications_nesting_pm_and_pollfree_tail(self):
        originals = ''.join(self.raw(name) for name in ('ep_poll_callback',
            'ep_poll_safewake_debug', 'ep_poll_safewake_normal'))
        private = notification.private_epoll({'fs/eventpoll.c': originals.encode()})
        outer = notification.prior.function(private, 'int lsf_prepaid_device_epoll_callback(')
        self.assertLess(outer.index('lsf_factory_device_recipient_current(source, NULL)'),
            outer.index('epi = ep_item_from_wait(wait)'))
        self.assertIn('ep_set_busy_poll_napi_id(epi);', outer)
        self.assertEqual(outer.count('ep_pm_stay_awake_rcu(epi);'), 2)
        self.assertLess(outer.index('spin_unlock_irqrestore(&ep->lock, flags)'),
            outer.index('lsf_prepaid_device_epoll_safewake(source'))
        original = self.raw('ep_poll_callback')
        # All real POLLFREE cleanup executes before the new closed-error return.
        tail = original[original.index('\tif (pollflags & POLLFREE) {'):original.index('\treturn ewake;')]
        self.assertIn(tail, outer)
        self.assertLess(outer.index('smp_store_release(&ep_pwq_from_wait(wait)->whead, NULL)'),
            outer.index('return error < 0 ? error : ewake;'))
        self.assertIn('#ifdef CONFIG_DEBUG_LOCK_ALLOC\n', private)
        self.assertIn('spin_lock_irqsave_nested(&ep->poll_wait.lock, flags, nests);', private)
        self.assertIn('ep->nests = 0;', private)
        self.assertIn('lsf_prepaid_device_wake_locked(source', private)
        self.assertIn('lsf_prepaid_device_wake(source', private)

    def test_socket_notification_keeps_trace_rcu_and_original_wake_selection(self):
        private = notification.private_socket_notifications({'net/core/sock.c':
            (self.raw('sock_def_readable') + self.raw('sock_def_error_report')).encode()})
        guard = ('\tif (!sk || !lsf_factory_device_recipient_current(source, sk)) {\n'
            '\t\tlsf_factory_device_uevent_poison();\n\t\treturn -EOPNOTSUPP;\n\t}\n')
        for original, renamed in [('sock_def_readable', 'lsf_prepaid_device_sock_readable'),
                                  ('sock_def_error_report', 'lsf_prepaid_device_sock_error')]:
            raw = notification.prior.function(private, 'static int ' + renamed + '(')
            self.assertLess(raw.index(guard), raw.index('rcu_read_lock();'))
            self.assertIn('wq = rcu_dereference(sk->sk_wq);', raw)
            self.assertLess(raw.index('rcu_read_unlock();'),
                raw.index('return result < 0 ? result :'))
            raw = raw.replace('\tint result = 0;\n\n' + guard, '')
            raw = raw.replace('\trcu_read_unlock();\n\treturn result < 0 ? result :\n'
                '\t\t(lsf_factory_device_recipient_current(source, sk) ? 0 : -EOPNOTSUPP);\n',
                '\trcu_read_unlock();\n')
            raw = raw.replace('lsf_prepaid_device_sk_wake_async_rcu(source, sk,', 'sk_wake_async_rcu(sk,')
            raw = raw.replace('static int ' + renamed +
                '(struct lsf_device_registration_source source, ',
                ('static void ' if original == 'sock_def_error_report' else 'void ') + original + '(')
            raw = raw.replace('\t\tresult = lsf_prepaid_device_wake_sync(source, &wq->wait, TASK_INTERRUPTIBLE,\n'
                '\t\t\tpoll_to_key(EPOLLIN | EPOLLPRI | EPOLLRDNORM | EPOLLRDBAND));\n',
                '\t\twake_up_interruptible_sync_poll(&wq->wait, EPOLLIN | EPOLLPRI |\n'
                '\t\t\t\t\t\tEPOLLRDNORM | EPOLLRDBAND);\n')
            raw = raw.replace('\t\tresult = lsf_prepaid_device_wake(source, &wq->wait, TASK_INTERRUPTIBLE,\n'
                '\t\t\t1, 0, poll_to_key(EPOLLERR));\n',
                '\t\twake_up_interruptible_poll(&wq->wait, EPOLLERR);\n')
            self.assertEqual(raw, self.raw(original))
        dispatch = notification.prior.function(private, 'int lsf_prepaid_device_socket_notify(')
        self.assertLess(dispatch.index('if (!sk || !lsf_factory_device_recipient_current(source, sk))'),
            dispatch.index('READ_ONCE(sk->sk_error_report)'))
        self.assertIn('callback == sock_def_error_report', dispatch)
        self.assertIn('callback == sock_def_readable', dispatch)
        self.assertNotIn('callback(sk)', dispatch)
        self.assertFalse(self.value['instrumentationAdmissionQualified'])


if __name__ == '__main__':
    unittest.main()
