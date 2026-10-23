"""Original real worker association/wake tail, disconnected full consumer.

No fake create completion, worker Ready witness, second wake_up_new_task,
alternate queue, unowned worker allocation or qualified executor follows.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_cgroup as prior
from tools.host_stream_kernel_device_security import function

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_association.json'
FIXTURE_SHA = 'b8d982ad908a159ee1ab5bc6375bd9f9e942709292ab2e077b39c34d8a0d4256'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 16 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-association-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-association-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 1 and len(value['sections']) == 1 and len(value['parentDerived']) == 4 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'factoryCallsFullWorkerCreate', 'pendingConsumerCallsFullClone',
            'observerClosure', 'bootstrapQualified', 'fullConstructorClosure',
            'completeAllocationClosure', 'productionInstallation')),
        'cleanup-association-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-association-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-association-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-association-definition-preimage')


def full_worker(prefix):
    original = function(prefix, 'int lsf_prepaid_cleanup_worker_create(void)')
    text = replace(original, 'int lsf_prepaid_cleanup_worker_create(void)',
        'int lsf_prepaid_cleanup_worker_create_full(void)')
    begin = text.index('    /* The current constructor can ONLY return an error before stack birth.\n')
    text = replace(text, text[begin:],
        '    /* The REAL running entry completed this result. Bind only its\n'
        '     * actual born Task to the already-charged original worker. The\n'
        '     * full pending consumer remains disconnected until all active\n'
        '     * observer/bootstrap gates are closed; no executor is claimed. */\n'
        '    if (!lsf_factory_cleanup_worker_associate(source, owned, &owned->worker, task))\n'
        '        return -EIO;\n'
        '    wake_up_process(task);\n    return 0;\n}\n')
    return text


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-association-parent-preimage')
    outputs = dict(outputs)
    include = '#include <net/lsf_stream_cleanup_association.h>\n'
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_io.h>\n',
        '#include <net/lsf_stream_cleanup_io.h>\n' + include)
    outputs[name] = replace(text, '#include "factory-cleanup-io.c"\n',
        '#include "factory-cleanup-io.c"\n#include "factory-cleanup-association.c"\n').encode()
    name = 'net/factory-device.c'
    text = outputs[name].decode()
    outputs[name] = replace(text, '    unsigned int cleanup_entry_started;\n',
        '    unsigned int cleanup_entry_started, cleanup_worker_associated;\n').encode()
    name = 'kernel/kthread.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_clone.h>\n',
        '#include <net/lsf_stream_cleanup_clone.h>\n' + include)
    outputs[name] = replace(text, '#include "lsf-cleanup-clone-args.c"\n',
        '#include "lsf-cleanup-clone-args.c"\n#include "lsf-cleanup-association.c"\n').encode()
    outputs['kernel/lsf-cleanup-association.c'] = ((OWNED/'kernel-cleanup-association.c').read_bytes() +
        b'\n' + full_worker(outputs['kernel/lsf-cleanup-worker.c'].decode()).encode())
    outputs['net/factory-cleanup-association.c'] = (OWNED/'factory-cleanup-association.c').read_bytes()
    outputs['include/net/lsf_stream_cleanup_association.h'] = (OWNED/'cleanup-association-private.h').read_bytes()
    return outputs
