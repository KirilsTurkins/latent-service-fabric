"""Return the real provider association reference after original WQ stop.

The failed489 source already has a separate original set_worker_dying reference
for stop_put. Preserve the association's early-exit protection and consume it
once using the existing stop state. This is source composition, not retirement
qualification; the original probe, scheduler and final-return guards remain.
"""
import hashlib

from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_cleanup_native import function, require

PREIMAGES = {
    'include/net/lsf_stream_cleanup_provider_executor.h':
        (5788, '3bdff7e57b3f8b7e29f9d65b3c292ea94d59acfbbe82bb65ce3352028673bcd7'),
    'net/factory-cleanup-provider-retirement.c':
        (7954, '5cf8c1df21f5ff7c542bba7f3c226689d929128e6fe1a190dc711dc602fcc601'),
    'kernel/workqueue.c':
        (236419, '09a491c07228b6107abb2341da046aa648cf10682ae0fb986dda532e94615ebf'),
    'kernel/lsf-cleanup-constructor.c':
        (21986, '252579386b3cc6c6624ecf151fa1c80d89a8c6d705d280f27a4f541a4b9bc893'),
}

DECLARATION = (
    'int lsf_factory_cleanup_provider_task_reference_take(struct lsf_cleanup_task_source,\n'
    '    const void *, const struct task_struct *);\n')

TAKE = '''/* Original reap has completed stop_put outside all factory locks. The
 * association still protects this exact Task, even if the worker exited early.
 * State 0->1 consumes only that reference; part_finish sets 2 afterwards. */
int lsf_factory_cleanup_provider_task_reference_take(struct lsf_cleanup_task_source source,
    const void *worker, const struct task_struct *task)
{
    struct lsf_prepaid_view *record;
    unsigned long flags;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_cleanup_lifecycle_identity_locked(source, task) || factory.pool.poisoned ||
        factory.device->cleanup_physical_role != LSF_CLEANUP_PHYSICAL_PROVIDER ||
        factory.device->cleanup_worker_associated != 1u || factory.device->cleanup_worker_stop != 0u)
        goto poison;
    record = lsf_provider_part_record_locked(source, LSF_PROVIDER_WORKER, worker);
    if (!record || record->deferred != LSF_PREPAID_QUEUED)
        goto poison;
    /* No TASK_DEAD premise: stop completion may precede final do_exit. Original
     * scheduler/stack references retain their own real physical continuations. */
    factory.device->cleanup_worker_stop = 1u;
    result = 1;
    goto out;
poison:
    lsf_cleanup_lifecycle_poison_locked();
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

'''


def reap_workers(original):
    editor = Editor(original)
    editor.edit('\t\tstruct lsf_cleanup_task_source source;\n',
        '\t\tstruct lsf_cleanup_task_source source;\n'
        '\t\tstruct task_struct *association_task = NULL;\n')
    editor.edit('\t\tlist_del_init(&worker->entry);\n',
        '\t\tlist_del_init(&worker->entry);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (owned)\n\t\t\tassociation_task = worker->task;\n#endif\n')
    editor.edit('\t\tif (owned)\n'
        '\t\t\t(void)lsf_factory_cleanup_provider_part_finish(source, LSF_PROVIDER_WORKER, worker);\n',
        '\t\tif (owned) {\n'
        '\t\t\tif (!lsf_factory_cleanup_provider_task_reference_take(source, worker, association_task))\n'
        '\t\t\t\treturn; /* Unknown/repeated custody retains the actual reference. */\n'
        '\t\t\tput_task_struct(association_task); /* LAST Task use. */\n'
        '\t\t\t(void)lsf_factory_cleanup_provider_part_finish(source, LSF_PROVIDER_WORKER, worker);\n'
        '\t\t}\n')
    return editor.finish()


def retirement(original):
    editor = Editor(original)
    editor.edit('int lsf_factory_cleanup_provider_part_finish(struct lsf_cleanup_task_source source,\n',
        TAKE+'int lsf_factory_cleanup_provider_part_finish(struct lsf_cleanup_task_source source,\n')
    editor.edit('    if (part == LSF_PROVIDER_CONTROL &&\n',
        '    if (record && part == LSF_PROVIDER_WORKER &&\n'
        '        (!factory.device->cleanup_worker_associated || factory.device->cleanup_worker_stop != 1u))\n'
        '        goto poison;\n'
        '    if (part == LSF_PROVIDER_CONTROL &&\n')
    return editor.finish()


def constructor(original):
    editor = Editor(original)
    editor.edit('\tif (kthread_error) {\n',
        '\tif (kthread_error) {\n\t\tretval = kthread_error;\n')
    return editor.finish()


def transform(outputs):
    for name, expected in PREIMAGES.items():
        raw = outputs.get(name)
        require(type(raw) is bytes and (len(raw), hashlib.sha256(raw).hexdigest()) == expected,
            'provider-task-reference-compiled-489-preimage')
    result = dict(outputs)
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    editor = Editor(outputs[name].decode())
    editor.edit('#endif\n', DECLARATION+'#endif\n')
    result[name] = editor.finish().encode()
    name = 'kernel/workqueue.c'
    text = outputs[name].decode()
    before = function(text, 'static void reap_dying_workers(')
    editor = Editor(text)
    editor.edit(before, reap_workers(before))
    result[name] = editor.finish().encode()
    name = 'net/factory-cleanup-provider-retirement.c'
    result[name] = retirement(outputs[name].decode()).encode()
    name = 'kernel/lsf-cleanup-constructor.c'
    result[name] = constructor(outputs[name].decode()).encode()
    require(set(result) == set(outputs) and
        {name for name in result if result[name] != outputs[name]} == set(PREIMAGES),
        'provider-task-reference-four-output-delta')
    return result
