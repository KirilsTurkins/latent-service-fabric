"""Source-bound reference/custody controls; no Linux retirement qualification."""
import ast
import hashlib
import re
import unittest

from tools import host_stream_kernel_provider_task_reference as source
from tools import host_stream_kernel_cleanup_provider_retirement as prior
from tools.host_stream_kernel_cleanup_native import OWNED, function
from tools.tests.test_host_stream_kernel_constructor_failure import originals
from tools import host_stream_kernel_constructor_failure as observation
from tools.tests.test_host_stream_kernel_task_identity_geometry import calculate


def take(state):
    """Interpret the actual finite C refusal predicates, not C execution."""
    helper = source.TAKE
    replacements = {
        'lsf_cleanup_lifecycle_identity_locked(source, task)':'identity',
        'factory.pool.poisoned':'poisoned',
        'factory.device->cleanup_physical_role':'role',
        'factory.device->cleanup_worker_associated':'associated',
        'factory.device->cleanup_worker_stop':'stop', 'record->deferred':'deferred',
    }
    predicates = re.findall(r'    if \((.*?)\)\n        goto poison;', helper, re.S)
    if len(predicates) != 2:
        raise ValueError('reference-control-exact-two-guards')
    context = dict(state, LSF_CLEANUP_PHYSICAL_PROVIDER=2, LSF_PREPAID_QUEUED=3)
    for predicate in predicates:
        for old, new in replacements.items():
            predicate = predicate.replace(old, new)
        predicate = re.sub(r'\b(\d+)u\b', r'\1', predicate)
        predicate = re.sub(r'!(?!=)', ' not ', predicate.replace('||', ' or ').replace('&&', ' and '))
        if calculate(ast.parse(' '.join(predicate.split()), mode='eval'), context):
            return False
    assignment = re.search(r'cleanup_worker_stop = (\d+)u;', helper)
    if not assignment or assignment[1] != '1':
        raise ValueError('reference-control-one-consume-state')
    state['stop'] = int(assignment[1])
    return True


def admitted():
    return dict(identity=1, poisoned=0, role=2, associated=1, stop=0, record=1, deferred=3)


