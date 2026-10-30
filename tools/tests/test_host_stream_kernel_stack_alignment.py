"""Frozen-source and actual arithmetic guards; no Linux/PTE execution claim."""
import ast
import hashlib
import operator
import re
import unittest

from tools import host_stream_kernel_stack_alignment as change
from tools import host_stream_kernel_constructor_failure as observation
from tools import host_stream_kernel_cleanup_constructor as constructor
from tools.host_stream_kernel_cleanup_native import replace, function
from tools.tests.test_host_stream_kernel_constructor_failure import originals


def inputs():
    result = observation.transform(originals())
    # The existing IRQ/constructor projections contain no new Linux body copy.
    text = (constructor.OWNED/'cleanup-stack-retire.c').read_text(encoding='utf-8')
    text = text.replace('int lsf_prepaid_cleanup_stack_release(struct task_struct *task)\n',
        'int lsf_prepaid_cleanup_stack_capture_deferred(struct task_struct *task)\n')
    text = replace(text, '    if (valid && lsf_factory_cleanup_task_publish(source, task))\n',
        '    if (valid && !lsf_prepaid_cleanup_irq_prepare(source, task) &&\n'
        '        lsf_factory_cleanup_task_publish(source, task) &&\n'
        '        !lsf_prepaid_cleanup_irq_arm(source, task))\n')
    text = text.replace('int lsf_prepaid_cleanup_stack_publish(',
        'int lsf_prepaid_cleanup_constructor_prepare(')
    text = replace(text, '    if (valid && !lsf_prepaid_cleanup_irq_prepare(source, task) &&\n'
        '        lsf_factory_cleanup_task_publish(source, task) &&\n'
        '        !lsf_prepaid_cleanup_irq_arm(source, task))\n',
        '    if (valid && !lsf_prepaid_cleanup_irq_prepare(source, task) &&\n'
        '        lsf_factory_cleanup_constructor_vm_prepared(source, task, stack))\n')
    result['mm/lsf-cleanup-stack-retire.c'] = (
        '#include <net/lsf_stream_cleanup_constructor.h>\n'+text).encode()
    return result


def selected():
    return change.transform(inputs())


def arithmetic(node, context):
    """Closed integer/boolean interpreter; no executable-source evaluation."""
    if isinstance(node,ast.Expression):
        return arithmetic(node.body,context)
    if isinstance(node,ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node,ast.Name) and node.id in context:
        return context[node.id]
    if isinstance(node,ast.BinOp) and type(node.op) in (ast.Add,ast.Sub,ast.Mult):
        operation = {ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul}[type(node.op)]
        return operation(arithmetic(node.left,context),arithmetic(node.right,context))
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.Not):
        return not arithmetic(node.operand,context)
    if isinstance(node,ast.BoolOp) and type(node.op) in (ast.Or,ast.And):
        operation = any if isinstance(node.op,ast.Or) else all
        return operation(arithmetic(item,context) for item in node.values)
    comparisons = {ast.Lt:operator.lt,ast.LtE:operator.le,ast.Gt:operator.gt,
        ast.GtE:operator.ge,ast.Eq:operator.eq,ast.NotEq:operator.ne}
    if isinstance(node,ast.Compare) and len(node.ops) == len(node.comparators) == 1 \
            and type(node.ops[0]) in comparisons:
        return comparisons[type(node.ops[0])](arithmetic(node.left,context),
            arithmetic(node.comparators[0],context))
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and \
            node.func.id in ('ALIGN','IS_ALIGNED') and len(node.args) == 2 and not node.keywords:
        return context[node.func.id](*(arithmetic(item,context) for item in node.args))
    raise ValueError('unknown-carve-expression')


