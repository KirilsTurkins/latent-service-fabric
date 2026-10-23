"""Actual creator/opener last accesses and worker/IRQ request drain.

Full constructor consumers remain disconnected. This is source composition,
not execution, observer/bootstrap qualification or physical backing return.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_association as prior
from tools.host_stream_kernel_device_security import function

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_close.json'
FIXTURE_SHA = 'a603cf1a3c5c2b634cd9fe8b2a4d54d219ed754d4cfa116f05ea9deb4c597198'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 16 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-close-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-close-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 1 and len(value['sections']) == 3 and len(value['parentDerived']) == 7 and
        len(value['parentSections']) == 3 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'factoryCallsFullWorkerCreate', 'pendingConsumerCallsFullClone', 'actualWorkerStop',
            'actualIrqExecution', 'actualRcuExecution', 'observerClosure', 'bootstrapQualified',
            'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-close-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-close-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-close-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-close-definition-preimage')


def creator(text):
    old = function(text, 'static void __maybe_unused lsf_cleanup_create_kthread_full(')
    new = replace(old,
        '\t\t/* Name and create are embedded in the original held bank. */\n',
        '\t\t/* Name and create are embedded in the original held bank. */\n'
        '\t\tif (!lsf_factory_cleanup_creator_error(source))\n\t\t\treturn;\n')
    new = replace(new, '\t\t\t/* Interrupted opener: retain the real original request. */\n',
        '\t\t\tlsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_CREATOR);\n')
    new = replace(new, '\t\tcreate->result = ERR_PTR(pid);\n\t\tcomplete(done);\n',
        '\t\tcreate->result = ERR_PTR(pid);\n'
        '\t\tlsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_CREATOR);\n'
        '\t\tcomplete(done); /* LAST borrowed completion access. */\n')
    new = replace(new, '\t\tcomplete(done); /* LAST borrowed completion access. */\n\t}\n',
        '\t\tcomplete(done); /* LAST borrowed completion access. */\n\t} else {\n'
        '\t\t/* Child owns its own actual create/worker/name accesses until\n'
        '\t\t * real Task return. Creator has no further request accesses. */\n'
        '\t\tlsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_CREATOR);\n\t}\n')
    return replace(text, old, new)


def opener(text):
    old = function(text, 'int lsf_prepaid_cleanup_worker_create_full(')
    new = replace(old, '        return -EBUSY;\n',
        '        lsf_factory_cleanup_stack_poison(source);\n'
        '        return -EBUSY; /* Unexpected pending owner: retain, never cancel it. */\n')
    new = replace(new, '        if (xchg(&owned->create.done, NULL))\n            return -EINTR;\n',
        '        if (xchg(&owned->create.done, NULL)) {\n'
        '            lsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_OPENER);\n'
        '            return -EINTR;\n        }\n')
    new = replace(new, '    if (IS_ERR(task))\n        return PTR_ERR(task);\n',
        '    if (IS_ERR(task)) {\n        error = PTR_ERR(task);\n'
        '        lsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_OPENER);\n'
        '        return error;\n    }\n')
    new = replace(new, '    wake_up_process(task);\n    return 0;\n',
        '    wake_up_process(task);\n'
        '    lsf_factory_cleanup_request_put(source, LSF_CLEANUP_REQUEST_OPENER);\n'
        '    return 0;\n')
    # Failed association has already poisoned; preserve all unknown lifetimes.
    return replace(text, old, new)


def factory_close(text):
    release = function(text, 'static int lsf_factory_release(')
    fence = release[release.index('    spin_lock_irqsave(&pool_lock, flags);\n'):
        release.index('    /* A finite scan')]
    new = replace(release, '    unsigned long flags;\n', '')
    new = replace(new, fence,
        '    lsf_cleanup_admission_close();\n'
        '    mutex_unlock(&factory_lock);\n'
        '    lsf_prepaid_cleanup_worker_destroy_full();\n'
        '    mutex_lock(&factory_lock);\n')
    text = replace(text, release, new)
    opening = function(text, 'static int lsf_factory_open(')
    new = replace(opening, '    int error = -EOPNOTSUPP;\n',
        '    int error = -EOPNOTSUPP;\n    unsigned int cleanup_close = 0;\n')
    new = replace(new, '    error = lsf_prepaid_cleanup_worker_create();\n    if (error) {\n'
        '        WRITE_ONCE(factory.uncertain, 1);\n',
        '    error = lsf_prepaid_cleanup_worker_create();\n    if (error) {\n'
        '        lsf_cleanup_admission_close();\n        cleanup_close = 1;\n')
    new = replace(new, '    mutex_unlock(&factory_lock);\n    return error;\n',
        '    mutex_unlock(&factory_lock);\n'
        '    if (cleanup_close)\n        lsf_prepaid_cleanup_worker_destroy_full();\n'
        '    return error;\n')
    return replace(text, opening, new)


def request_lookup(text):
    # Closed admission prevents new claims. It must not invalidate an existing
    # creator's born request or strand real interrupted-opener cancellation.
    return replace(text,
        '    if (!lsf_factory_cleanup_task_source_locked(actual) || factory.pool.stopped ||\n'
        '        factory.pool.contexts[actual.owner.slot].closed || factory.device->cleanup_task_claimed ||\n',
        '    if (!lsf_factory_cleanup_task_source_locked(actual) || factory.device->cleanup_task_claimed ||\n')


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-close-parent-preimage')
    for expected in preimages()['parentSections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            outputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-close-parent-definition-preimage')
    outputs = dict(outputs)
    include = '#include <net/lsf_stream_cleanup_close.h>\n'
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_association.h>\n',
        '#include <net/lsf_stream_cleanup_association.h>\n' + include)
    text = replace(text, '#include "factory-cleanup-association.c"\n',
        '#include "factory-cleanup-association.c"\n#include "factory-cleanup-close.c"\n')
    outputs[name] = factory_close(text).encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(),
        '    unsigned int cleanup_entry_started, cleanup_worker_associated;\n',
        '    unsigned int cleanup_entry_started, cleanup_worker_associated;\n'
        '    unsigned int cleanup_request_users, cleanup_worker_stop, cleanup_request_returned;\n').encode()
    name = 'net/factory-cleanup-task.c'
    text = outputs[name].decode()
    reserve = function(text, 'int lsf_factory_cleanup_task_reserve(')
    text = replace(text, reserve, replace(reserve, '    result = 0;\n',
        '    factory.device->cleanup_request_users =\n'
        '        LSF_CLEANUP_REQUEST_CREATOR | LSF_CLEANUP_REQUEST_OPENER;\n'
        '    result = 0;\n'))
    abort = function(text, 'int lsf_factory_cleanup_task_abort(')
    text = replace(text, abort, replace(abort, '    factory.device->cleanup_task_claimed = 2u;\n',
        '    factory.device->cleanup_task_claimed = 2u;\n'
        '    factory.device->cleanup_lifecycle = LSF_CLEANUP_TASK_RETURNED;\n'
        '    factory.device->cleanup_final_phase = LSF_CLEANUP_FINAL_RETURNED;\n'))
    outputs[name] = text.encode()
    name = 'net/factory-cleanup-clone.c'
    outputs[name] = request_lookup(outputs[name].decode()).encode()
    name = 'kernel/kthread.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_association.h>\n',
        '#include <net/lsf_stream_cleanup_association.h>\n' + include)
    text = replace(text, '#include "lsf-cleanup-association.c"\n',
        '#include "lsf-cleanup-association.c"\n#include "lsf-cleanup-close.c"\n')
    text = replace(text, '\t\t    && !lsf_factory_cleanup_final_pending()\n',
        '\t\t    && !lsf_factory_cleanup_final_pending()\n'
        '\t\t    && !lsf_factory_cleanup_request_pending()\n')
    text = replace(text, '\t\t       || lsf_factory_cleanup_final_pending()\n',
        '\t\t       || lsf_factory_cleanup_final_pending()\n'
        '\t\t       || lsf_factory_cleanup_request_pending()\n')
    text = replace(text, '\t\t\tif (lsf_factory_cleanup_final_pending()) {\n',
        '\t\t\tif (lsf_factory_cleanup_request_pending()) {\n'
        '\t\t\t\tspin_unlock(&kthread_create_lock);\n'
        '\t\t\t\tlsf_factory_cleanup_request_drain();\n'
        '\t\t\t\tspin_lock(&kthread_create_lock);\n'
        '\t\t\t\tcontinue;\n\t\t\t}\n'
        '\t\t\tif (lsf_factory_cleanup_final_pending()) {\n')
    outputs[name] = text.encode()
    name = 'kernel/lsf-cleanup-clone-args.c'
    outputs[name] = creator(outputs[name].decode()).encode()
    name = 'kernel/lsf-cleanup-association.c'
    outputs[name] = opener(outputs[name].decode()).encode()
    outputs['kernel/lsf-cleanup-close.c'] = (OWNED/'kernel-cleanup-close.c').read_bytes()
    outputs['net/factory-cleanup-close.c'] = (OWNED/'factory-cleanup-close.c').read_bytes()
    outputs['include/net/lsf_stream_cleanup_close.h'] = (OWNED/'cleanup-close-private.h').read_bytes()
    return outputs
