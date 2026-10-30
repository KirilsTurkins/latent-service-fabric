"""Bind private Task identity to the same original geometry that funded birth.

The exact failed740 source used sizeof(task_struct) after funding Linux's smaller
boot-selected FPU tail. Geometry reads stay before locks, including their existing
numeric refusal observation; physical identity grants no new operation authority.
"""
import hashlib
import re

from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_cleanup_native import function, require

NAME = 'net/factory-cleanup-provider-operation.c'
PREIMAGE = (12648, '490f96129eb9055e6b2cbcc64c3c4f3bc157d86c41db04c34516b945a64c8c7e')
CALLERS = (
    'int lsf_factory_cleanup_provider_physical_current(',
    'int lsf_factory_cleanup_provider_snapshot_source(',
    'void lsf_factory_cleanup_provider_dispatch_begin(',
    'void lsf_factory_cleanup_provider_dispatch_end(',
    'int lsf_factory_cleanup_provider_operation_current(',
)


def transform(outputs):
    raw = outputs.get(NAME)
    require(type(raw) is bytes and (len(raw), hashlib.sha256(raw).hexdigest()) == PREIMAGE,
        'task-identity-compiled-740-preimage')
    original = raw.decode()
    editor = Editor(original)
    editor.edit('static int lsf_cleanup_provider_physical_locked(struct lsf_cleanup_task_source *source)\n',
        'static int lsf_cleanup_provider_physical_locked(struct lsf_cleanup_task_source *source,\n'
        '    unsigned long task_bytes, unsigned long task_alignment)\n')
    editor.edit('        root->bytes < sizeof(*factory.device) || task->bytes < sizeof(*current) ||\n',
        '        root->bytes < sizeof(*factory.device) || !task_bytes || !task_alignment ||\n'
        '        task->bytes < task_bytes || (address & (task_alignment - 1u)) ||\n')
    for signature in CALLERS:
        before = function(original, signature)
        after = before
        declaration = re.search(r'    unsigned long flags[^;]*;\n', after)
        require(declaration is not None, 'task-identity-original-flags-declaration')
        after = (after[:declaration.end()] +
            '    unsigned long task_bytes = 0, task_alignment = 0;\n' + after[declaration.end():])
        lock = '    spin_lock_irqsave(&pool_lock, flags);\n'
        require(after.count(lock) == 1, 'task-identity-one-original-lock')
        after = after.replace(lock,
            '    /* Reuse the same boot-selected geometry that funded the original Task.\n'
            '     * Invalid geometry cannot make an in-bank Task current; foreign Tasks\n'
            '     * still take the original zero-result path before this value is used. */\n'
            '    if (lsf_prepaid_cleanup_task_geometry(&task_bytes, &task_alignment)) {\n'
            '        task_bytes = 0;\n        task_alignment = 0;\n    }\n' + lock)
        after, count = re.subn(r'lsf_cleanup_provider_physical_locked\((source|&actual|&source)\)',
            r'lsf_cleanup_provider_physical_locked(\1, task_bytes, task_alignment)', after)
        require(count == 1, 'task-identity-one-private-call')
        editor.edit(before, after)
    result = dict(outputs)
    result[NAME] = editor.finish().encode()
    require(set(result) == set(outputs) and
        [name for name in result if result[name] != outputs[name]] == [NAME],
        'task-identity-only-private-geometry-delta')
    return result