def actual_carve_arithmetic(text, start, end, *, lower=0x100000, upper=0x200000):
    """Evaluate only the actual closed, side-effect-free C guard expressions.

    All tokens between first-node selection and first mutation must be consumed;
    unknown source refuses. This is not a stand-in for locks/PTEs/the kernel.
    """
    body = function(text, 'static int lsf_cleanup_stack_carve(')
    body = body[body.index('    start = free->va_start;\n'):
                body.index('    stack->area.va_start = start;\n')]
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    token = re.compile(r'\s*(?:if \((.*?)\) \{\s*lsf_cleanup_failure\([^;]*;\s*goto out;\s*\}'
                       r'|([a-z]+) (\+?=) ([^;]+);)', re.S)
    context = {'start':start, 'free_start':start, 'free_end':end,
        'PAGE_SIZE':4096, 'THREAD_SIZE':16384, 'THREAD_ALIGN':16384,
        'VMALLOC_START':lower, 'VMALLOC_END':upper, 'MAXIMUM':2**64-1, 'ENTRIES':8,
        'size':20480, 'IS_ALIGNED':lambda value, align: value % align == 0,
        'ALIGN':lambda value, align: (value+align-1) & ~(align-1)}
    position = 0
    for row in token.finditer(body):
        if body[position:row.start()].strip():
            raise ValueError('unknown-carve-arithmetic')
        position = row.end()
        expression = row[1] if row[1] is not None else row[4]
        expression = expression.replace('free->va_start','free_start').replace('free->va_end','free_end')
        expression = expression.replace('ARRAY_SIZE(stack->entries)', 'ENTRIES').replace('~0UL','MAXIMUM')
        expression = re.sub(r'\b(\d+)u\b', r'\1', expression)
        expression = expression.replace('||', ' or ').replace('&&', ' and ')
        expression = re.sub(r'!(?!=)', ' not ', expression).strip()
        value = arithmetic(ast.parse(expression,mode='eval'),context)
        if row[1] is not None:
            if value:
                return None
        elif row[3] == '+=':
            context[row[2]] += value
        else:
            context[row[2]] = value
    if body[position:].strip():
        raise ValueError('unknown-carve-arithmetic')
    return context['aligned'], context['padding'], context['size']


