"""Own the first extent's alignment prefix in the selected x86 stack alias.

This changes the private derived implementation only. Four physical bank pages
remain unchanged; the single exclusive VA reservation is now 20--32 KiB. No
Linux execution, existing page-table readiness or whole-profile fit is implied.
"""
import hashlib

from tools.host_stream_kernel_constructor_failure import Editor, failure
from tools.host_stream_kernel_cleanup_native import require

PREIMAGES = {
    'mm/lsf-cleanup-stack.c': (15901, 'a8799115b5e65d0dd5e775edf4ed690a14d059fbb84f371ce746d0d4a8a6b2c2'),
    'mm/lsf-cleanup-stack-retire.c': (6408, 'b6524f750d2e54817f8ddf3b248544fe39b37712ae573a8268bbf8f7c989e32a'),
}

STACK_START = '''/* Only the selected, four-page x86 profile uses this private view.
 * vm/area describe the complete original reservation, including an unmapped
 * alignment prefix. Task stack consumers receive the aligned four-page body. */
static unsigned long lsf_cleanup_stack_start(const struct lsf_cleanup_stack *stack)
{
    return ALIGN((unsigned long)stack->vm.addr, THREAD_ALIGN);
}

'''


def stack(text):
    editor = Editor(text)
    editor.edit('    pte_t *entries[THREAD_SIZE / PAGE_SIZE + 1];\n',
        '    pte_t *entries[THREAD_SIZE / PAGE_SIZE + THREAD_ALIGN / PAGE_SIZE];\n')
    editor.edit('static struct lsf_cleanup_stack *lsf_cleanup_stack_live;\n\n',
        'static struct lsf_cleanup_stack *lsf_cleanup_stack_live;\n\n'+STACK_START)
    editor.edit('    unsigned long flags, start, size = THREAD_SIZE + PAGE_SIZE;\n',
        '    unsigned long flags, start, aligned, padding, size = THREAD_SIZE + PAGE_SIZE;\n')
    editor.edit('    if (!IS_ALIGNED(start, THREAD_ALIGN)) {\n',
        '    if (!IS_ALIGNED(start, PAGE_SIZE)) {\n')
    old = ('    if (free->va_end - start <= size) {\n'
        '        '+failure('CARVE_EXTENT', 'result', '5')+'\n        goto out;\n    }\n')
    new = '''    /* Consume the bounded prefix in this SAME reservation, never discard it
     * or create a second split node. All arithmetic/refusals precede mutation. */
    if (start > ~0UL - (THREAD_ALIGN - 1u)) {
        '''+failure('CARVE_EXTENT', 'result', '6')+'''
        goto out;
    }
    aligned = ALIGN(start, THREAD_ALIGN);
    padding = aligned - start;
    if (padding >= THREAD_ALIGN || !IS_ALIGNED(padding, PAGE_SIZE)) {
        '''+failure('CARVE_EXTENT', 'result', '7')+'''
        goto out;
    }
    size += padding;
    if (size > ARRAY_SIZE(stack->entries) * PAGE_SIZE) {
        '''+failure('CARVE_EXTENT', 'result', '8')+'''
        goto out;
    }
'''+old
    editor.edit(old, new)
    editor.edit('    /* Exactly ONE real free extent; no global scan, retry, purge or notifier.\n'
        '     * Only a left edge may be shortened. No extra split metadata can be born. */\n',
        '    /* Exactly ONE real free extent; no global scan, retry, purge or notifier.\n'
        '     * Only its left edge is shortened, including all owned alignment padding.\n'
        '     * No extra split metadata can be born. */\n')
    editor.edit('    unsigned long address = stack->area.va_start;\n',
        '    unsigned long address = lsf_cleanup_stack_start(stack);\n'
        '    unsigned long base = stack->area.va_start;\n'
        '    unsigned long count = stack->vm.size / PAGE_SIZE;\n'
        '    unsigned long offset = (address - base) / PAGE_SIZE;\n')
    editor.edit('    if (stack->mapped) {\n',
        '    if (stack->vm.addr != (void *)base ||\n'
        '        !IS_ALIGNED(base, PAGE_SIZE) || !IS_ALIGNED(stack->vm.size, PAGE_SIZE) ||\n'
        '        stack->vm.size > ARRAY_SIZE(stack->entries) * PAGE_SIZE ||\n'
        '        count < ARRAY_SIZE(stack->pages) + 1u || count > ARRAY_SIZE(stack->entries) ||\n'
        '        offset >= THREAD_ALIGN / PAGE_SIZE ||\n'
        '        offset + ARRAY_SIZE(stack->pages) + 1u != count ||\n'
        '        stack->area.va_end - base != stack->vm.size)\n'
        '        return -EIO;\n'
        '    if (stack->mapped) {\n')
    editor.edit('        for (i = 0; i <= ARRAY_SIZE(stack->pages); ++i) {\n'
        '            pte_t *entry = lsf_cleanup_existing_pte(address + i * PAGE_SIZE);\n',
        '        for (i = 0; i < count; ++i) {\n'
        '            pte_t *entry = lsf_cleanup_existing_pte(base + i * PAGE_SIZE);\n')
    editor.edit('                (i == ARRAY_SIZE(stack->pages) ? !pte_none(ptep_get(entry)) :\n'
        '                 !pte_same(pte_mkold(pte_mkclean(ptep_get(entry))),\n'
        '                    pte_mkold(pte_mkclean(mk_pte(stack->pages[i], pgprot_nx(PAGE_KERNEL)))))))\n',
        '                (i < offset || i >= offset + ARRAY_SIZE(stack->pages) ?\n'
        '                 !pte_none(ptep_get(entry)) :\n'
        '                 !pte_same(pte_mkold(pte_mkclean(ptep_get(entry))),\n'
        '                    pte_mkold(pte_mkclean(mk_pte(stack->pages[i - offset], pgprot_nx(PAGE_KERNEL)))))))\n')
    editor.edit('    unsigned long start, bytes;\n    unsigned int i;\n',
        '    unsigned long start, bytes;\n    unsigned int i, count, offset;\n')
    editor.edit('    trace_alloc_vmap_area(error ? VMALLOC_END : stack->area.va_start,\n'
        '        THREAD_SIZE + PAGE_SIZE, THREAD_ALIGN, VMALLOC_START, VMALLOC_END, !!error);\n',
        '    trace_alloc_vmap_area(error ? VMALLOC_END : stack->area.va_start,\n'
        '        error ? THREAD_SIZE + PAGE_SIZE : stack->vm.size,\n'
        '        PAGE_SIZE, VMALLOC_START, VMALLOC_END, !!error);\n')
    editor.edit('    start = stack->area.va_start;\n'
        '    /* Preflight EVERY leaf and the full guard before the FIRST PTE write.\n'
        '     * Missing/huge/shared nonempty entries refuse without table allocation. */\n'
        '    for (i = 0; i <= ARRAY_SIZE(stack->pages); ++i) {\n'
        '        stack->entries[i] = lsf_cleanup_existing_pte_observed(start + i * PAGE_SIZE, observation, i);\n',
        '    start = lsf_cleanup_stack_start(stack);\n'
        '    count = stack->vm.size / PAGE_SIZE;\n'
        '    offset = (start - stack->area.va_start) / PAGE_SIZE;\n'
        '    /* Preflight EVERY prefix/body/guard leaf before the FIRST PTE write.\n'
        '     * At most eight pointers, exactly four physical payload pages.\n'
        '     * Missing/huge/shared nonempty entries refuse without table allocation. */\n'
        '    for (i = 0; i < count; ++i) {\n'
        '        stack->entries[i] = lsf_cleanup_existing_pte_observed(\n'
        '            stack->area.va_start + i * PAGE_SIZE, observation, i);\n')
    editor.edit('        set_pte_at(&init_mm, start + i * PAGE_SIZE, stack->entries[i],\n',
        '        set_pte_at(&init_mm, start + i * PAGE_SIZE, stack->entries[offset + i],\n')
    editor.edit('    task->stack = stack->vm.addr;\n', '    task->stack = (void *)start;\n')
    editor.edit('    if (stack != lsf_cleanup_stack_live || stack->vm.addr != task->stack ||\n',
        '    if (stack != lsf_cleanup_stack_live ||\n'
        '        (void *)lsf_cleanup_stack_start(stack) != task->stack ||\n')
    return editor.finish()


