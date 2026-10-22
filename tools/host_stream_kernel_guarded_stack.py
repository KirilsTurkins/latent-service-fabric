"""Uninstalled guarded alias for the actual private, unpublished task prefix.

No Linux execution or running-task/RCU retirement is qualified by this source.
The original 512 KiB bank and 192 KiB infrastructure region are unchanged.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_task as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_guarded_stack.json'
FIXTURE_SHA = '4138d1df3bda6beab4db7ea891cdfd1cb315a5c0f4ba236689075a82d1e25a0b'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 32 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'guarded-stack-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-guarded-stack-source.v1' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        len(value['source']) == 6 and len(value['sections']) == 9 and
        value['stackMappingSourceImplemented'] is True and
        all(value[name] is False for name in ('linuxMappingExecuted', 'taskCreated',
            'executorReady', 'runningTaskStackRetirementImplemented',
            'completeAllocationClosure', 'productionInstallation')),
        'guarded-stack-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'guarded-stack-whole-membership')
    for name, row in value['source'].items():
        require(type(inputs[name]) is bytes and len(inputs[name]) == row['bytes'] and
            hashlib.sha256(inputs[name]).hexdigest() == row['sha256'],
            'guarded-stack-whole-source')
    for row in value['sections'].values():
        require(inputs[row['source']].decode().count(row['text']) == 1,
            'guarded-stack-definition-preimage')


def transform(outputs, inputs):
    authenticate(inputs)
    outputs = dict(outputs)
    for name in inputs:
        require(name not in outputs or outputs[name] == inputs[name],
            'guarded-stack-existing-original')
        outputs[name] = inputs[name]
    name = 'net/device-prepaid.h'
    text = outputs[name].decode()
    text = replace(text, '    LSF_DEVICE_CLEANUP_TASK\n',
        '    LSF_DEVICE_CLEANUP_TASK,\n    LSF_DEVICE_CLEANUP_STACK\n')
    text = replace(text, 'kind == LSF_DEVICE_CLEANUP_TASK;',
        'kind == LSF_DEVICE_CLEANUP_TASK || kind == LSF_DEVICE_CLEANUP_STACK;')
    outputs[name] = text.encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(),
        '    unsigned int cleanup_attempted, cleanup_task_claimed;\n',
        '    unsigned int cleanup_attempted, cleanup_task_claimed;\n'
        '    struct lsf_prepaid_ticket cleanup_stack;\n'
        '    unsigned int cleanup_stack_attempted;\n').encode()
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_task.h>\n',
        '#include <net/lsf_stream_cleanup_task.h>\n#include <net/lsf_stream_cleanup_stack.h>\n')
    text = replace(text, 'LSF_BACKING_BYTES + sizeof(void *) < LSF_BOOTSTRAP_CEILING);',
        'LSF_BACKING_BYTES + 2u * sizeof(void *) < LSF_BOOTSTRAP_CEILING);')
    outputs[name] = replace(text, '#include "factory-cleanup-task.c"\n',
        '#include "factory-cleanup-task.c"\n#include "factory-cleanup-stack.c"\n').encode()
    # This is the original actual copied task, not a fabricated Linux task.
    # Advance through a real owned stack birth, then unwind before the still
    # unclosed task instrumentation/security/PID/scheduler constructor chain.
    name = 'kernel/lsf-cleanup-task.c'
    old = prior.private_prefix()
    require(outputs[name].decode() == old, 'guarded-stack-private-prefix-preimage')
    start = old.index('    /* The original next call may take a global cached VM stack')
    prefix = old[:start]
    outputs[name] = (prefix + '''    err = lsf_prepaid_cleanup_stack_create(source, tsk);
    if (err)
        goto free_tsk;
    /* No task has been published, scheduled, or handed to a running worker.
     * The next original task setup/instrumentation chain is not owned yet.
     * Return this REAL guarded alias synchronously before its parent view. */
    if (lsf_prepaid_cleanup_stack_abort_unpublished(source, tsk))
        return ERR_PTR(-EIO);
    err = -EOPNOTSUPP;
free_tsk:
    if (!lsf_factory_cleanup_task_abort(source, tsk))
        return ERR_PTR(-EIO);
    return ERR_PTR(err);
}
''').encode()
    name = 'kernel/fork.c'
    outputs[name] = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_task.h>\n',
        '#include <net/lsf_stream_cleanup_task.h>\n#include <net/lsf_stream_cleanup_stack.h>\n').encode()
    name = 'mm/vmalloc.c'
    text = inputs[name].decode()
    original = preimages()['sections']['alloc_vmap_area']['text']
    text = replace(text, original, original + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <linux/kthread.h>\n#include <net/lsf_stream_cleanup_stack.h>\n'
        '#include "lsf-cleanup-stack.c"\n#endif\n')
    original = preimages()['sections']['remove_vm_area']['text']
    guarded = replace(original, '\tva = find_unlink_vmap_area((unsigned long)addr);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_prepaid_cleanup_stack_foreign_unmap(addr))\n\t\treturn NULL;\n#endif\n'
        '\tva = find_unlink_vmap_area((unsigned long)addr);\n')
    outputs[name] = replace(text, original, guarded).encode()
    outputs['mm/lsf-cleanup-stack.c'] = (OWNED / 'cleanup-stack-vmap.c').read_bytes()
    outputs['include/net/lsf_stream_cleanup_stack.h'] = (OWNED / 'cleanup-stack-private.h').read_bytes()
    outputs['net/factory-cleanup-stack.c'] = (OWNED / 'factory-cleanup-stack.c').read_bytes()
    return outputs


def derive(inputs):
    before = set(prior.prior.fixture()['source']) | prior.EXTRAS
    require(set(inputs) == before | set(preimages()['source']),
        'guarded-stack-complete-membership')
    return transform(prior.derive({name: inputs[name] for name in before}),
        {name: inputs[name] for name in preimages()['source']})
