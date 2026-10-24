"""Actual source geometry predicates; no Linux execution or worker-ready claim."""
import ast
import hashlib
import operator
import re
import unittest

from tools import host_stream_kernel_task_identity_geometry as source
from tools import host_stream_kernel_cleanup_task as original_task
from tools import host_stream_kernel_cleanup_native_programme as programme
from tools.host_stream_kernel_cleanup_native import OWNED, function


def calculate(node, context):
    """Closed integer/boolean interpretation, never executable-source evaluation."""
    if isinstance(node, ast.Expression):
        return calculate(node.body, context)
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Name) and node.id in context:
        return context[node.id]
    operations = {ast.Add:operator.add, ast.Sub:operator.sub, ast.BitAnd:operator.and_}
    if isinstance(node, ast.BinOp) and type(node.op) in operations:
        return operations[type(node.op)](calculate(node.left, context), calculate(node.right, context))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not calculate(node.operand, context)
    if isinstance(node, ast.BoolOp) and type(node.op) in (ast.Or, ast.And):
        operation = any if isinstance(node.op, ast.Or) else all
        return operation(calculate(item, context) for item in node.values)
    comparisons = {ast.Lt:operator.lt, ast.Gt:operator.gt, ast.Eq:operator.eq, ast.NotEq:operator.ne}
    if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1 \
            and type(node.ops[0]) in comparisons:
        return comparisons[type(node.ops[0])](calculate(node.left, context),
            calculate(node.comparators[0], context))
    raise ValueError('unknown-task-geometry-expression')


