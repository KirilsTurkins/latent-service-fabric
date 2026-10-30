"""Exact source/guard controls; none executes Linux or certifies a bank return."""
import ast
import re
import unittest

from tools import host_stream_kernel_root_final_free as source
from tools.tests.test_host_stream_kernel_task_identity_geometry import calculate


def originals():
    return {name: row['text'].encode() for name, row in source.preimages()['parentDerived'].items()}


def collector():
    return (source.OWNED/'factory-cleanup-root-final-free.c').read_text()


def pages_rejected(state):
    body = source.function(collector(), 'static int lsf_cleanup_root_pages_locked(')
    predicate = re.search(r'        if \((.*?)\)\n            return 0;', body, re.S)[1]
    expressions = {
        'PageCompound(page)':'compound', 'PageHWPoison(page)':'poison',
        'page_ref_count(page)':'references', 'atomic_read(&page->_mapcount)':'mapcount',
        'page->mapping':'mapping', 'page_pool_page_is_pp(page)':'pagepool',
        '(page->flags & PAGE_FLAGS_CHECK_AT_FREE)':'badflags', 'page->memcg_data':'memcg',
    }
    for old, new in expressions.items():
        predicate = predicate.replace(old, new)
    predicate = re.sub(r'^#.*$', '', predicate, flags=re.M).replace('||', ' or ')
    predicate = predicate.replace('!= -1', '!= clear_mapcount')
    return calculate(ast.parse(' '.join(predicate.split()), mode='eval'), dict(state, clear_mapcount=-1))


def terminal_refused(changes):
    """Interpret the actual two C entry predicates over finite scalar inputs."""
    body = source.function(collector(), 'static int lsf_cleanup_root_release_take_locked(')
    predicates = re.findall(r'    if \((.*?)\)\n        goto out;', body, re.S)[:2]
    context = dict(file_private_data=1, factory_pointer=1, qualification=1, consumer=0,
        factory_opened=1, factory_pages=1, factory_device=1, file_f_cred=1, factory_mm=1,
        factory_tgid=1, factory_cred=1, factory_net=1, factory_uncertain=0,
        factory_pool_poisoned=0, factory_pool_initialized=1, factory_pool_stopped=1,
        factory_cleanup_observer_prebirth=1, lsf_device_uevent_taps_private_alive=1,
        lsf_device_uevent_taps_taps=0, lsf_device_uevent_taps_poisoned=0, no_application=1,
        source_owner_slot=63, source_owner_generation=1, factory_device_bootstrap_state=4,
        factory_device_bootstrap_busy=0, factory_device_bootstrap_error=0,
        factory_device_pci_attempted=0, factory_device_firmware_slot=0,
        factory_device_firmware_generation=0, factory_device_constructor_active=0,
        factory_device_cleanup_operation_active=0, factory_device_cleanup_physical_role=2,
        factory_device_cleanup_lifecycle=8, factory_device_cleanup_final_phase=5,
        factory_device_cleanup_request_users=0, factory_device_cleanup_task_claimed=2,
        factory_device_cleanup_request_returned=1, factory_device_cleanup_worker_associated=1,
        factory_device_cleanup_worker_stop=2, factory_device_cleanup_provider_control_retiring=1,
        factory_device_cleanup_provider_control_readers=0,
        factory_device_cleanup_provider_close_requested=1,
        factory_device_cleanup_provider_pool_destructed=1,
        LSF_DEVICE_OWNER_SLOT=63, LSF_FACTORY_BOOTSTRAP_CLOSED=4,
        LSF_CLEANUP_PHYSICAL_PROVIDER=2, LSF_CLEANUP_TASK_RETURNED=8, LSF_CLEANUP_FINAL_RETURNED=5)
    context.update(changes)
    for predicate in predicates:
        predicate = predicate.replace('lsf_factory_constructor_qualification()', 'qualification')
        predicate = predicate.replace('lsf_factory_selected_consumer()', 'consumer')
        predicate = predicate.replace('lsf_cleanup_root_no_application_locked()', 'no_application')
        predicate = predicate.replace('READ_ONCE(factory.uncertain)', 'factory.uncertain')
        members = set(re.findall(r'\b(?:factory|file|source|lsf_device_uevent_taps)(?:(?:\.|->)[a-z0-9_]+)+', predicate))
        for member in sorted(members, key=len, reverse=True):
            predicate = predicate.replace(member, member.replace('->', '_').replace('.', '_'))
        predicate = predicate.replace('&factory', 'factory_pointer').replace('||', ' or ').replace('&&', ' and ')
        predicate = re.sub(r'\b(\d+)u\b', r'\1', predicate)
        predicate = re.sub(r'!(?!=)', ' not ', predicate)
        if calculate(ast.parse(' '.join(predicate.split()), mode='eval'), context):
            return True
    return False


