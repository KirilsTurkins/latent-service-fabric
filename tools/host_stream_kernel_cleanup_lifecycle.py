"""Uninstalled original-owner creation metadata and final-stack handoff.

No linked/booted task, executor or physical retirement is qualified here. All
previous source algorithms and original bounds are retained. No build workflow
is added by this source layer.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_guarded_stack as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_lifecycle.json'
FIXTURE_SHA = 'e2519dc27c879ff74b54f5e9cba1e7b58a8066f8d95b9d65379527b78eae2665'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 32 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-lifecycle-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-lifecycle-source.v1' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        value['parentExecutedSource'] == '0694cb4092c76c2bbb65546bd20acb6e09a17707' and
        len(value['source']) == 11 and len(value['sections']) == 14 and
        len(value['parentDerived']) == 8 and value['runtimeStackHandoffSourceImplemented'] is True and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'runningTaskStackRetirementExecuted', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-lifecycle-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-lifecycle-whole-membership')
    for name, row in value['source'].items():
        require(type(inputs[name]) is bytes and len(inputs[name]) == row['bytes'] and
            hashlib.sha256(inputs[name]).hexdigest() == row['sha256'],
            'cleanup-lifecycle-whole-source')
    for row in value['sections'].values():
        raw = row['text'].encode()
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'] and
            inputs[row['source']].decode().count(row['text']) == 1,
            'cleanup-lifecycle-definition-preimage')


def definition(name):
    return preimages()['sections'][name]['text']


AFFINITY = '''/* The original helper's unlocked NULL check is explicitly racy and may
 * allocate. This private subset observes NULL under the SAME source pi_lock,
 * clears the borrowed destination pointer, and refuses before any allocation. */
static int lsf_cleanup_dup_empty_user_cpus(struct task_struct *dst,
    struct task_struct *src)
{
    unsigned long flags;
    int error;
    raw_spin_lock_irqsave(&src->pi_lock, flags);
    dst->user_cpus_ptr = NULL;
    error = src->user_cpus_ptr ? -EOPNOTSUPP : 0;
    raw_spin_unlock_irqrestore(&src->pi_lock, flags);
    return error;
}

'''


def initialized_task():
    text = definition('dup_task_struct')
    text = replace(text, 'static struct task_struct *dup_task_struct(struct task_struct *orig, int node)\n',
        'struct task_struct *lsf_prepaid_cleanup_dup_initialized(\n'
        '    struct lsf_cleanup_task_source source, int node)\n')
    text = replace(text, '\tstruct task_struct *tsk;\n\tint err;\n',
        '\tstruct task_struct *tsk;\n\tstruct task_struct *orig = current;\n\tint err;\n'
        '\n\t/* Keep enabled instrumentation real. Unowned enabled profiles refuse\n'
        '\t * BEFORE birth, rather than silently omitting the original calls. */\n'
        '\tif (current != kthreadd_task || in_interrupt() ||\n'
        '\t    IS_ENABLED(CONFIG_SCS) || IS_ENABLED(CONFIG_KCOV) ||\n'
        '\t    IS_ENABLED(CONFIG_KMSAN) || IS_ENABLED(CONFIG_DEBUG_LOCK_ALLOC))\n'
        '\t\treturn ERR_PTR(-EOPNOTSUPP);\n')
    text = replace(text, '\ttsk = alloc_task_struct_node(node);\n',
        '\ttsk = lsf_factory_cleanup_task_claim(source);\n')
    text = replace(text, '\t\treturn NULL;\n', '\t\treturn ERR_PTR(-EOPNOTSUPP);\n')
    text = replace(text, '\terr = alloc_thread_stack_node(tsk, node);\n',
        '\terr = lsf_prepaid_cleanup_stack_create(source, tsk);\n')
    text = replace(text, '\tdup_user_cpus_ptr(tsk, orig, node);\n',
        '\terr = lsf_cleanup_dup_empty_user_cpus(tsk, orig);\n'
        '\tif (err)\n\t\tgoto free_stack;\n')
    text = replace(text, '\treturn tsk;\n',
        '\tif (!lsf_factory_cleanup_task_initialized(source, tsk))\n'
        '\t\treturn ERR_PTR(-EIO);\n\treturn tsk;\n')
    text = replace(text, '\tfree_thread_stack(tsk);\n',
        '\tif (lsf_prepaid_cleanup_stack_abort_unpublished(source, tsk))\n'
        '\t\treturn ERR_PTR(-EIO);\n')
    text = replace(text, '\tfree_task_struct(tsk);\n\treturn NULL;\n',
        '\tif (!lsf_factory_cleanup_task_abort(source, tsk))\n'
        '\t\treturn ERR_PTR(-EIO);\n\treturn ERR_PTR(err);\n')
    return AFFINITY + text + '''
int lsf_prepaid_cleanup_abort_initialized(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    if (!lsf_factory_cleanup_task_abort_ready(source, task))
        return -EIO;
    /* Actual accounting was established exactly once by the copied original
     * initializer. Runtime exit already accounts its own stack separately. */
    exit_task_stack_account(task);
    if (lsf_prepaid_cleanup_stack_abort_unpublished(source, task))
        return -EIO;
    return lsf_factory_cleanup_task_abort(source, task) ? 0 : -EIO;
}
'''


def kthreadd_retirement(text):
    text = replace(text, '\t\t    && !READ_ONCE(lsf_cleanup_pending)\n',
        '\t\t    && !READ_ONCE(lsf_cleanup_pending)\n'
        '\t\t    && !lsf_factory_cleanup_retire_pending()\n')
    text = replace(text, '\t\t       || lsf_cleanup_pending\n',
        '\t\t       || lsf_cleanup_pending || lsf_factory_cleanup_retire_pending()\n')
    text = replace(text, '\t\t\tif (lsf_cleanup_pending) {\n',
        '\t\t\tif (lsf_factory_cleanup_retire_pending()) {\n'
        '\t\t\t\tspin_unlock(&kthread_create_lock);\n'
        '\t\t\t\tlsf_prepaid_cleanup_retire_one();\n'
        '\t\t\t\tspin_lock(&kthread_create_lock);\n'
        '\t\t\t\tcontinue;\n\t\t\t}\n'
        '\t\t\tif (lsf_cleanup_pending) {\n')
    return text


def transform(outputs, inputs):
    authenticate(inputs)
    for name, row in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == row['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == row['sha256'],
            'cleanup-lifecycle-parent-preimage')
    outputs = dict(outputs)
    for name, data in inputs.items():
        # Some of these TUs already contain reviewed private insertions. Whole
        # originals were authenticated above; never overwrite those derivations.
        if name not in outputs:
            outputs[name] = data
    name = 'net/device-prepaid.h'
    text = replace(outputs[name].decode(), '    LSF_DEVICE_CLEANUP_STACK\n',
        '    LSF_DEVICE_CLEANUP_STACK,\n    LSF_DEVICE_CLEANUP_KTHREAD\n')
    text = replace(text, 'kind == LSF_DEVICE_CLEANUP_STACK;',
        'kind == LSF_DEVICE_CLEANUP_STACK || kind == LSF_DEVICE_CLEANUP_KTHREAD;')
    outputs[name] = text.encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(), '    unsigned int cleanup_stack_attempted;\n',
        '    unsigned int cleanup_stack_attempted;\n'
        '    struct lsf_prepaid_ticket cleanup_kthread;\n'
        '    unsigned int cleanup_kthread_attempted, cleanup_lifecycle;\n'
        '    struct task_struct *cleanup_retire_task;\n').encode()
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_stack.h>\n',
        '#include <net/lsf_stream_cleanup_stack.h>\n'
        '#include <net/lsf_stream_cleanup_lifecycle.h>\n')
    outputs[name] = replace(text, '#include "factory-cleanup-stack.c"\n',
        '#include "factory-cleanup-stack.c"\n#include "factory-cleanup-lifecycle.c"\n').encode()
    name = 'kernel/fork.c'
    # Prototypes precede even the early original free_task_struct definition.
    text = replace(outputs[name].decode(), definition('free_task_struct'),
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_cleanup_lifecycle.h>\n#endif\n' +
        replace(definition('free_task_struct'), '\tkmem_cache_free(task_struct_cachep, tsk);\n',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tif (lsf_factory_cleanup_task_final(tsk))\n\t\treturn;\n#endif\n'
            '\tkmem_cache_free(task_struct_cachep, tsk);\n'))
    original = definition('release_task_stack')
    text = replace(text, original, replace(original, '\tfree_thread_stack(tsk);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_prepaid_cleanup_stack_release(tsk))\n\t\treturn;\n#endif\n'
        '\tfree_thread_stack(tsk);\n'))
    outputs[name] = replace(text, '#include "lsf-cleanup-task.c"\n',
        '#include "lsf-cleanup-task.c"\n#include "lsf-cleanup-lifecycle-task.c"\n').encode()
    name = 'kernel/kthread.c'
    text = replace(outputs[name].decode(), definition('free_kthread_struct'),
        replace(definition('free_kthread_struct'), '\tstruct kthread *kthread;\n',
            '\tstruct kthread *kthread;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tif (lsf_prepaid_cleanup_kthread_free(k))\n\t\treturn;\n#endif\n'))
    text = replace(text, 'struct task_struct *kthreadd_task;\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_cleanup_lifecycle.h>\n#endif\n'
        'struct task_struct *kthreadd_task;\n')
    text = kthreadd_retirement(text)
    outputs[name] = replace(text, '#include "lsf-cleanup-worker.c"\n',
        '#include "lsf-cleanup-worker.c"\n#include "lsf-cleanup-lifecycle.c"\n').encode()
    name = 'kernel/lsf-cleanup-worker.c'
    text = replace(outputs[name].decode(), 'static_assert(sizeof(lsf_cleanup_pending) == sizeof(void *));\n',
        'static_assert(sizeof(lsf_cleanup_pending) == sizeof(void *));\n'
        'static struct task_struct *lsf_cleanup_prepare_unpublished(struct lsf_cleanup_request *);\n')
    outputs[name] = replace(text,
        '    task = lsf_prepaid_cleanup_dup_task_struct(owned->source, owned->create.node);\n',
        '    task = lsf_cleanup_prepare_unpublished(owned);\n').encode()
    name = 'mm/vmalloc.c'
    outputs[name] = replace(outputs[name].decode(), '#include "lsf-cleanup-stack.c"\n',
        '#include <net/lsf_stream_cleanup_lifecycle.h>\n'
        '#include "lsf-cleanup-stack.c"\n#include "lsf-cleanup-stack-retire.c"\n').encode()
    outputs['kernel/lsf-cleanup-lifecycle-task.c'] = initialized_task().encode()
    for destination, original in {
        'include/net/lsf_stream_cleanup_lifecycle.h': 'cleanup-lifecycle-private.h',
        'net/factory-cleanup-lifecycle.c': 'factory-cleanup-lifecycle.c',
        'mm/lsf-cleanup-stack-retire.c': 'cleanup-stack-retire.c',
        'kernel/lsf-cleanup-lifecycle.c': 'kernel-cleanup-lifecycle.c',
    }.items():
        outputs[destination] = (OWNED / original).read_bytes()
    return outputs


def derive(inputs):
    names = set(prior.prior.prior.fixture()['source']) | prior.prior.EXTRAS | set(prior.preimages()['source'])
    require(set(inputs) == names | set(preimages()['source']), 'cleanup-lifecycle-complete-membership')
    return transform(prior.derive({name: inputs[name] for name in names}),
        {name: inputs[name] for name in preimages()['source']})
