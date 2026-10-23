"""Paid PWQ subview and actual closed provider pool/worker initialization.

The consumer remains unselected pending queue lifetime and physical return.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_provider_birth as prior

OWNED = prior.OWNED
require = prior.require
replace = prior.replace
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_cleanup_provider_initialize.json'
FIXTURE_SHA = 'fc9d89906f2ba263baf19b145db79339233339c05fcf38b3192ada88b2c1d41d'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 36 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-provider-initialize-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-provider-initialize-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 5 and len(value['sections']) == 7 and len(value['parentDerived']) == 7 and
        all(value[key] is False for key in ('taskCreated', 'poolCreated', 'queueLifetimeRegistered',
            'actualRcuExecution', 'fullConstructorClosure', 'productionInstallation')),
        'cleanup-provider-initialize-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-provider-initialize-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-provider-initialize-whole-source')
        if 'gitBlob' in expected:
            require(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == expected['gitBlob'],
                'cleanup-provider-initialize-upstream-blob')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-provider-initialize-definition-preimage')


def definition(name):
    return preimages()['sections'][name]['text']


def aligned_storage(text):
    # Original 64-byte allocator and its sole ancestry/record array remain
    # unchanged. Padding is charged in the SAME record before its birth.
    text = replace(text,
        '    unsigned long bytes[LSF_PROVIDER_PARTS], alignment[LSF_PROVIDER_PARTS], flags;\n',
        '    unsigned long bytes[LSF_PROVIDER_PARTS], charged[LSF_PROVIDER_PARTS], alignment[LSF_PROVIDER_PARTS], flags;\n')
    text = replace(text, '            alignment[i] > 64u || (alignment[i] & (alignment[i] - 1u)))\n',
        '            alignment[i] > PAGE_SIZE || (alignment[i] & (alignment[i] - 1u)))\n')
    text = replace(text, '        rounded = ((lsf_u64)bytes[i] + 63u) & ~(lsf_u64)63u;\n',
        '        if (bytes[i] > LSF_FACTORY_INFRA_BYTES - (alignment[i] - 1u))\n'
        '            return -ENOMEM;\n'
        '        charged[i] = bytes[i] + alignment[i] - 1u;\n'
        '        rounded = ((lsf_u64)charged[i] + 63u) & ~(lsf_u64)63u;\n')
    text = replace(text, 'source.owner, bytes[i],\n', 'source.owner, charged[i],\n')
    text = replace(text, '        storage->addresses[i] = (char *)page_address(factory.pages) + offsets[i];\n',
        '        storage->addresses[i] = (void *)ALIGN((unsigned long)page_address(factory.pages) +\n'
        '            offsets[i], alignment[i]);\n')
    text = replace(text, '    unsigned long bytes, alignment, base;\n',
        '    unsigned long bytes, alignment, base, address, padding;\n')
    text = replace(text,
        '            record->bytes < bytes || !alignment || record->offset % alignment || result)\n',
        '            !alignment || alignment > PAGE_SIZE || (alignment & (alignment - 1u)) || result)\n')
    text = replace(text, '        result = (void *)(base + record->offset);\n',
        '        address = ALIGN(base + record->offset, alignment);\n'
        '        padding = address - (base + record->offset);\n'
        '        if (padding >= alignment || padding > record->bytes || bytes > record->bytes - padding)\n'
        '            return NULL;\n'
        '        result = (void *)address;\n')
    return text


def pool_initialize():
    text = replace(definition('init_worker_pool'), 'static int init_worker_pool(struct worker_pool *pool)',
        'static int lsf_provider_init_worker_pool(struct lsf_cleanup_task_source source,\n'
        '    struct worker_pool *pool, struct workqueue_attrs *attrs)')
    text = replace(text, '{\n\traw_spin_lock_init(&pool->lock);',
        '{\n\tif (IS_ENABLED(CONFIG_CPUMASK_OFFSTACK) ||\n'
        '\t    !lsf_factory_cleanup_provider_birth_current(source, pool) ||\n'
        '\t    !lsf_factory_cleanup_provider_storage_current(source, LSF_PROVIDER_ATTRS, attrs))\n'
        '\t\treturn -EOPNOTSUPP;\n\traw_spin_lock_init(&pool->lock);')
    text = replace(text, '\tpool->attrs = alloc_workqueue_attrs();\n\tif (!pool->attrs)\n\t\treturn -ENOMEM;\n',
        '\t/* Exact selected inline cpumasks: original allocator defaults. */\n'
        '\tpool->attrs = attrs;\n'
        '\tcpumask_copy(attrs->cpumask, cpu_possible_mask);\n'
        '\tattrs->affn_scope = WQ_AFFN_DFL;\n')
    return text


def worker_allocate():
    text = replace(definition('alloc_worker'), 'static struct worker *alloc_worker(int node)',
        'static struct worker *lsf_provider_alloc_worker(struct lsf_cleanup_task_source source,\n'
        '    struct worker_pool *pool, struct worker *paid)')
    text = replace(text, '\tworker = kzalloc_node(sizeof(*worker), GFP_KERNEL, node);\n',
        '\tif (!lsf_factory_cleanup_provider_birth_current(source, pool) ||\n'
        '\t    !lsf_factory_cleanup_provider_storage_current(source, LSF_PROVIDER_WORKER, paid))\n'
        '\t\treturn NULL;\n\tworker = paid;\n')
    return text


def worker_create():
    text = replace(definition('create_worker'), 'static struct worker *create_worker(struct worker_pool *pool)',
        'static struct worker *lsf_provider_create_worker(struct lsf_cleanup_task_source source,\n'
        '    struct worker_pool *pool, struct worker *paid)')
    text = replace(text, '\t/* ID is needed to determine kthread name */\n',
        '\tif (!lsf_factory_cleanup_provider_birth_current(source, pool) ||\n'
        '\t    !lsf_factory_cleanup_provider_storage_current(source, LSF_PROVIDER_WORKER, paid))\n'
        '\t\treturn NULL;\n'
        '\tlockdep_assert_held(&wq_pool_mutex);\n'
        '\t/* This actual newly initialized, exclusive IDA is empty. Only ID0\n'
        '\t * is supported: maintained ida_alloc_range stores an inline XA\n'
        '\t * value at empty index0, without bitmap or xarray-node growth. */\n'
        '\tif (!xa_empty(&pool->worker_ida.xa) || pool->nr_workers ||\n'
        '\t    !list_empty(&pool->workers) || (pool->flags & POOL_BH))\n'
        '\t\treturn NULL;\n\t/* ID is needed to determine kthread name */\n')
    text = replace(text, 'id = ida_alloc(&pool->worker_ida, GFP_KERNEL);',
        'id = ida_alloc_range(&pool->worker_ida, 0, 0, GFP_KERNEL);')
    text = replace(text, 'worker = alloc_worker(pool->node);',
        'worker = lsf_provider_alloc_worker(source, pool, paid);')
    text = replace(text,
        '\t\tworker->task = kthread_create_on_node(worker_thread, worker,\n'
        '\t\t\t\t\t\t      pool->node, "%s", id_buf);',
        '\t\tworker->task = lsf_prepaid_cleanup_provider_task_create(source, worker);')
    text = replace(text, '\n\t\tset_user_nice(worker->task, pool->attrs->nice);',
        '\n\t\tif (!lsf_factory_cleanup_provider_task_associate(source, worker, worker->task)) {\n'
        '\t\t\tlsf_factory_cleanup_provider_hold(source);\n'
        '\t\t\treturn NULL; /* Unknown association is retained, never followed. */\n'
        '\t\t}\n\t\tset_user_nice(worker->task, pool->attrs->nice);')
    text = replace(text, '\tkfree(worker);\n',
        '\t/* Paid worker/Task/request physical return belongs to the typed\n'
        '\t * retirement route. No bank address reaches ordinary SLUB. */\n'
        '\tlsf_factory_cleanup_provider_hold(source);\n')
    return text


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-provider-initialize-parent-preimage')
    outputs = dict(outputs)
    name = 'net/factory-cleanup-provider-executor.c'
    outputs[name] = aligned_storage(outputs[name].decode()).encode()
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    outputs[name] = replace(outputs[name].decode(), '#endif\n',
        'int lsf_factory_cleanup_thread_pair(struct lsf_cleanup_task_source, int (*)(void *), const void *);\n'
        'int lsf_factory_cleanup_provider_open_request(struct lsf_cleanup_task_source, const void *, void **);\n'
        'int lsf_factory_cleanup_provider_task_associate(struct lsf_cleanup_task_source,\n'
        '    const void *, struct task_struct *);\n'
        'struct task_struct *lsf_prepaid_cleanup_provider_task_create(struct lsf_cleanup_task_source, void *);\n'
        '#endif\n').encode()
    name = 'net/factory.c'
    outputs[name] = replace(outputs[name].decode(), '#include "factory-cleanup-provider-birth.c"\n',
        '#include "factory-cleanup-provider-birth.c"\n#include "factory-cleanup-provider-initialize.c"\n').encode()
    name = 'kernel/kthread.c'
    text = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_cleanup_provider_executor.h>\n#endif\n'+outputs[name].decode()
    outputs[name] = replace(text, '#include "lsf-cleanup-association.c"\n',
        '#include "lsf-cleanup-association.c"\n#include "lsf-cleanup-provider-initialize.c"\n').encode()
    name = 'kernel/lsf-cleanup-clone-args.c'
    outputs[name] = replace(outputs[name].decode(),
        '        owned->create.threadfn == kthread_worker_fn && owned->create.data == &owned->worker &&\n',
        '        lsf_factory_cleanup_thread_pair(actual, owned->create.threadfn, owned->create.data) &&\n').encode()
    name = 'kernel/lsf-cleanup-entry.c'
    outputs[name] = replace(outputs[name].decode(),
        '    if (_create != &owned->create || owned->create.threadfn != kthread_worker_fn ||\n'
        '        owned->create.data != &owned->worker || owned->create.full_name != owned->name ||\n',
        '    if (_create != &owned->create ||\n'
        '        !lsf_factory_cleanup_thread_pair(source, owned->create.threadfn, owned->create.data) ||\n'
        '        owned->create.full_name != owned->name ||\n').encode()
    name = 'kernel/lsf-cleanup-provider-executor.c'
    # The finite branch has no original manager retry target. Ordinary full
    # worker_thread is not modified; remove only this private unused label.
    text = replace(outputs[name].decode(), '\nrecheck:\n', '\n')
    outputs[name] = (text+'\n'+pool_initialize()+'\n'+worker_allocate()+'\n'+worker_create()).encode()
    outputs['net/factory-cleanup-provider-initialize.c'] = (OWNED/'factory-cleanup-provider-initialize.c').read_bytes()
    outputs['kernel/lsf-cleanup-provider-initialize.c'] = (OWNED/'kthread-cleanup-provider-initialize.c').read_bytes()
    return outputs