class RootFinalFreeSource(unittest.TestCase):
    def test_exact_successful_source_and_all_other_outputs_preserved(self):
        old = originals()
        old['ordinary.c'] = b'unchanged ordinary kernel'
        new = source.transform(old)
        self.assertEqual(new['ordinary.c'], old['ordinary.c'])
        self.assertEqual(set(new) - set(old), {'net/factory-cleanup-root-final-free.c'})
        self.assertNotIn(b'__free_pages(', old['net/factory.c'])
        self.assertNotIn(b'LSF_CLEANUP_IRQ_CLOSED', old['kernel/lsf-cleanup-irq.c'])
        for name in source.preimages()['parentDerived']:
            wrong = dict(old)
            wrong[name] += b'\n'
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'actual-000860-preimage'):
                source.transform(wrong)
        with self.assertRaisesRegex(ValueError, 'original-page-header'):
            source.authenticate_headers({})
        self.assertFalse(source.preimages()['actualLinuxFinalFree'])
        self.assertFalse(source.preimages()['nativeQuotaRelease'])

    def test_actual_page_guard_rejects_partial_tail_free_and_every_original_bad_page_state(self):
        for index in (0, 1, 127):
            baseline = dict(i=index, compound=0, poison=0, references=int(index == 0),
                mapcount=-1, mapping=0, pagepool=0, badflags=0, memcg=0)
            self.assertFalse(pages_rejected(baseline))
            for key, bad in (('compound', 1), ('poison', 1), ('references', 2),
                    ('references', int(index == 0)+1), ('mapcount', 0), ('mapping', 1),
                    ('pagepool', 1), ('badflags', 1), ('memcg', 1)):
                changed = dict(baseline, **{key:bad})
                with self.subTest(index=index, key=key, bad=bad):
                    self.assertTrue(pages_rejected(changed))
        body = source.function(collector(), 'static int lsf_cleanup_root_pages_locked(')
        self.assertIn('i < (1u << LSF_BACKING_ORDER)', body)
        self.assertNotIn('put_page', body)

    def test_original_generation_parent_chain_and_stored_pool_identity_are_source_bound(self):
        body = source.function(collector(), 'static int lsf_cleanup_root_records_locked(')
        bound = re.search(r'for \(depth = 0; depth < ([A-Z_]+);', body)[1]
        self.assertEqual(bound, 'LSF_ALLOCATION_SLOTS')
        self.assertIn('generation >= ancestor->generation', body)
        self.assertIn('ancestor->owner_generation != source.owner.generation', body)
        self.assertIn('generation != source.root.generation', body)
        self.assertIn('ancestor->phase != LSF_PREPAID_LIVE', body)
        for member in ('cleanup_provider_pool.slot', 'cleanup_provider_pool.generation',
                'cleanup_provider_worker.slot', 'cleanup_provider_worker.generation'):
            self.assertIn('factory.device->'+member, body)
        self.assertIn('which == LSF_PROVIDER_POOL', body)
        self.assertIn('which == LSF_PROVIDER_WORKER', body)
        for member in ('security_cache_location', 'security_cache_identity'):
            self.assertEqual(body.count('record->'+member), 2)  # Backing and each EMPTY record.
            take = source.function(collector(), 'static int lsf_cleanup_root_release_take_locked(')
            self.assertIn('root->'+member, take)
        self.assertIn('seen == (1u << LSF_PROVIDER_PARTS) - 1u', body)

    def test_all_original_owner_slots_and_historical_application_births_refuse(self):
        body = source.function(collector(), 'static int lsf_cleanup_root_no_application_locked(')
        for member in ('key.slot', 'key.generation', 'socket', 'net', 'lease'):
            self.assertIn('factory.contexts[i].'+member, body)
        for member in ('generation', 'cursor', 'live', 'continuations', 'poisoned', 'closed'):
            self.assertIn('context->'+member, body)
        self.assertIn('i < LSF_OWNER_SLOTS', body)
        self.assertIn('context->scope.identity[word]', body)
        take = source.function(collector(), 'static int lsf_cleanup_root_release_take_locked(')
        self.assertIn('owner->scope.identity[word]', take)
        for refusal in ('bootstrap_busy', 'bootstrap_error', 'pci_attempted', 'constructor_active',
                'cleanup_operation_active', 'cleanup_request_users', 'cleanup_provider_control_readers'):
            self.assertIn('factory.device->'+refusal, take)
        for seal in ('cleanup_task_claimed != 2u', 'cleanup_request_returned != 1u',
                'cleanup_worker_stop != 2u', 'cleanup_provider_control_retiring != 1u'):
            self.assertIn(seal, take)
        self.assertIn('READ_ONCE(factory.uncertain)', take)
        self.assertNotIn('factory.uncertain, 0', collector())

    def test_actual_terminal_entry_guards_retain_late_close_incomplete_and_uncertain_graphs(self):
        self.assertFalse(terminal_refused({}))
        for field, wrong in (('factory_device_cleanup_request_returned', 0),
                ('factory_device_cleanup_request_users', 1), ('factory_device_cleanup_task_claimed', 1),
                ('factory_device_cleanup_lifecycle', 7), ('factory_device_cleanup_final_phase', 0),
                ('factory_device_cleanup_provider_control_readers', 1),
                ('factory_device_cleanup_provider_control_retiring', 0),
                ('factory_device_cleanup_worker_stop', 1), ('factory_device_constructor_active', 1),
                ('factory_device_bootstrap_busy', 1), ('factory_device_bootstrap_state', 2),
                ('factory_device_bootstrap_error', 110), ('factory_uncertain', 1),
                ('factory_pool_poisoned', 1), ('no_application', 0), ('consumer', 1),
                ('qualification', 0), ('source_owner_slot', 62), ('file_private_data', 2),
                ('file_f_cred', 2), ('factory_pages', 0), ('factory_device', 0)):
            with self.subTest(field=field):
                self.assertTrue(terminal_refused({field:wrong}))

    def test_irq_closed_precedes_request_return_and_old_armed_readers_cannot_requeue(self):
        old = originals()
        new = source.transform(old)
        quiesce = source.function(new['kernel/lsf-cleanup-close.c'].decode().split('#else\n')[0],
            'int lsf_prepaid_cleanup_request_irq_quiesce(')
        self.assertLess(quiesce.index('irq_work_sync('), quiesce.index('LSF_CLEANUP_IRQ_CLOSED'))
        self.assertIn('phase != LSF_CLEANUP_IRQ_ABORTED && phase != LSF_CLEANUP_IRQ_CONSUMED', quiesce)
        release = source.function(new['kernel/lsf-cleanup-irq.c'].decode().split('#else\n')[0],
            'int lsf_prepaid_cleanup_stack_release(')
        self.assertLess(release.index('phase == LSF_CLEANUP_IRQ_RELEASED'), release.index('bank_base'))
        self.assertLess(release.index('LSF_CLEANUP_IRQ_QUEUING)'), release.index('irq_work_queue('))
        # Interpret the actual source guard: cmpxchg returns the CURRENT phase,
        # rather than an old reader's cached phase. No descriptor is followed
        # when this guard refuses; no actual Linux/NMI execution is claimed.
        predicate = re.search(r'    if \((phase != LSF_CLEANUP_IRQ_ARMED.*?)\) \{', release, re.S)[1]
        predicate = re.sub(r'atomic_cmpxchg\(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_ARMED,\s*LSF_CLEANUP_IRQ_QUEUING\)',
            'current_phase', predicate)
        predicate = predicate.replace('atomic_read(&lsf_cleanup_irq_hint.uncertain)', 'uncertain').replace('||', ' or ')
        expression = ast.parse(' '.join(predicate.split()), mode='eval')
        phases = {name:i for i,name in enumerate(('PREPARING', 'ARMED', 'CONSUMED', 'ABORTED', 'CLOSED', 'RELEASED'))}
        for cached in ('PREPARING', 'ARMED', 'CONSUMED', 'ABORTED', 'CLOSED'):
            for current in ('CLOSED', 'RELEASED'):
                self.assertTrue(calculate(expression, dict(phase=phases[cached],
                    current_phase=phases[current], uncertain=0, LSF_CLEANUP_IRQ_ARMED=phases['ARMED'])))
        self.assertFalse(calculate(expression, dict(phase=phases['ARMED'],
            current_phase=phases['ARMED'], uncertain=0, LSF_CLEANUP_IRQ_ARMED=phases['ARMED'])))
        for forbidden in ('request->', 'task->', 'irq_work_queue(', 'irq_work_sync('):
            self.assertNotIn(forbidden, source.IRQ_HELPERS)

    def test_physical_return_and_ref_puts_follow_unpublication_and_real_page_return(self):
        text = collector()
        take = source.function(text, 'static int lsf_cleanup_root_release_take_locked(')
        self.assertLess(take.index('lsf_device_finish('), take.index('factory.device = NULL'))
        self.assertLess(take.index('lsf_prepaid_cleanup_irq_release('), take.index('factory.pages = NULL'))
        self.assertNotIn('factory.device->', take[take.index('lsf_device_finish('):])
        physical = source.function(text, 'static void lsf_cleanup_root_release_physical(')
        sequence = ('__free_pages(release.pages, LSF_BACKING_ORDER)',
            'factory.pool.records[0].phase = LSF_PREPAID_RETURNED',
            'put_net(release.net)', 'put_cred(release.cred)', 'put_pid(release.tgid)', 'mmdrop(release.mm)',
            'pr_info("LSFVM1 physical-return=constructor-root-bank-and-actor-refs\\n")')
        self.assertEqual([physical.count(item) for item in sequence], [1]*len(sequence))
        self.assertEqual(sorted(physical.index(item) for item in sequence),
            [physical.index(item) for item in sequence])
        release = source.function(source.transform(originals())['net/factory.c'].decode(),
            'static int lsf_factory_release(')
        self.assertLess(release.rindex('mutex_unlock(&factory_lock)'),
            release.index('lsf_cleanup_root_release_physical(release)'))
        for reset in ('factory.opened = 0', 'pool.initialized = 0', 'prebirth_rollback(',
                'private_alive = 0', 'next_generation ='):
            self.assertNotIn(reset, text)


if __name__ == '__main__':
    unittest.main()
