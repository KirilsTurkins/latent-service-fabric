"""Actual C custody/pending guards and exact source projections; no Linux run."""
import ast
import hashlib
import re
import unittest

from tools import host_stream_kernel_late_fd_final_free as source
from tools import host_stream_kernel_root_final_free as prior
from tools.host_stream_kernel_cleanup_native import function
from tools.tests.test_host_stream_kernel_task_identity_geometry import calculate


def original_outputs():
    return prior.transform({name: row['text'].encode()
        for name, row in prior.preimages()['parentDerived'].items()})


def helpers():
    return (source.OWNED/'factory-cleanup-late-fd-final-free.c').read_text()


def condition(expression, changes=None):
    """Interpret operands from the actual C predicate, never a mirror machine."""
    values = dict(file=1, factory_pointer=2, file_private_data=2, file_f_cred=3,
        factory_opened=1, factory_pages=1, factory_device=1, factory_mm=1,
        factory_tgid=1, factory_cred=3, factory_net=1, factory_pool_initialized=1,
        factory_uncertain=0, factory_pool_poisoned=0,
        factory_device_cleanup_request_returned=1, pending=1, took=0)
    values.update(changes or {})
    expression = expression.replace('READ_ONCE(factory.uncertain)', 'factory.uncertain')
    expression = expression.replace('lsf_cleanup_root_release_take_locked(&release)', 'took')
    members = set(re.findall(r'\b(?:factory|file)(?:(?:\.|->)[a-z0-9_]+)+', expression))
    for member in sorted(members, key=len, reverse=True):
        expression = expression.replace(member, member.replace('->', '_').replace('.', '_'))
    expression = expression.replace('&factory', 'factory_pointer')
    expression = expression.replace('||', ' or ').replace('&&', ' and ')
    expression = re.sub(r'\b(\d+)u\b', r'\1', expression)
    expression = re.sub(r'!(?!=)', ' not ', expression)
    return calculate(ast.parse(' '.join(expression.split()), mode='eval'), values)