def retirement(text):
    editor = Editor(text)
    old = '        task->stack == stack->vm.addr && task->stack_vm_area == &stack->vm'
    require(text.count(old) == 2, 'stack-alignment-two-retirement-identities')
    # Distinct suffixes keep the exact reverse projection unambiguous.
    for suffix in (';\n', ' &&\n'):
        editor.edit(old+suffix,
            '        task->stack == (void *)lsf_cleanup_stack_start(stack) &&\n'
            '        task->stack_vm_area == &stack->vm'+suffix)
    return editor.finish()


def transform(outputs):
    for name, (size, checksum) in PREIMAGES.items():
        require(name in outputs and type(outputs[name]) is bytes and len(outputs[name]) == size
            and hashlib.sha256(outputs[name]).hexdigest() == checksum,
            'stack-alignment-compiled-505-preimage')
    result = dict(outputs)
    result['mm/lsf-cleanup-stack.c'] = stack(outputs['mm/lsf-cleanup-stack.c'].decode()).encode()
    result['mm/lsf-cleanup-stack-retire.c'] = retirement(outputs['mm/lsf-cleanup-stack-retire.c'].decode()).encode()
    require(set(result) == set(outputs) and
        {name for name in result if result[name] != outputs[name]} == set(PREIMAGES),
        'stack-alignment-only-two-private-derived-files')
    return result