def expression(text, context):
    replacements = {
        'sizeof(*factory.device)':'root_size', 'sizeof(*current)':'static_size',
        'root->bytes':'root_bytes', 'task->bytes':'record_bytes',
        'fpu_kernel_cfg.default_size':'default_size',
        'sizeof(struct task_struct)':'static_size',
        'sizeof(current->thread.fpu.__fpstate.regs)':'register_size',
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    text = re.sub(r'\b(\d+)u\b', r'\1', text)
    text = text.replace('||', ' or ').replace('&&', ' and ')
    text = re.sub(r'!(?!=)', ' not ', text).strip()
    return calculate(ast.parse(' '.join(text.split()), mode='eval'), context)


def actual_geometry():
    # Reuse the actual maintained repair, with its exact historical preimage.
    old = original_task.GEOMETRY.replace('        return -EOPNOTSUPP;\n',
        '        return lsf_factory_cleanup_prebirth_refused(LSF_REFUSE_TASK_GEOMETRY,\n'
        '            actual_bytes, actual_alignment);\n')
    return programme.repair_task_geometry({'kernel/lsf-cleanup-task.c':old.encode()})[
        'kernel/lsf-cleanup-task.c'].decode()


def geometry_values(text, static_size, registers, default, arch_size, alignment):
    context = dict(static_size=static_size, register_size=registers, default_size=default,
        actual_bytes=arch_size, actual_alignment=alignment, bytes=1, alignment=1,
        LSF_FACTORY_INFRA_BYTES=196608)
    expected = re.search(r'unsigned long expected_bytes = (.*?);', text, re.S)[1]
    context['expected_bytes'] = expression(expected, context)
    condition = re.search(r'    if \((.*?)\)\n        return lsf_factory_cleanup_prebirth_refused', text, re.S)[1]
    return (0, 0) if expression(condition, context) else (arch_size, alignment)


def record_refused(body, record_bytes, task_bytes, alignment, address=0x400000):
    condition = body[body.index('root->bytes < sizeof(*factory.device)'):
                     body.index('factory.device != (void *)(base + root->offset)')]
    condition = condition.strip().removesuffix('||').strip()
    return bool(expression(condition, dict(root_size=256, root_bytes=256,
        static_size=16384, record_bytes=record_bytes, task_bytes=task_bytes,
        task_alignment=alignment, address=address)))


class TaskIdentityGeometrySource(unittest.TestCase):
    def setUp(self):
        self.raw = (OWNED/'factory-cleanup-provider-operation.c').read_bytes()
        self.old = self.raw.decode()
        self.new = source.transform({source.NAME:self.raw})[source.NAME].decode()
        self.helper = function(self.new, 'static int lsf_cleanup_provider_physical_locked(')

    def test_exact_740_source_and_reviewed_inverse_projection_refuse_foreign_inputs(self):
        self.assertEqual((len(self.raw), hashlib.sha256(self.raw).hexdigest()), source.PREIMAGE)
        # Byte-exact output independently reviewed before this maintained transform.
        self.assertEqual((len(self.new.encode()), hashlib.sha256(self.new.encode()).hexdigest()),
            (15001, 'ae459f785738974a0ba7c05ecfd2ff11cf93496c34678165ce721cd88153d5d5'))
        after = source.transform({source.NAME:self.raw, 'unrelated-source':b'unchanged'})
        self.assertEqual(after['unrelated-source'], b'unchanged')
        for wrong in ({}, {source.NAME:self.raw+b'\n'}, after):
            with self.assertRaisesRegex(ValueError, 'compiled-740-preimage'):
                source.transform(wrong)
        for signature in ('static struct lsf_prepaid_view *lsf_cleanup_provider_held_record_locked(',
                'static int lsf_cleanup_provider_same_task_source(',
                'int lsf_factory_cleanup_provider_bind('):
            self.assertEqual(function(self.old, signature), function(self.new, signature))
        probe = (OWNED/'constructor-vm-init.c').read_text(encoding='utf-8')
        self.assertIn('little(status + 24, 8) == 3', probe)
        self.assertIn('"refused-retry-preserves-original"', probe)

    def test_actual_dynamic_geometry_and_fxsave_minimum_keep_undersize_alignment_refusals(self):
        geometry = actual_geometry()
        old_helper = function(self.old, 'static int lsf_cleanup_provider_physical_locked(')
        for default in (512, 4096, 8192):
            arch_size = 16384-4096+default
            task_bytes, alignment = geometry_values(geometry, 16384, 4096, default, arch_size, 64)
            rounded = (arch_size+63) & ~63
            with self.subTest(default=default):
                self.assertEqual((task_bytes, alignment), (arch_size, 64))
                self.assertFalse(record_refused(self.helper, rounded, task_bytes, alignment))
                self.assertTrue(record_refused(self.helper, task_bytes-1, task_bytes, alignment))
                self.assertTrue(record_refused(self.helper, rounded, task_bytes, alignment, 0x400001))
                if default == 512:
                    self.assertTrue(record_refused(old_helper, rounded, task_bytes, alignment))
        for default, arch, alignment in ((0, 12288, 64), (512, 12801, 64),
                (512, 12800, 0), (512, 12800, 3), (512, 12800, 128)):
            with self.subTest(default=default, arch=arch, alignment=alignment):
                values = geometry_values(geometry, 16384, 4096, default, arch, alignment)
                self.assertEqual(values, (0, 0))
                self.assertTrue(record_refused(self.helper, 16384, *values))
        for unknown in ('unknown(1)', 'value.attribute', '1 / 2', "'text'"):
            with self.assertRaisesRegex(ValueError, 'unknown-task-geometry-expression'):
                expression(unknown, {})

    def test_all_five_original_callers_read_geometry_before_lock_and_task_fields_stay_guarded(self):
        self.assertEqual(len(source.CALLERS), 5)
        for signature in source.CALLERS:
            body = function(self.new, signature)
            with self.subTest(signature=signature):
                self.assertEqual(body.count('lsf_prepaid_cleanup_task_geometry('), 1)
                self.assertEqual(body.count('lsf_cleanup_provider_physical_locked('), 1)
                self.assertLess(body.index('lsf_prepaid_cleanup_task_geometry('), body.index('spin_lock_irqsave('))
                self.assertLess(body.index('task_bytes = 0;'), body.index('spin_lock_irqsave('))
                self.assertIn(', task_bytes, task_alignment)', body)
        self.assertNotIn('lsf_prepaid_cleanup_task_geometry(', self.helper)
        self.assertLess(self.helper.index('address - base >= LSF_BACKING_BYTES'),
                        self.helper.index('!task_bytes || !task_alignment'))
        self.assertIn('if (address < base || address - base >= LSF_BACKING_BYTES)\n        return 0;', self.helper)
        self.assertLess(self.helper.index('task->bytes < task_bytes'), self.helper.index('current->usage'))
        for token in ('source->owner.slot != LSF_DEVICE_OWNER_SLOT',
                'factory.device->cleanup_task_claimed != 1u',
                'task->phase != LSF_PREPAID_LIVE', 'LSF_PREPAID_PUBLISHED',
                'LSF_PREPAID_QUEUED', 'address != base + task->offset',
                'current->flags & PF_KTHREAD', 'LSF_CLEANUP_PHYSICAL_PROVIDER'):
            self.assertIn(token, self.helper)


if __name__ == '__main__':
    unittest.main()
