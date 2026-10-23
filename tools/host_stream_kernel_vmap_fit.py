"""Choose one fitting original extent with one finite shared search budget.

Only the consumed raw prefix must lie inside VMALLOC. The original right node
may extend beyond that window; its end and the complete restore path are intact.
This exact post-e518 projection does not create page tables or retry PTE refusal.
"""
import hashlib

from tools.host_stream_kernel_constructor_failure import Editor, failure
from tools.host_stream_kernel_cleanup_native import require
from tools.host_stream_kernel_vmap_extent import SELECTOR as PREVIOUS_SELECTOR

NAME = 'mm/lsf-cleanup-stack.c'
PREIMAGE = (18870, 'b0929866ecea78936b19ce63e10da8888d3035b11ca43ddb9a7fb252d2045dc1')

FIT = '''/* Shared side-effect-free geometry: return the existing finite failure detail.
 * Only the consumed prefix belongs to this reservation. The untouched original
 * right node may extend outside VMALLOC, but must remain strictly nonempty. */
static unsigned int lsf_cleanup_stack_fit(const struct vmap_area *area,
    unsigned long *reservation_size)
{
    unsigned long start = area->va_start;
    unsigned long aligned, padding, size = THREAD_SIZE + PAGE_SIZE;
    if (!IS_ALIGNED(start, PAGE_SIZE))
        return 1u;
    if (start < VMALLOC_START)
        return 2u;
    if (start >= VMALLOC_END)
        return 3u;
    if (area->va_end <= start)
        return 4u;
    if (start > ~0UL - (THREAD_ALIGN - 1u))
        return 6u;
    aligned = ALIGN(start, THREAD_ALIGN);
    padding = aligned - start;
    if (padding >= THREAD_ALIGN || !IS_ALIGNED(padding, PAGE_SIZE))
        return 7u;
    size += padding;
    if (size > (THREAD_SIZE / PAGE_SIZE + THREAD_ALIGN / PAGE_SIZE) * PAGE_SIZE)
        return 8u;
    if (size > VMALLOC_END - start)
        return 3u;
    if (area->va_end - start <= size)
        return 5u;
    if (reservation_size)
        *reservation_size = size;
    return 0;
}

'''

SELECTOR = '''/* Borrow original augmented RB metadata under the existing free-tree lock.
 * One combined 64-unit budget covers every traversal state and fit predicate.
 * In-order search prunes subtrees that cannot leave a nonempty right remainder.
 * Return one eligible original left edge; PTE refusal never resumes this walk. */
static struct vmap_area *lsf_cleanup_stack_extent(void)
{
    struct rb_node *node = free_vmap_area_root.rb_node;
    struct rb_node *previous = NULL;
    unsigned int work = 0;
    while (node && work < 64u) {
        struct rb_node *parent = rb_parent(node), *next;
        struct vmap_area *area = rb_entry(node, struct vmap_area, rb_node);
        unsigned int consider = 0;
        ++work;
        if (previous == parent) {
            if (area->subtree_max_size <= THREAD_SIZE + PAGE_SIZE)
                goto ascend;
            if (area->va_start < VMALLOC_START) {
                if (get_subtree_max_size(node->rb_right) > THREAD_SIZE + PAGE_SIZE) {
                    next = node->rb_right;
                    goto move;
                }
                goto ascend;
            }
            if (get_subtree_max_size(node->rb_left) > THREAD_SIZE + PAGE_SIZE) {
                next = node->rb_left;
                goto move;
            }
            consider = 1u;
        } else if (previous == node->rb_left) {
            consider = 1u;
        } else if (previous != node->rb_right) {
            return NULL;
        }
        if (consider && area->va_start < VMALLOC_END) {
            if (work == 64u)
                return NULL;
            ++work;
            if (!lsf_cleanup_stack_fit(area, NULL))
                return area;
            if (get_subtree_max_size(node->rb_right) > THREAD_SIZE + PAGE_SIZE) {
                next = node->rb_right;
                goto move;
            }
        }
ascend:
        next = parent;
move:
        previous = node;
        node = next;
    }
    return NULL; /* No proved fit, including an unfinished or cyclic walk. */
}

'''


def transform(outputs):
    raw = outputs.get(NAME)
    require(type(raw) is bytes and (len(raw), hashlib.sha256(raw).hexdigest()) == PREIMAGE,
        'vmap-fit-compiled-e518-preimage')
    original = raw.decode()
    editor = Editor(original)
    editor.edit(PREVIOUS_SELECTOR, FIT + SELECTOR)
    editor.edit('    unsigned long flags, start, aligned, padding, size = THREAD_SIZE + PAGE_SIZE;\n',
        '    unsigned long flags, start, size;\n    unsigned int detail;\n')
    editor.edit('    /* Select exactly one existing VMALLOC-domain left edge. All original\n'
        '     * bounds, fit, alignment and PTE checks still apply without retry. */\n',
        '    /* Select one fitting original left edge; do not retry failed PTEs. */\n')
    start = original.index('    start = free->va_start;\n')
    end = original.index('    stack->area.va_start = start;\n', start)
    editor.edit(original[start:end],
        '    start = free->va_start;\n'
        '    detail = lsf_cleanup_stack_fit(free, &size);\n'
        '    if (detail) {\n        '+failure('CARVE_EXTENT', 'result', 'detail')+'\n'
        '        goto out;\n    }\n')
    result = dict(outputs)
    result[NAME] = editor.finish().encode()
    require(set(result) == set(outputs) and
        [name for name in result if result[name] != outputs[name]] == [NAME],
        'vmap-fit-only-private-selection-and-geometry')
    return result
