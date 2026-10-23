"""Finite ordered-worker and real PWQ park/restore source, not selected birth.

Pool-IDR/Task creation, queue lifetime registration and final physical return
remain unqualified; constructor function guards remain closed.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_provider_operation as prior

OWNED = prior.OWNED
require = prior.require
replace = prior.replace
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_cleanup_provider_executor.json'
FIXTURE_SHA = '767f86ad857fdaa36c5b30ab61922bbdacb3f7422383ddbcfb61c6179dbeb59a'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 16 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-provider-executor-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-provider-executor-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 5 and len(value['sections']) == 4 and len(value['parentDerived']) == 5 and
        all(value[key] is False for key in ('providerCreated', 'taskCreated', 'queueMigrationExecuted',
            'queueLifetimeRegistered', 'physicalRetirementQualified', 'constructorFunctionGuardWidened',
            'bootstrapQualified', 'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-provider-executor-source-origin')
    return value


def definition(name):
    return preimages()['sections'][name]['text']


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-provider-executor-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-provider-executor-whole-source')
        if 'gitBlob' in expected:
            require(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == expected['gitBlob'],
                'cleanup-provider-executor-upstream-git-blob')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-provider-executor-definition-preimage')


def put_pwq():
    return replace(definition('put_pwq'), '\tlockdep_assert_held(&pwq->pool->lock);\n',
        '\tlockdep_assert_held(&pwq->pool->lock);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tlsf_prepaid_cleanup_provider_pwq_drop(pwq);\n#endif\n')


def get_unbound_pool():
    return replace(definition('get_unbound_pool'),
        '\thash_for_each_possible(unbound_pool_hash, pool, hash_node, hash) {\n',
        '\thash_for_each_possible(unbound_pool_hash, pool, hash_node, hash) {\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\t/* A paid private physical pool is not an ordinary cache match. */\n'
        '\t\tif (lsf_factory_cleanup_provider_pool_address(pool))\n\t\t\tcontinue;\n#endif\n')


def apply_prepare():
    return replace(definition('apply_prepare'), '\tlockdep_assert_held(&wq_pool_mutex);\n',
        '\tlockdep_assert_held(&wq_pool_mutex);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t/* This finite provider has no spare replacement pool/PWQ extent.\n'
        '\t * Real capacity failure precedes every temporary allocation;\n'
        '\t * original callers retain their transactional error rollback. */\n'
        '\tif (lsf_prepaid_cleanup_provider_attributes_bound(wq))\n'
        '\t\treturn ERR_PTR(-ENOMEM);\n#endif\n')


def worker_thread():
    text = replace(definition('worker_thread'), 'static int worker_thread(void *__worker)\n',
        'int lsf_prepaid_cleanup_provider_worker_thread(void *__worker)\n')
    text = replace(text, '\tstruct worker_pool *pool = worker->pool;\n',
        '\tstruct worker_pool *pool;\n\n'
        '\tif (lsf_provider_worker_entry(__worker))\n\t\treturn -EIO;\n'
        '\tpool = worker->pool;\n')
    return replace(text,
        '\tif (unlikely(!may_start_working(pool)) && manage_workers(worker))\n\t\tgoto recheck;\n',
        '\t/* A sole exclusive ordered PWQ has at most one active callback.\n'
        '\t * A spare cannot advance another callback from this same queue.\n'
        '\t * Never enter the original allocator/retry manager with cap one. */\n'
        '\tif (!lsf_provider_single_worker_locked(worker, pool)) {\n'
        '\t\tstruct lsf_cleanup_task_source source;\n'
        '\t\tif (lsf_factory_cleanup_provider_physical_current(&source) == 2)\n'
        '\t\t\tlsf_factory_cleanup_provider_hold(source);\n'
        '\t\tworker_enter_idle(worker);\n'
        '\t\tset_current_state(TASK_UNINTERRUPTIBLE);\n'
        '\t\traw_spin_unlock_irq(&pool->lock);\n'
        '\t\tschedule();\n\t\tgoto woke_up;\n\t}\n')


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-provider-executor-parent-preimage')
    outputs = dict(outputs)
    include = '#include <net/lsf_stream_cleanup_provider_executor.h>\n'
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_provider_operation.h>\n',
        '#include <net/lsf_stream_cleanup_provider_operation.h>\n'+include)
    outputs[name] = replace(text, '#include "factory-cleanup-provider-operation.c"\n',
        '#include "factory-cleanup-provider-operation.c"\n#include "factory-cleanup-provider-executor.c"\n').encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(),
        '    unsigned int cleanup_physical_role, cleanup_operation_active;\n',
        '    unsigned int cleanup_physical_role, cleanup_operation_active;\n'
        '    unsigned int cleanup_provider_storage_attempted;\n').encode()
    name = 'net/device-prepaid.h'
    text = replace(outputs[name].decode(), '    LSF_DEVICE_CLEANUP_PROVIDER_WORKER\n',
        '    LSF_DEVICE_CLEANUP_PROVIDER_WORKER,\n'
        '    LSF_DEVICE_CLEANUP_PROVIDER_PWQ,\n'
        '    LSF_DEVICE_CLEANUP_PROVIDER_ATTRS,\n'
        '    LSF_DEVICE_CLEANUP_PROVIDER_CONTROL,\n'
        '    LSF_DEVICE_CLEANUP_PROVIDER_CONTEXT\n')
    outputs[name] = replace(text, '        kind == LSF_DEVICE_CLEANUP_PROVIDER_WORKER;\n',
        '        kind == LSF_DEVICE_CLEANUP_PROVIDER_WORKER ||\n'
        '        kind == LSF_DEVICE_CLEANUP_PROVIDER_PWQ ||\n'
        '        kind == LSF_DEVICE_CLEANUP_PROVIDER_ATTRS ||\n'
        '        kind == LSF_DEVICE_CLEANUP_PROVIDER_CONTROL ||\n'
        '        kind == LSF_DEVICE_CLEANUP_PROVIDER_CONTEXT;\n').encode()
    name = 'kernel/workqueue.c'
    text = outputs[name].decode()
    for key, modified in [('put_pwq', put_pwq()), ('get_unbound_pool', get_unbound_pool()),
                          ('apply_prepare', apply_prepare())]:
        text = replace(text, definition(key), modified)
    text = replace(text, 'static int apply_workqueue_attrs_locked(',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-provider-executor.c"\n#endif\n\n'
        'static int apply_workqueue_attrs_locked(')
    outputs[name] = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'+include+'#endif\n'+text).encode()
    name = 'drivers/acpi/osl.c'
    text = replace(outputs[name].decode(), '#include "../../net/device-acpi-queue.c"\n',
        '#include "../../net/device-acpi-queue.c"\n'
        '#include "../../net/acpi-cleanup-provider-executor.c"\n')
    outputs[name] = text.encode()
    outputs['net/acpi-cleanup-provider-executor.c'] = (OWNED/'acpi-cleanup-provider-executor.c').read_bytes()
    outputs['include/net/lsf_stream_cleanup_provider_executor.h'] = (
        OWNED/'cleanup-provider-executor-private.h').read_bytes()
    outputs['net/factory-cleanup-provider-executor.c'] = (OWNED/'factory-cleanup-provider-executor.c').read_bytes()
    outputs['kernel/lsf-cleanup-provider-executor.c'] = (
        (OWNED/'workqueue-cleanup-provider-executor.c').read_bytes()+b'\n'+worker_thread().encode())
    return outputs
