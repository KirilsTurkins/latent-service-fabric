"""Separate physical provider Task ownership from real current WORK authority.

Unselected source; the finite executor and restoration lifetime remain separate.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_worker_operations as prior

OWNED = prior.OWNED
require = prior.require
replace = prior.replace
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_provider_operation.json'
FIXTURE_SHA = '121e8dde033b4834fea2f930982e62ad794ea9e40222081a27f656df7fb26172'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 16 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-provider-operation-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-provider-operation-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 3 and len(value['sections']) == 1 and len(value['parentDerived']) == 5 and
        all(value[key] is False for key in ('physicalRoleBound', 'dispatchExecuted', 'providerCreated',
            'factoryCallsFullWorkerCreate', 'pendingConsumerCallsFullClone', 'bootstrapQualified',
            'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-provider-operation-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-provider-operation-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-provider-operation-whole-source')
        if 'gitBlob' in expected:
            require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() ==
                expected['gitBlob'], 'cleanup-provider-operation-upstream-git-blob')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-provider-operation-definition-preimage')
    config = inputs['selected.config'].decode().splitlines()
    require(config.count('CONFIG_NR_CPUS=64') == 1 and
        config.count('CONFIG_PAGE_SHIFT=12') == 1 and
        not any(line.startswith('CONFIG_PREEMPT_RT=') for line in config),
        'cleanup-provider-operation-actual-selected-profile')


def process_one_work():
    original = preimages()['sections']['process_one_work']['text']
    return replace(original, '\tworker->current_func(work);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tlsf_factory_cleanup_provider_dispatch_begin();\n#endif\n'
        '\tworker->current_func(work);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tlsf_factory_cleanup_provider_dispatch_end();\n#endif\n')


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-provider-operation-parent-preimage')
    outputs = dict(outputs)
    include = '#include <net/lsf_stream_cleanup_provider_operation.h>\n'
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_worker_operations.h>\n',
        '#include <net/lsf_stream_cleanup_worker_operations.h>\n' + include)
    outputs[name] = replace(text, '#include "factory-device-firmware.c"\n',
        '#include "factory-device-firmware.c"\n#include "factory-cleanup-provider-operation.c"\n').encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(),
        '    unsigned int cleanup_child_attempted, cleanup_final_phase, cleanup_vm_prepared;\n',
        '    unsigned int cleanup_child_attempted, cleanup_final_phase, cleanup_vm_prepared;\n'
        '    unsigned int cleanup_physical_role, cleanup_operation_active;\n'
        '    struct lsf_prepaid_ticket cleanup_provider_worker, cleanup_provider_pool;\n'
        '    struct work_struct *cleanup_operation_work;\n'
        '    work_func_t cleanup_operation_function;\n').encode()
    name = 'net/device-prepaid.h'
    text = replace(outputs[name].decode(), '    LSF_DEVICE_ROOT_AUDIT_HEAD\n',
        '    LSF_DEVICE_ROOT_AUDIT_HEAD,\n'
        '    LSF_DEVICE_CLEANUP_PROVIDER_POOL = 0x150,\n'
        '    LSF_DEVICE_CLEANUP_PROVIDER_WORKER\n')
    outputs[name] = replace(text, '        kind == LSF_DEVICE_ROOT_AUDIT_HEAD;\n',
        '        kind == LSF_DEVICE_ROOT_AUDIT_HEAD ||\n'
        '        kind == LSF_DEVICE_CLEANUP_PROVIDER_POOL ||\n'
        '        kind == LSF_DEVICE_CLEANUP_PROVIDER_WORKER;\n').encode()
    name = 'net/factory-cleanup-worker-operations.c'
    outputs[name] = ('/* SPDX-License-Identifier: GPL-2.0-only */\n'
        '/* Physical provider ownership alone grants no Root operation. */\n'
        'int lsf_factory_cleanup_worker_operation_current(void)\n{\n'
        '    return lsf_factory_cleanup_provider_operation_current();\n}\n').encode()
    name = 'kernel/workqueue.c'
    require(name not in outputs or outputs[name] == inputs[name],
        'cleanup-provider-operation-workqueue-whole-original')
    text = inputs[name].decode()
    original = preimages()['sections']['process_one_work']['text']
    text = replace(text, original, process_one_work())
    text = replace(text, 'static void process_one_work(',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-provider-operation.c"\n#endif\n\n'
        'static void process_one_work(')
    outputs[name] = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n' + include + '#endif\n' + text).encode()
    outputs['kernel/workqueue_internal.h'] = inputs['kernel/workqueue_internal.h']
    outputs['include/net/lsf_stream_cleanup_provider_operation.h'] = (
        OWNED/'cleanup-provider-operation-private.h').read_bytes()
    outputs['kernel/lsf-cleanup-provider-operation.c'] = (
        OWNED/'workqueue-cleanup-provider-operation.c').read_bytes()
    outputs['net/factory-cleanup-provider-operation.c'] = (
        OWNED/'factory-cleanup-provider-operation.c').read_bytes()
    return outputs