class ProviderTaskReferenceSource(unittest.TestCase):
    def test_exact_failed_source_projection_and_actual_kthread_error_propagation(self):
        old = prior.reap_workers()
        new = source.reap_workers(old)
        self.assertEqual(new.count('kthread_stop_put(worker->task);'), 1)
        self.assertEqual(new.count('put_task_struct(association_task);'), 1)
        for wrong in ({}, {name:b'foreign source' for name in source.PREIMAGES}):
            with self.assertRaisesRegex(ValueError, 'compiled-489-preimage'):
                source.transform(wrong)
        old_constructor = observation.transform(originals())['kernel/lsf-cleanup-constructor.c'].decode()
        self.assertEqual((len(old_constructor.encode()), hashlib.sha256(old_constructor.encode()).hexdigest()),
            source.PREIMAGES['kernel/lsf-cleanup-constructor.c'])
        new_constructor = source.constructor(old_constructor)
        added = '\t\tretval = kthread_error;\n'
        self.assertEqual(new_constructor.replace(added, ''), old_constructor)
        before = function(old_constructor, 'struct task_struct *lsf_prepaid_cleanup_copy_process(')
        after = function(new_constructor, 'struct task_struct *lsf_prepaid_cleanup_copy_process(')
        self.assertEqual(before.count('lsf_prepaid_cleanup_kthread_prepare('), 1)
        self.assertEqual(after.count('lsf_prepaid_cleanup_kthread_prepare('), 1)
        branch = re.search(r'\tif \(kthread_error\) \{\n(.*?)\n\t\}', after, re.S)[1]
        self.assertEqual(branch.splitlines()[0], '\t\tretval = kthread_error;')
        for error in (-95, -12, -4, -110):
            # Closed interpretation of the new actual scalar assignment only.
            assignment = branch.splitlines()[0].strip()
            self.assertEqual(assignment, 'retval = kthread_error;')
            result = {'kthread_error':error}[assignment.removeprefix('retval = ').removesuffix(';')]
            self.assertEqual(result, error)
            self.assertNotEqual(result, -11)
        self.assertIn('goto bad_fork_cleanup_delayacct;', branch)
        self.assertEqual(after.replace(added, ''), before)

    def test_actual_consume_guards_refuse_cross_owner_missing_and_double_custody(self):
        state = admitted()
        self.assertTrue(take(state))
        self.assertEqual(state['stop'], 1)
        self.assertFalse(take(state))
        self.assertEqual(state['stop'], 1)
        for name, wrong in (('identity', 0), ('poisoned', 1), ('role', 1),
                ('associated', 0), ('associated', 2), ('stop', 1), ('stop', 2),
                ('record', 0), ('deferred', 1), ('deferred', 2)):
            state = admitted()
            state[name] = wrong
            before = dict(state)
            with self.subTest(name=name, value=wrong):
                self.assertFalse(take(state))
                self.assertEqual(state, before)  # No authority/ref release on refusal.
        self.assertNotIn('TASK_DEAD', source.TAKE.split('/* No TASK_DEAD')[0])
        self.assertNotIn('task->', source.TAKE)
        self.assertLess(source.TAKE.index('lsf_cleanup_lifecycle_identity_locked('),
            source.TAKE.index('lsf_provider_part_record_locked('))
        self.assertLess(source.TAKE.index('cleanup_worker_stop = 1u'),
            source.TAKE.index('spin_unlock_irqrestore('))
        for unknown in ('arbitrary_call()', 'value.attribute', '1 / 2'):
            with self.assertRaises(ValueError):
                calculate(ast.parse(unknown, mode='eval'), {})

    def test_association_retains_early_exit_and_both_original_stack_return_orders(self):
        reaper = source.reap_workers(prior.reap_workers())
        self.assertIn('put_task_struct(association_task);', reaper)
        # Explicit abstract real owners, not an observation of Linux's usage.
        # An early thread-function return cannot consume the association owner.
        for order in (('stack', 'reap'), ('reap', 'stack')):
            owners = {'association', 'stack'}
            old_owners = set(owners)
            state = admitted()
            for event in order:
                if event == 'stack':
                    owners.remove('stack')
                    old_owners.remove('stack')
                else:
                    # Original dying-owner get/stop_put is separately balanced.
                    owners.add('dying')
                    owners.remove('dying')
                    self.assertTrue(take(state))
                    owners.remove('association')
                if owners:
                    self.assertIn('stack' if event == 'reap' else 'association', owners)
            self.assertEqual(owners, set())
            self.assertEqual(old_owners, {'association'})
            self.assertFalse(take(state))
        self.assertTrue(any(isinstance(value, str) and '!tryget_task_struct(task)' in value
            for value in prior.transform.__code__.co_consts))

    def test_original_foreign_reap_and_last_task_use_worker_finish_order(self):
        old = prior.reap_workers()
        new = source.reap_workers(old)
        ordinary = lambda text: re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', text, flags=re.S)
        self.assertEqual(ordinary(new), ordinary(old))
        self.assertLess(new.index('association_task = worker->task;'), new.index('kthread_stop_put('))
        self.assertLess(new.index('kthread_stop_put('), new.index('lsf_factory_cleanup_provider_task_reference_take('))
        self.assertLess(new.index('lsf_factory_cleanup_provider_task_reference_take('),
            new.index('put_task_struct(association_task);'))
        tail = new[new.index('put_task_struct(association_task);')+len('put_task_struct(association_task);'):]
        self.assertNotIn('association_task', tail)
        self.assertNotIn('worker->task', tail)
        self.assertIn('lsf_factory_cleanup_provider_part_finish(source, LSF_PROVIDER_WORKER, worker)', tail)
        self.assertIn('return; /* Unknown/repeated custody retains the actual reference. */', new)
        self.assertNotIn('put_task_struct(', source.TAKE)
        self.assertNotIn('kthread_stop', source.TAKE)
        original = (OWNED/'factory-cleanup-provider-retirement.c').read_text(encoding='utf-8')
        # The existing queue stage's exact admission is the only fixture delta.
        original = original.replace('    if (!record || !lsf_provider_part_queue_locked(source, record))\n',
            '    if (part == LSF_PROVIDER_CONTROL &&\n'
            '        (!factory.device->cleanup_provider_control_retiring || factory.device->cleanup_provider_control_readers))\n'
            '        goto poison;\n    if (!record || !lsf_provider_part_queue_locked(source, record))\n')
        modified = source.retirement(original)
        finish = function(modified, 'int lsf_factory_cleanup_provider_part_finish(')
        self.assertLess(finish.index('cleanup_worker_stop != 1u'), finish.index('lsf_device_finish('))
        self.assertLess(finish.index('lsf_device_finish('), finish.index('cleanup_worker_stop = 2u'))
        unused = (OWNED/'factory-cleanup-provider-queue.c').read_text(encoding='utf-8')
        self.assertIn('factory.device->cleanup_worker_associated || factory.device->cleanup_request_users',
            function(unused, 'int lsf_factory_cleanup_provider_unused_worker_finish('))


if __name__ == '__main__':
    unittest.main()