class StackAlignmentSource(unittest.TestCase):
    def test_compiled_505_preimages_only_two_outputs_and_tampering_refuses(self):
        before = inputs();before['untouched-original'] = b'actual other source unchanged'
        for name, (size, checksum) in change.PREIMAGES.items():
            self.assertEqual((len(before[name]), hashlib.sha256(before[name]).hexdigest()), (size, checksum))
        after = change.transform(before)
        self.assertEqual(set(before), set(after))
        self.assertEqual({n for n in before if before[n] != after[n]}, set(change.PREIMAGES))
        for name in change.PREIMAGES:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'compiled-505-preimage'):
                change.transform({**before,name:before[name]+b'\n'})
        with self.assertRaisesRegex(ValueError, 'compiled-505-preimage'):
            change.transform(after)

    def test_actual_arithmetic_all_residues_exact_boundary_overflow_and_no_mutation(self):
        text = selected()['mm/lsf-cleanup-stack.c'].decode()
        for residue in range(4):
            start = 0x100000+residue*4096
            aligned = (start+16383) & ~16383
            size = aligned-start+20480
            with self.subTest(residue=residue):
                self.assertEqual(actual_carve_arithmetic(text,start,start+size+4096),
                                 (aligned,aligned-start,size))
                self.assertIsNone(actual_carve_arithmetic(text,start,start+size))
                self.assertIsNone(actual_carve_arithmetic(text,start,start+size-4096))
                self.assertEqual((start+size)-(aligned+16384),4096)
                self.assertLessEqual(size,32768)
        self.assertIsNone(actual_carve_arithmetic(text,0x100001,0x180000))
        self.assertIsNone(actual_carve_arithmetic(text,0x0ff000,0x180000))
        self.assertIsNone(actual_carve_arithmetic(text,0x100000,0x200001))
        self.assertIsNone(actual_carve_arithmetic(text,2**64-4096,2**64-1,lower=0,upper=2**64-1))
        for expression in ('unknown(1)', 'value.attribute', '1 / 2', "'not an integer'"):
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError,'unknown-carve'):
                arithmetic(ast.parse(expression,mode='eval'),{})
        carve = function(text,'static int lsf_cleanup_stack_carve(')
        self.assertLess(carve.index('free->va_end - start <= size'),carve.index('stack->area.va_start ='))
        self.assertEqual(carve.count('list_first_entry('),1)
        self.assertNotIn('for (',carve)
        self.assertEqual(carve.count('free->va_start += size;'),1)

    def test_prefix_and_guard_preflight_retirement_all_eight_only_four_pages_mapped(self):
        text = selected()['mm/lsf-cleanup-stack.c'].decode()
        create = function(text.split('\n#else\n',1)[0],
            'int lsf_prepaid_cleanup_stack_create_observed(')
        self.assertIn('entries[THREAD_SIZE / PAGE_SIZE + THREAD_ALIGN / PAGE_SIZE]',text)
        self.assertIn('sizeof(struct lsf_cleanup_stack) + PAGE_SIZE - 1u + THREAD_SIZE',text)
        self.assertIn('for (i = 0; i < count; ++i)',create)
        self.assertIn('stack->area.va_start + i * PAGE_SIZE',create)
        self.assertLess(create.index('!pte_none(ptep_get(stack->entries[i]))'),create.index('set_pte_at('))
        self.assertIn('for (i = 0; i < ARRAY_SIZE(stack->pages); ++i)\n        set_pte_at(',create)
        self.assertIn('stack->entries[offset + i]',create)
        unmap = function(text,'static int lsf_cleanup_stack_unmap(')
        self.assertLess(unmap.index('count > ARRAY_SIZE(stack->entries)'),unmap.index('stack->entries[i]'))
        self.assertIn('entry != stack->entries[i]',unmap)
        self.assertIn('i < offset || i >= offset + ARRAY_SIZE(stack->pages)',unmap)
        self.assertIn('stack->pages[i - offset]',unmap)
        self.assertIn('vunmap_range(address, address + THREAD_SIZE);',unmap)
        self.assertLess(unmap.index('vunmap_range('),unmap.index('lsf_cleanup_stack_restore(stack)'))

    def test_raw_vm_full_restore_foreign_guard_and_aligned_task_identity(self):
        before = inputs();after = change.transform(before)
        old = before['mm/lsf-cleanup-stack.c'].decode().split('\n#else\n',1)[0]+'\n'
        new = after['mm/lsf-cleanup-stack.c'].decode().split('\n#else\n',1)[0]+'\n'
        for signature in ('static int lsf_cleanup_stack_restore(',
                'static void lsf_cleanup_stack_busy(', 'int lsf_prepaid_cleanup_stack_foreign_unmap('):
            self.assertEqual(function(old,signature),function(new,signature))
        self.assertIn('stack->vm.addr = (void *)start;',new)
        self.assertIn('stack->vm.size = size;',new)
        self.assertIn('task->stack = (void *)start;',new)
        self.assertIn('return ALIGN((unsigned long)stack->vm.addr, THREAD_ALIGN);',new)
        abort = function(new,'int lsf_prepaid_cleanup_stack_abort_unpublished(')
        self.assertLess(abort.index('lsf_factory_cleanup_stack_current(source, task)'),
                        abort.index('(void *)lsf_cleanup_stack_start(stack) != task->stack'))
        retire = after['mm/lsf-cleanup-stack-retire.c'].decode()
        self.assertEqual(retire.count('task->stack == (void *)lsf_cleanup_stack_start(stack)'),2)
        self.assertIn('error ? THREAD_SIZE + PAGE_SIZE : stack->vm.size,\n        PAGE_SIZE,',new)
        self.assertNotIn('VM_NO_GUARD',new)
        self.assertNotIn('VM_MAP_PUT_PAGES',new)


if __name__ == '__main__':
    unittest.main()
