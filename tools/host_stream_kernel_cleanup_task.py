"""Uninstalled private cleanup task prefix, with a real pre-stack refusal.

Ordinary fork/kthread algorithms remain exact. No worker is created or declared
ready: guarded-stack/PID/security/RCU ownership is not implemented by this layer.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_retirement as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_task.json'
FIXTURE_SHA = 'bb9fd432193aa0ffc435eebc5d4de910eef3a8eb4b6ebc1655e91c2d060133b8'
FORK = 'kernel/fork.c'
EXTRAS = {FORK, 'kernel/kthread.c', 'arch/x86/kernel/process.c',
    'include/linux/sched/task.h', 'arch/x86/include/asm/page_64_types.h', 'include/linux/kthread.h'}
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 64 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-task-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-task-prefix.v1' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        value['parentSource'] == '334f95cd0627e4f02dd54d3ae07fa33d6417ff93' and
        set(value['source']) == EXTRAS and len(value['parentDerived']) == 3 and
        all(value[key] is False for key in ('taskCreated', 'executorReady',
            'stackOwnerImplemented', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-task-source-origin')
    return value


def definition(name):
    return preimages()['sections'][name]['text']


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == EXTRAS, 'cleanup-task-whole-membership')
    for name, row in value['source'].items():
        require(type(inputs[name]) is bytes and len(inputs[name]) == row['bytes'] and
            hashlib.sha256(inputs[name]).hexdigest() == row['sha256'], 'cleanup-task-whole-source')
    for row in value['sections'].values():
        text = inputs[row['source']].decode()
        require(text.count(row['text']) == 1, 'cleanup-task-definition-preimage')


GEOMETRY = '''int lsf_prepaid_cleanup_task_geometry(unsigned long *bytes, unsigned long *alignment)
{
    unsigned long actual_bytes = arch_task_struct_size;
    unsigned long actual_alignment = max_t(int, L1_CACHE_BYTES, ARCH_MIN_TASKALIGN);
    if (!bytes || !alignment || actual_bytes < sizeof(struct task_struct) ||
        actual_bytes > LSF_FACTORY_INFRA_BYTES || !actual_alignment ||
        actual_alignment > 64u || (actual_alignment & (actual_alignment - 1u)))
        return -EOPNOTSUPP;
    *bytes = actual_bytes;
    *alignment = actual_alignment;
    return 0;
}

'''


def private_prefix():
    raw = definition('dup_task_struct')
    before = raw[:raw.index('\terr = alloc_thread_stack_node(tsk, node);\n')]
    before = replace(before, 'static struct task_struct *dup_task_struct(struct task_struct *orig, int node)\n',
        'struct task_struct *lsf_prepaid_cleanup_dup_task_struct(\n'
        '    struct lsf_cleanup_task_source source, int node)\n')
    before = replace(before, '\ttsk = alloc_task_struct_node(node);\n',
        '\ttsk = lsf_factory_cleanup_task_claim(source);\n')
    before = replace(before, '\t\tnode = tsk_fork_get_node(orig);\n',
        '\t\tnode = tsk_fork_get_node(current);\n')
    before = replace(before, '\t\treturn NULL;\n', '\t\treturn ERR_PTR(-EOPNOTSUPP);\n')
    # arch_dup_task_struct(current) is the original actual no-allocation x86
    # copy/reset prefix. Source pins the complete architecture definition too.
    before = replace(before, '\terr = arch_dup_task_struct(tsk, orig);\n',
        '\terr = arch_dup_task_struct(tsk, current);\n')
    return GEOMETRY + before + '''    /* The original next call may take a global cached VM stack or allocate
     * a guarded mapping. Neither has this original owner yet. Refuse BEFORE
     * either operation and before all later task/security/PID publication.
     * This is a concrete unsupported constructor result, never worker success. */
    err = -EOPNOTSUPP;
free_tsk:
    if (!lsf_factory_cleanup_task_abort(source, tsk))
        return ERR_PTR(-EIO);
    return ERR_PTR(err);
}
'''


def kthreadd_prefix(text):
    original = definition('kthreadd')
    updated = replace(original, '\t\tif (list_empty(&kthread_create_list))\n',
        '\t\tif (list_empty(&kthread_create_list)\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\t    && !READ_ONCE(lsf_cleanup_pending)\n#endif\n\t\t   )\n')
    updated = replace(updated, '\t\twhile (!list_empty(&kthread_create_list)) {\n',
        '\t\twhile (!list_empty(&kthread_create_list)\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\t       || lsf_cleanup_pending\n#endif\n\t\t      ) {\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\t\tif (lsf_cleanup_pending) {\n'
        '\t\t\t\tstruct lsf_cleanup_request *owned = lsf_cleanup_pending;\n'
        '\t\t\t\tWRITE_ONCE(lsf_cleanup_pending, NULL);\n'
        '\t\t\t\tspin_unlock(&kthread_create_lock);\n'
        '\t\t\t\tlsf_cleanup_create_kthread(owned);\n'
        '\t\t\t\tspin_lock(&kthread_create_lock);\n'
        '\t\t\t\tcontinue;\n\t\t\t}\n#endif\n')
    text = replace(text, original, updated)
    text = replace(text, 'struct task_struct *kthreadd_task;\n',
        'struct task_struct *kthreadd_task;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'struct lsf_cleanup_request;\n'
        'static struct lsf_cleanup_request *lsf_cleanup_pending;\n'
        'static void lsf_cleanup_create_kthread(struct lsf_cleanup_request *);\n#endif\n')
    original = definition('__kthread_create_worker')
    return replace(text, original, original + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_cleanup_task.h>\n#include "lsf-cleanup-worker.c"\n#endif\n')


def transform(outputs, inputs):
    authenticate(inputs)
    for name, row in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == row['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == row['sha256'],
            'cleanup-task-parent-derived-preimage')
    outputs = dict(outputs)
    for name in EXTRAS:
        require(name not in outputs or outputs[name] == inputs[name], 'cleanup-task-existing-original')
        outputs[name] = inputs[name]
    name = 'net/device-prepaid.h'
    text = outputs[name].decode()
    text = replace(text, '    LSF_DEVICE_AUDIT_HEAD\n',
        '    LSF_DEVICE_AUDIT_HEAD,\n    LSF_DEVICE_CLEANUP_REQUEST,\n    LSF_DEVICE_CLEANUP_TASK\n')
    # The last delivery kind is explicitly selected in each of the existing
    # disjoint kind predicates; do not admit an enum range or application kind.
    text = replace(text, 'kind == LSF_DEVICE_AUDIT_HEAD;',
        'kind == LSF_DEVICE_AUDIT_HEAD ||\n'
        '        kind == LSF_DEVICE_CLEANUP_REQUEST || kind == LSF_DEVICE_CLEANUP_TASK;')
    outputs[name] = text.encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(), '    struct lsf_prepaid_ticket firmware;\n',
        '    struct lsf_prepaid_ticket firmware;\n'
        '    struct lsf_prepaid_ticket cleanup_request, cleanup_task;\n'
        '    unsigned int cleanup_attempted, cleanup_task_claimed;\n').encode()
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include "factory-private.h"\n',
        '#include "factory-private.h"\n#include <linux/kthread.h>\n'
        '#include <net/lsf_stream_cleanup_task.h>\n')
    text = replace(text, 'static_assert(sizeof(factory) + sizeof(lsf_device_uevent_taps) + LSF_BACKING_BYTES < LSF_BOOTSTRAP_CEILING);\n',
        '/* The sole private kthreadd pending pointer is additional actual static\n'
        ' * metadata inside the SAME original bootstrap ceiling, not another bank. */\n'
        'static_assert(sizeof(factory) + sizeof(lsf_device_uevent_taps) + LSF_BACKING_BYTES + sizeof(void *) < LSF_BOOTSTRAP_CEILING);\n')
    text = replace(text, '#include "factory-device.c"\n',
        '#include "factory-device.c"\n#include "factory-cleanup-task.c"\n')
    outputs[name] = replace(text,
        '    error = lsf_factory_device_initialize();\n    if (error)\n        goto out;\n',
        '    error = lsf_factory_device_initialize();\n    if (error)\n        goto out;\n'
        '    error = lsf_prepaid_cleanup_worker_create();\n    if (error) {\n'
        '        WRITE_ONCE(factory.uncertain, 1);\n        goto out;\n    }\n').encode()
    original = definition('dup_task_struct')
    outputs[FORK] = replace(inputs[FORK].decode(), original, original +
        '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_cleanup_task.h>\n'
        '#include "lsf-cleanup-task.c"\n#endif\n').encode()
    outputs['kernel/lsf-cleanup-task.c'] = private_prefix().encode()
    outputs['kernel/kthread.c'] = kthreadd_prefix(inputs['kernel/kthread.c'].decode()).encode()
    outputs['kernel/lsf-cleanup-worker.c'] = (OWNED / 'kernel-cleanup-worker.c').read_bytes()
    outputs['include/net/lsf_stream_cleanup_task.h'] = (OWNED / 'cleanup-task-private.h').read_bytes()
    outputs['net/factory-cleanup-task.c'] = (OWNED / 'factory-cleanup-task.c').read_bytes()
    return outputs


def derive(inputs):
    parent_inputs = {name: inputs[name] for name in prior.fixture()['source']}
    require(set(inputs) == set(parent_inputs) | EXTRAS, 'cleanup-task-complete-membership')
    return transform(prior.derive(parent_inputs), {name: inputs[name] for name in EXTRAS})
