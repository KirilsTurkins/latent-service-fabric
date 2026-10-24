"""Select one existing VMALLOC-domain left edge without splitting or retry.

The original global free tree spans the whole unsigned address space. Its first
list entry is not a VMALLOC allocator result. This bounded lower-bound lookup
borrows original RB metadata and allocates nothing; an unfinished walk refuses.
"""
import hashlib

from tools.host_stream_kernel_constructor_failure import Editor, failure
from tools.host_stream_kernel_cleanup_native import require

NAME = 'mm/lsf-cleanup-stack.c'
PREIMAGE = (18015, 'c8125df6d52c991bd1996e6cf591606b71d4289abe2a967f81ea99ae5b82d9e1')

SELECTOR = '''/* The original free tree includes non-VMALLOC addresses. Borrow at most
 * 64 existing nodes to find its first left edge in the fixed VMALLOC domain.
 * Do not clip a spanning extent, scan candidates or retry a failed fit/PTE. */
static struct vmap_area *lsf_cleanup_stack_extent(void)
{
    struct rb_node *node = free_vmap_area_root.rb_node;
    struct vmap_area *first = NULL;
    unsigned int visited = 0;
    while (node && visited < 64u) {
        struct vmap_area *area = rb_entry(node, struct vmap_area, rb_node);
        ++visited;
        if (area->va_start >= VMALLOC_START) {
            first = area;
            node = node->rb_left;
        } else {
            node = node->rb_right;
        }
    }
    if (node)
        return NULL; /* The finite walk did not establish a lower bound. */
    return first;
}

'''


def transform(outputs):
    raw = outputs.get(NAME)
    require(type(raw) is bytes and (len(raw), hashlib.sha256(raw).hexdigest()) == PREIMAGE,
        'vmap-extent-compiled-2460-preimage')
    editor = Editor(raw.decode())
    editor.edit('static int lsf_cleanup_stack_carve(struct lsf_cleanup_stack *stack,\n',
        SELECTOR+'static int lsf_cleanup_stack_carve(struct lsf_cleanup_stack *stack,\n')
    editor.edit('    /* Exactly ONE real free extent; no global scan, retry, purge or notifier.\n'
        '     * Only its left edge is shortened, including all owned alignment padding.\n'
        '     * No extra split metadata can be born. */\n'
        '    free = list_first_entry(&free_vmap_area_list, struct vmap_area, list);\n',
        '    /* Select exactly one existing VMALLOC-domain left edge. All original\n'
        '     * bounds, fit, alignment and PTE checks still apply without retry. */\n'
        '    free = lsf_cleanup_stack_extent();\n'
        '    if (!free) {\n        '+failure('CARVE_STATE', 'result', '4')+'\n'
        '        goto out;\n    }\n')
    result = dict(outputs)
    result[NAME] = editor.finish().encode()
    require(set(result) == set(outputs) and
        [name for name in result if result[name] != outputs[name]] == [NAME],
        'vmap-extent-only-private-selection')
    return result