class LateFdRootSource(unittest.TestCase):
    def test_whole_parent_identities_and_function_edits_fail_closed(self):
        parents = original_outputs()
        for name, row in source.preimages()['parentDerived'].items():
            if name == 'kernel/kthread.c':
                continue  # Whole binding is checked in actual composition, not a fake full file.
            self.assertEqual((len(parents[name]), hashlib.sha256(parents[name]).hexdigest()),
                (row['bytes'], row['sha256']))
        with self.assertRaisesRegex(ValueError, 'parent-whole-preimage'):
            source.authenticate(parents)  # Missing full original kthread is never accepted.
        for name in source.preimages()['parentDerived']:
            changed = dict(parents, **{name: b'foreign kernel input'})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'parent-whole-preimage'):
                source.authenticate(changed)
        old = source.preimages()['kthreadd']['text']
        with self.assertRaisesRegex(ValueError, 'exact-kthreadd-function'):
            source.kthreadd_function(old+'\n')
        for name, editor in (('net/factory.c', source.factory),
                ('net/factory-cleanup-root-final-free.c', source.collector)):
            self.assertNotEqual(editor(parents[name].decode()), parents[name].decode())

    def test_actual_final_file_custody_guard_accepts_closed_pending_without_ready_invention(self):
        body = function(helpers(), 'static int lsf_cleanup_root_fd_handoff_locked(')
        predicate = re.search(r'    if \((.*?)\)\n        goto out;', body, re.S)[1]
        self.assertFalse(condition(predicate))
        for member, bad in (('file', 0), ('file_private_data', 0), ('file_f_cred', 4),
                ('factory_opened', 0), ('factory_opened', 2), ('factory_pages', 0),
                ('factory_device', 0), ('factory_mm', 0), ('factory_tgid', 0),
                ('factory_cred', 0), ('factory_net', 0), ('factory_pool_initialized', 0)):
            with self.subTest(member=member, bad=bad):
                self.assertTrue(condition(predicate, {member:bad}))
        self.assertNotIn('bootstrap_state', body)
        self.assertNotIn('cleanup_request_returned', body)
        self.assertNotIn('current_cred()', body)
        self.assertLess(body.index('factory.opened = 2u'), body.index('file->private_data = NULL'))
        self.assertNotIn('factory.opened = 0', helpers())

    def test_actual_cheap_pending_excludes_in_progress_poison_and_disappeared_owner(self):
        body = function(helpers(), 'static int lsf_cleanup_root_pending_locked(')
        predicate = re.search(r'    return (.*?);', body, re.S)[1]
        self.assertTrue(condition(predicate, {'factory_opened':2}))
        for member, bad in (('factory_opened', 1), ('factory_opened', 0),
                ('factory_pages', 0), ('factory_device', 0), ('factory_uncertain', 1),
                ('factory_pool_poisoned', 1), ('factory_device_cleanup_request_returned', 0)):
            with self.subTest(member=member):
                self.assertFalse(condition(predicate, {'factory_opened':2, member:bad}))
        public = function(helpers(), 'int lsf_factory_cleanup_root_pending(')
        self.assertIn('spin_lock_irqsave(&pool_lock, flags)', public)
        for forbidden in ('mutex_lock', 'file->', 'irq_work_sync', '__free_pages', 'lsf_device_finish'):
            self.assertNotIn(forbidden, public)

    def test_final_file_handoff_follows_every_cache_scan_and_retains_fast_collector(self):
        body = function(source.factory(original_outputs()['net/factory.c'].decode()),
            'static int lsf_factory_release(')
        handoff = body.index('transferred = lsf_cleanup_root_fd_handoff_locked(file)')
        for scan in ('lsf_prepaid_netport_drain(', 'lsf_prepaid_sidcache_drain(',
                'lsf_prepaid_avc_drain(', 'lsf_prepaid_route_cache_drain(',
                'lsf_prepaid_device_sidcache_drain(', 'lsf_prepaid_cleanup_sidcache_drain(',
                'lsf_prepaid_device_avc_drain(', 'lsf_prepaid_cleanup_avc_drain('):
            self.assertLess(body.index(scan), handoff)
        self.assertLess(handoff, body.index('lsf_cleanup_root_release_take_locked(&release)'))
        self.assertLess(body.rindex('mutex_unlock(&factory_lock)'),
            body.index('lsf_cleanup_root_release_physical(release)'))
        self.assertLess(body.index('lsf_cleanup_root_release_physical(release)'),
            body.index('wake_up_process(kthreadd_task)'))
        self.assertIn('release = {0}', body)
        self.assertNotIn('factory.device->', body[handoff:])

    def test_both_original_sleep_predicates_and_request_first_dispatch_keep_create_lock_outside(self):
        body = source.kthreadd_function(source.preimages()['kthreadd']['text'])
        self.assertIn('&& !lsf_factory_cleanup_root_pending()', body)
        self.assertIn('|| lsf_factory_cleanup_root_pending()', body)
        branch = '''\t\t\tif (lsf_factory_cleanup_root_pending()) {
\t\t\t\tspin_unlock(&kthread_create_lock);
\t\t\t\tlsf_factory_cleanup_root_drain();
\t\t\t\tspin_lock(&kthread_create_lock);
\t\t\t\tcontinue;
\t\t\t}
'''
        self.assertIn(branch, body)
        self.assertLess(body.index('lsf_factory_cleanup_request_drain()'), body.index(branch))
        self.assertLess(body.index(branch), body.index('lsf_factory_cleanup_final_drain()'))
        self.assertLess(body.index('set_current_state(TASK_INTERRUPTIBLE)'),
            body.index('&& !lsf_factory_cleanup_root_pending()'))
        self.assertIn('create_kthread(create)', body)

    def test_actual_attempt_guard_is_once_then_original_sticky_quarantine_without_new_owner(self):
        body = function(helpers(), 'void lsf_factory_cleanup_root_drain(')
        predicate = re.search(r'    if \((pending &&.*?)\) \{', body, re.S)[1]
        for pending in (0, 1):
            for took in (0, 1):
                self.assertEqual(condition(predicate, {'pending':pending, 'took':took}),
                    bool(pending and not took))
        self.assertEqual(body.count('lsf_cleanup_root_release_take_locked(&release)'), 1)
        self.assertIn('if (lsf_cleanup_root_pending_locked()) {\n'
            '            factory.pool.poisoned = 1;\n'
            '            WRITE_ONCE(factory.uncertain, 1);', body)
        self.assertLess(body.index('mutex_lock(&factory_lock)'), body.index('spin_lock_irqsave'))
        self.assertLess(body.rindex('mutex_unlock(&factory_lock)'),
            body.index('lsf_cleanup_root_release_physical(release)'))
        self.assertIn('current != kthreadd_task || in_interrupt() || irqs_disabled()', body)
        self.assertNotIn('file->', body)
        for forbidden in ('kthread_create(', 'queue_work(', 'kthread_queue_work(', 'schedule(',
                'atomic_inc(', 'factory.opened = 0', 'factory.uncertain, 0'):
            self.assertNotIn(forbidden, helpers())

    def test_actual_final_guard_handles_consumed_private_reason_without_empty_list_extraction(self):
        body = source.kthreadd_function(source.preimages()['kthreadd']['text'])
        guard = '\t\t\tif (list_empty(&kthread_create_list))\n\t\t\t\tcontinue;\n'
        self.assertEqual(body.count(guard), 1)
        at = body.index(guard)
        self.assertGreater(at, body.index('lsf_cleanup_dispatch_kthread(owned)'))
        self.assertLess(at, body.index('struct kthread_create_info *create;'))
        self.assertLess(at, body.index('create = list_entry('))
        self.assertIn(guard+'#endif\n', body)  # Foreign CONFIG-off body remains original.
        self.assertGreater(at, body.index('spin_lock(&kthread_create_lock);'))
        # Drive the ACTUAL while and fallback expressions with two observations:
        # root pending at entry, consumed by FD before the private branch tests.
        while_predicate = re.search(r'while \((.*?)\) \{', body, re.S)[1]
        while_predicate = re.sub(r'^#.*$', '', while_predicate, flags=re.M)
        while_predicate = while_predicate.replace('list_empty(&kthread_create_list)', 'empty')
        while_predicate = re.sub(r'lsf_(?:factory|prepaid)_cleanup_[a-z_]+_pending\(\)',
            lambda m: 'root' if '_root_pending' in m[0] else 'other', while_predicate)
        while_predicate = while_predicate.replace('lsf_cleanup_pending', 'other')
        while_predicate = while_predicate.replace('||', ' or ')
        while_predicate = re.sub(r'!(?!=)', ' not ', while_predicate)
        self.assertTrue(calculate(ast.parse(' '.join(while_predicate.split()), mode='eval'),
            dict(empty=1, root=1, other=0)))
        branch = re.search(r'if \((lsf_factory_cleanup_root_pending\(\))\) \{', body)[1]
        self.assertFalse(calculate(ast.parse(branch.replace(
            'lsf_factory_cleanup_root_pending()', 'branch_root'), mode='eval'), dict(branch_root=0)))
        fallback = re.search(r'if \((.*?)\)\n\t\t\t\tcontinue;', guard, re.S)[1]
        fallback = fallback.replace('list_empty(&kthread_create_list)', 'empty')
        expression = ast.parse(fallback, mode='eval')
        self.assertTrue(calculate(expression, dict(empty=1)))
        self.assertFalse(calculate(expression, dict(empty=0)))

    def test_common_take_preserves_all_original_terminal_lineage_irq_page_and_ref_guards(self):
        old = original_outputs()['net/factory-cleanup-root-final-free.c'].decode()
        new = source.collector(old)
        take = function(new, 'static int lsf_cleanup_root_release_take_locked(')
        self.assertIn('factory.opened != 2u', take)
        self.assertNotIn('file->', take)
        for guard in ('lsf_cleanup_root_no_application_locked()',
                'lsf_cleanup_root_records_locked(source)', 'lsf_cleanup_root_pages_locked()',
                'lsf_prepaid_cleanup_irq_closed(source, base)',
                'cleanup_request_returned != 1u', 'cleanup_provider_control_readers',
                'cleanup_task_claimed != 2u', 'cleanup_worker_stop != 2u'):
            self.assertIn(guard, take)
        for prefix in ('static int lsf_cleanup_root_pages_locked(',
                'static int lsf_cleanup_root_records_locked(',
                'static int lsf_cleanup_root_no_application_locked(',
                'static void lsf_cleanup_root_release_physical('):
            self.assertEqual(function(old, prefix), function(new, prefix))


if __name__ == '__main__':
    unittest.main()
