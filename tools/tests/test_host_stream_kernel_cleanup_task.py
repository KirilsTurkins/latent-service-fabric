"""Changed source constructor checks, not Linux worker/stack execution."""
import hashlib
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_cleanup_task as source


class CleanupTaskPrefix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = source.preimages()

    def test_source_origin_is_exact_and_all_execution_readiness_gates_are_false(self):
        self.assertEqual(len(self.value['source']), 6)
        self.assertEqual(len(self.value['sections']), 6)
        self.assertEqual(len(self.value['parentDerived']), 3)
        self.assertTrue(all(self.value[name] is False for name in ('taskCreated', 'executorReady',
            'stackOwnerImplemented', 'completeAllocationClosure', 'productionInstallation')))
        self.assertNotIn('CONFIG_', source.GEOMETRY)

    def test_changed_fixture_or_source_refuses_before_parent_output_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            value = dict(self.value, executorReady=True)
            path.write_text(json.dumps(value))
            with patch.object(source, 'FIXTURE', path), self.assertRaisesRegex(ValueError,
                    'cleanup-task-fixed-source'):
                source.transform({}, {})
        with self.assertRaisesRegex(ValueError, 'cleanup-task-whole-membership'):
            source.transform({}, {})

    def test_private_copy_keeps_original_architecture_copy_before_closed_stack_refusal(self):
        raw = source.definition('dup_task_struct')
        new = source.private_prefix()
        prefix = raw[:raw.index('\terr = alloc_thread_stack_node(tsk, node);\n')]
        self.assertIn('err = arch_dup_task_struct(tsk, current);', new)
        self.assertLess(new.index('err = arch_dup_task_struct(tsk, current);'),
            new.index('err = -EOPNOTSUPP;'))
        self.assertNotIn('alloc_thread_stack_node(', new)
        self.assertNotIn('this_cpu_xchg', new)
        self.assertNotIn('__vmalloc', new)
        self.assertNotIn('kernel_clone(', new)
        self.assertNotIn('wake_up_new_task(', new)
        self.assertNotIn('tsk_fork_get_node(orig)', new)
        self.assertNotIn('arch_dup_task_struct(tsk, orig)', new)
        self.assertIn('alloc_task_struct_node(node)', prefix)
        self.assertIn('return ERR_PTR(err);', new)
        self.assertIn('return ERR_PTR(-EIO);', new)

    def test_geometry_reads_actual_extended_task_size_and_original_alignment(self):
        self.assertIn('actual_bytes = arch_task_struct_size;', source.GEOMETRY)
        self.assertIn('max_t(int, L1_CACHE_BYTES, ARCH_MIN_TASKALIGN)', source.GEOMETRY)
        self.assertIn('actual_bytes < sizeof(struct task_struct)', source.GEOMETRY)
        self.assertIn('actual_alignment > 64u', source.GEOMETRY)
        self.assertNotIn('16384', source.GEOMETRY)
        self.assertNotIn('sizeof(struct task_struct);', source.GEOMETRY)

    def test_complete_batch_preflight_precedes_both_births_and_storage_initialization(self):
        text = (source.OWNED / 'factory-cleanup-task.c').read_text()
        preflight = text.index('if (empty < 2u)')
        first = text.index('if (!lsf_device_allocate(')
        zero = text.index('    memset(*request_address, 0, request_bytes);')
        self.assertLess(preflight, first)
        self.assertLess(first, zero)
        self.assertIn('context->cursor > LSF_FACTORY_INFRA_BYTES - first - second', text)
        self.assertIn('task_bytes != actual_task_bytes || alignment != actual_alignment', text)
        self.assertIn('factory.device->cleanup_attempted || factory.device->pci_attempted', text)
        self.assertNotIn('kmalloc(', text)
        self.assertNotIn('alloc_pages(', text)

    def test_full_affine_request_parent_task_and_actual_constructor_are_checked(self):
        text = (source.OWNED / 'factory-cleanup-task.c').read_text()
        for name in ('owner', 'root', 'request', 'task'):
            self.assertIn('source.' + name + '.slot', text)
            self.assertIn('source.' + name + '.generation', text)
        self.assertIn('current != kthreadd_task', text)
        self.assertIn('factory.device->cleanup_task_claimed = 1;', text)
        self.assertIn('task->bytes < task_bytes', text)
        self.assertLess(text.index('lsf_factory_cleanup_task_source_locked(source) ||'),
            text.index('result = (void *)((char *)page_address(factory.pages) + task->offset);'))

    def test_failure_returns_only_never_published_task_view_and_retains_bank(self):
        text = (source.OWNED / 'factory-cleanup-task.c').read_text()
        abort = text[text.index('int lsf_factory_cleanup_task_abort('):]
        self.assertIn('factory.device->cleanup_task_claimed != 1u', abort)
        self.assertIn('lsf_device_finish(&factory.pool, source.owner, source.task,', abort)
        self.assertIn('factory.device->cleanup_task_claimed = 2u;', abort)
        for forbidden in ('kfree(', '__free_pages(', 'context->cursor -=', 'lsf_device_close(',
                'source.request, LSF_DEVICE_CLEANUP_REQUEST'):
            self.assertNotIn(forbidden, abort)
        self.assertIn('WRITE_ONCE(factory.uncertain, 1);', abort)

    def test_capture_does_not_change_parent_gate_or_dispatch_existing_acpi_work(self):
        raw = Path(source.__file__).read_text()
        for forbidden in ('queue_work(', 'kthread_queue_work(', 'wake_up_process(',
                'lsf_factory_selected_consumer(void)'):
            self.assertNotIn(forbidden, raw)
        self.assertNotIn('sysctl', (source.OWNED / 'cleanup-task-private.h').read_text())

    def test_normal_kthreadd_and_original_worker_constructor_tokens_are_preserved(self):
        old = ('struct task_struct *kthreadd_task;\n' + source.definition('kthreadd') +
            source.definition('__kthread_create_worker'))
        new = source.kthreadd_prefix(old)
        blocks = re.findall(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', new, re.S)
        self.assertEqual(len(blocks), 5)
        normal = re.sub(r'#ifdef CONFIG_LSF_STREAM_FACTORY\n.*?#endif\n', '', new, flags=re.S)
        self.assertEqual(re.findall(r'\w+|[^\s]', normal), re.findall(r'\w+|[^\s]', old))
        self.assertIn(source.definition('__kthread_create_worker'), new)
        private = new[new.index('if (lsf_cleanup_pending) {'):]
        self.assertLess(private.index('spin_unlock(&kthread_create_lock);'),
            private.index('lsf_cleanup_create_kthread(owned);'))

    def test_single_request_handoff_keeps_borrowed_completion_and_bank_on_interruption(self):
        text = (source.OWNED / 'kernel-cleanup-worker.c').read_text()
        self.assertEqual(text.count('struct kthread_worker worker;'), 1)
        self.assertIn('lsf_factory_cleanup_task_reserve(sizeof(*owned), task_bytes, alignment,', text)
        self.assertLess(text.index('lsf_factory_cleanup_task_reserve('),
            text.index('__kthread_init_worker(&owned->worker,'))
        self.assertIn('struct lock_class_key lock_key;', text)
        self.assertIn('sizeof(lsf_cleanup_pending) == sizeof(void *)', text)
        self.assertIn('owned->create.threadfn = kthread_worker_fn;', text)
        self.assertIn('owned->create.data = &owned->worker;', text)
        for forbidden in ('kmalloc(', 'kzalloc(', 'kernel_thread(', 'kernel_clone(',
                'wake_up_process(task)', 'kthread_bind(', 'kfree(', 'destroy_workqueue('):
            self.assertNotIn(forbidden, text)
        receiver = text[text.index('static void lsf_cleanup_create_kthread('):
            text.index('int lsf_prepaid_cleanup_worker_create(void)')]
        self.assertNotIn('owned->', receiver[receiver.index('complete(done);') + len('complete(done);'):])

    def test_close_fence_precedes_task_claim_and_final_return_remains_possible(self):
        text = (source.OWNED / 'factory-cleanup-task.c').read_text()
        shared = text[:text.index('int lsf_factory_cleanup_task_reserve(')]
        self.assertNotIn('pool.stopped', shared)
        claim = text[text.index('struct task_struct *lsf_factory_cleanup_task_claim('):
            text.index('int lsf_factory_cleanup_task_abort(')]
        self.assertLess(claim.index('spin_lock_irqsave'), claim.index('factory.pool.stopped'))
        self.assertLess(claim.index('factory.pool.contexts[source.owner.slot].closed'),
            claim.index('factory.device->cleanup_task_claimed = 1;'))


if __name__ == '__main__':
    unittest.main()
