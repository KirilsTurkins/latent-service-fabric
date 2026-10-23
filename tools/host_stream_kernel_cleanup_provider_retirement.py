"""Actual typed WQ stop, original destructor and independent RCU returns.

Queue lifetime integration/consumer selection still remain closed.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_provider_initialize as prior
from tools import host_stream_kernel_cleanup_provider_executor as executor

OWNED = prior.OWNED
require = prior.require
replace = prior.replace
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_cleanup_provider_retirement.json'
FIXTURE_SHA = 'e47f8f51aca56df35fa58a0e6be6e2ea07773fd23382628ba4eacff44b3c9784'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 32 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-provider-retirement-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-provider-retirement-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 2 and len(value['sections']) == 7 and len(value['parentDerived']) == 7 and
        all(value[key] is False for key in ('taskCreated', 'queueLifetimeRegistered',
            'actualRcuExecution', 'physicalRetirementQualified', 'fullConstructorClosure', 'productionInstallation')),
        'cleanup-provider-retirement-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-provider-retirement-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == expected['gitBlob'],
            'cleanup-provider-retirement-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-provider-retirement-definition-preimage')


def definition(name):
    return preimages()['sections'][name]['text']


def reap_workers():
    text = replace(definition('reap_dying_workers'),
        '\tlist_for_each_entry_safe(worker, tmp, cull_list, entry) {\n',
        '\tlist_for_each_entry_safe(worker, tmp, cull_list, entry) {\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tstruct lsf_cleanup_task_source source;\n'
        '\t\tint owned = lsf_factory_cleanup_provider_part_origin(worker, LSF_PROVIDER_WORKER, &source);\n'
        '\t\tif (owned < 0 || (owned &&\n'
        '\t\t    !lsf_factory_cleanup_provider_part_queue(source, LSF_PROVIDER_WORKER, worker)))\n'
        '\t\t\treturn;\n#endif\n')
    return replace(text, '\t\tkfree(worker);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (owned)\n'
        '\t\t\t(void)lsf_factory_cleanup_provider_part_finish(source, LSF_PROVIDER_WORKER, worker);\n'
        '\t\telse\n#endif\n\t\t\tkfree(worker);\n')


def free_attrs():
    text = replace(definition('free_workqueue_attrs'), '\tif (attrs) {\n',
        '\tif (attrs) {\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tstruct lsf_cleanup_task_source source;\n'
        '\t\tint owned = lsf_factory_cleanup_provider_part_origin(attrs, LSF_PROVIDER_ATTRS, &source);\n'
        '\t\tif (owned < 0 || (owned &&\n'
        '\t\t    !lsf_factory_cleanup_provider_part_queue(source, LSF_PROVIDER_ATTRS, attrs)))\n'
        '\t\t\treturn;\n#endif\n')
    return replace(text, '\t\tkfree(attrs);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (owned)\n'
        '\t\t\t(void)lsf_factory_cleanup_provider_part_finish(source, LSF_PROVIDER_ATTRS, attrs);\n'
        '\t\telse\n#endif\n\t\t\tkfree(attrs);\n')


def free_pool():
    text = replace(definition('rcu_free_pool'),
        '\tstruct worker_pool *pool = container_of(rcu, struct worker_pool, rcu);\n',
        '\tstruct worker_pool *pool = container_of(rcu, struct worker_pool, rcu);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_cleanup_task_source source;\n'
        '\tint owned = lsf_factory_cleanup_provider_part_origin(pool, LSF_PROVIDER_POOL, &source);\n'
        '\tif (owned < 0)\n\t\treturn;\n#endif\n')
    return replace(text, '\tkfree(pool);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (owned)\n'
        '\t\t(void)lsf_factory_cleanup_provider_pool_destructed(source, pool);\n'
        '\telse\n#endif\n\t\tkfree(pool);\n')


def put_pool():
    return replace(definition('put_unbound_pool'), '\tLIST_HEAD(cull_list);\n',
        '\tLIST_HEAD(cull_list);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_cleanup_task_source source;\n'
        '\tint owned = lsf_factory_cleanup_provider_part_origin(pool, LSF_PROVIDER_POOL, &source);\n'
        '\tif (owned < 0 || (owned && pool->refcnt == 1 &&\n'
        '\t    !lsf_factory_cleanup_provider_part_queue(source, LSF_PROVIDER_POOL, pool)))\n'
        '\t\treturn;\n#endif\n')


def release_pwq():
    text = replace(definition('pwq_release_workfn'),
        '\tstruct workqueue_struct *wq = pwq->wq;\n\tstruct worker_pool *pool = pwq->pool;\n',
        '\tstruct workqueue_struct *wq;\n\tstruct worker_pool *pool;\n')
    text = replace(text, '\tbool is_last = false;\n',
        '\tbool is_last = false;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_cleanup_task_source source;\n'
        '\tint owned = lsf_factory_cleanup_provider_part_origin(pwq, LSF_PROVIDER_PWQ, &source);\n'
        '\tif (owned < 0 || (owned &&\n'
        '\t    !lsf_factory_cleanup_provider_part_queue(source, LSF_PROVIDER_PWQ, pwq)))\n'
        '\t\treturn;\n#endif\n\twq = pwq->wq;\n\tpool = pwq->pool;\n')
    return replace(text, '\tkfree_rcu(pwq, rcu);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (owned)\n\t\tcall_rcu(&pwq->rcu, lsf_provider_rcu_free_pwq);\n'
        '\telse\n#endif\n\t\tkfree_rcu(pwq, rcu);\n')


def put_pwq():
    return replace(executor.put_pwq(), '{\n',
        '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_cleanup_task_source source;\n'
        '\tint owned = lsf_factory_cleanup_provider_part_origin(pwq, LSF_PROVIDER_PWQ, &source);\n'
        '\tif (owned < 0 || (owned && pwq->refcnt == 1 &&\n'
        '\t    !lsf_factory_cleanup_provider_part_queue(source, LSF_PROVIDER_PWQ, pwq)))\n'
        '\t\treturn;\n#endif\n')


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-provider-retirement-parent-preimage')
    outputs = dict(outputs)
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    outputs[name] = replace(outputs[name].decode(), '#endif\n',
        'int lsf_factory_cleanup_provider_part_origin(const void *, unsigned int, struct lsf_cleanup_task_source *);\n'
        'int lsf_factory_cleanup_provider_part_publish(struct lsf_cleanup_task_source, unsigned int, const void *);\n'
        'int lsf_factory_cleanup_provider_part_queue(struct lsf_cleanup_task_source, unsigned int, const void *);\n'
        'int lsf_factory_cleanup_provider_part_finish(struct lsf_cleanup_task_source, unsigned int, const void *);\n'
        'int lsf_factory_cleanup_provider_pool_destructed(struct lsf_cleanup_task_source, const void *);\n'
        'int lsf_factory_cleanup_provider_parts_retired_locked(struct lsf_cleanup_task_source);\n'
        '#endif\n').encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(), '    unsigned int cleanup_provider_storage_attempted;\n',
        '    unsigned int cleanup_provider_storage_attempted;\n'
        '    unsigned int cleanup_provider_pool_destructed;\n').encode()
    name = 'net/factory.c'
    outputs[name] = replace(outputs[name].decode(), '#include "factory-cleanup-provider-initialize.c"\n',
        '#include "factory-cleanup-provider-initialize.c"\n#include "factory-cleanup-provider-retirement.c"\n').encode()
    name = 'net/factory-cleanup-provider-initialize.c'
    outputs[name] = replace(outputs[name].decode(), '        READ_ONCE(task->__state) == TASK_DEAD)\n',
        '        READ_ONCE(task->__state) == TASK_DEAD || !tryget_task_struct(task))\n').encode()
    name = 'net/factory-cleanup-close.c'
    text = replace(outputs[name].decode(),
        '    if (!factory.device || !factory.device->cleanup_worker_associated)\n        goto out;\n',
        '    if (!factory.device || !factory.device->cleanup_worker_associated)\n        goto out;\n'
        '    if (factory.device->cleanup_physical_role == LSF_CLEANUP_PHYSICAL_PROVIDER)\n'
        '        goto out; /* Original WQ stop_put owns the provider worker. */\n')
    outputs[name] = replace(text, '    /* The fixed original record cannot be reused.',
        '    if (!lsf_factory_cleanup_provider_parts_retired_locked(source))\n        return 0;\n'
        '    /* The fixed original record cannot be reused.').encode()
    name = 'kernel/workqueue.c'
    text = outputs[name].decode()
    text = replace(text, executor.put_pwq(), put_pwq())
    callback = '''#ifdef CONFIG_LSF_STREAM_FACTORY
static void lsf_provider_rcu_free_pwq(struct rcu_head *rcu)
{
    struct pool_workqueue *pwq = container_of(rcu, struct pool_workqueue, rcu);
    struct lsf_cleanup_task_source source;
    if (lsf_factory_cleanup_provider_part_origin(pwq, LSF_PROVIDER_PWQ, &source) != 1)
        return;
    /* Actual independent PWQ grace is complete. No PWQ field after here. */
    (void)lsf_factory_cleanup_provider_part_finish(source, LSF_PROVIDER_PWQ, pwq);
}
#endif
'''
    for key, modified in [('reap_dying_workers', reap_workers()), ('free_workqueue_attrs', free_attrs()),
                          ('rcu_free_pool', free_pool()), ('put_unbound_pool', put_pool()),
                          ('pwq_release_workfn', callback+release_pwq())]:
        text = replace(text, definition(key), modified)
    outputs[name] = text.encode()
    outputs['net/factory-cleanup-provider-retirement.c'] = (OWNED/'factory-cleanup-provider-retirement.c').read_bytes()
    return outputs
