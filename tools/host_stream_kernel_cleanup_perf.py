"""Explicit unsupported private-task perf inheritance/attachment profile.

Ordinary fork/observer paths retain their complete maintained bodies. Private
inheritance selectors run against actual pinned context groups under the real
mutex, with original no-inherit decisions and no event/PMU allocation.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_security as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_perf.json'
FIXTURE_SHA = '6d2ea96942a54c2045933f2952c4b314a8d17c9b2afd79c896c11e249dd883ea'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 64 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-perf-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-perf-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        value['archiveSha256'] == prior.preimages()['archiveSha256'] and
        len(value['source']) == 1 and len(value['sections']) == 7 and len(value['parentDerived']) == 2 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'actualPerfExecution', 'bootstrapQualified', 'fullConstructorClosure',
            'completeAllocationClosure', 'productionInstallation')),
        'cleanup-perf-source-origin')
    return value


def definition(name):
    return preimages()['sections'][name]['text']


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-perf-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-perf-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-perf-definition-preimage')


def private_perf():
    group = definition('inherit_task_group')
    body = group[group.index('\n{\n'):]
    begin = body.index('\tif (!event->attr.inherit ||\n')
    end = body.index('\n\tchild_ctx = child->perf_event_ctxp;\n')
    # The entire actual original selector is retained, including inherit_thread
    # and cleared signal-handler semantics. No copied NULL/boolean certificate.
    selector = body[begin:end]
    group = '''static int lsf_cleanup_perf_select_group(struct perf_event *event,
    struct perf_event_context *parent_ctx, u64 clone_flags, int *inherited_all)
{
    lockdep_assert_held(&parent_ctx->mutex);
''' + selector + '''
    /* Explicit unsupported operation for THIS private task profile only.
     * Reject before alloc_perf_context, inherit_group or any PMU callback. */
    *inherited_all = 0;
    return -EOPNOTSUPP;
}
'''
    context = replace(definition('perf_event_init_context'),
        'static int perf_event_init_context(struct task_struct *child, u64 clone_flags)\n',
        'static int lsf_cleanup_perf_init_context(struct task_struct *child, u64 clone_flags)\n')
    context = replace(context, '\tint ret = 0;\n',
        '\tint ret = 0;\n\tunsigned int saved_rotation = 0;\n\tbool rotation_changed = false;\n')
    context = replace(context, '\tif (likely(!parent->perf_event_ctxp))\n\t\treturn 0;\n\n', '')
    oldcomment = context[context.index('\t/*\n\t * No need to check if parent_ctx'):context.index('\t/*\n\t * Lock the parent list.')]
    context = replace(context, oldcomment,
        '\t/* The actual RCU/ctx-lock/refcount/pin operation above, rather\n'
        '\t * than an unlocked NULL observation, established this lifetime. */\n\n')
    context = replace(context,
        '\t\tret = inherit_task_group(event, parent, parent_ctx,\n'
        '\t\t\t\t\t child, clone_flags, &inherited_all);\n',
        '\t\tret = lsf_cleanup_perf_select_group(event, parent_ctx, clone_flags, &inherited_all);\n', 2)
    context = replace(context, '\tparent_ctx->rotate_disable = 1;\n',
        '\tsaved_rotation = parent_ctx->rotate_disable;\n'
        '\tparent_ctx->rotate_disable = 1;\n\trotation_changed = true;\n')
    context = replace(context, '\tparent_ctx->rotate_disable = 0;\n',
        '\tparent_ctx->rotate_disable = saved_rotation;\n\trotation_changed = false;\n')
    context = replace(context, 'out_unlock:\n\tmutex_unlock(&parent_ctx->mutex);\n',
        'out_unlock:\n\tif (rotation_changed) {\n'
        '\t\traw_spin_lock_irqsave(&parent_ctx->lock, flags);\n'
        '\t\tparent_ctx->rotate_disable = saved_rotation;\n'
        '\t\traw_spin_unlock_irqrestore(&parent_ctx->lock, flags);\n\t}\n'
        '\tmutex_unlock(&parent_ctx->mutex);\n')
    task = replace(definition('perf_event_init_task'),
        'int perf_event_init_task(struct task_struct *child, u64 clone_flags)\n',
        'int lsf_prepaid_cleanup_perf_event_init_task(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *child, u64 clone_flags)\n')
    task = replace(task, '\tint ret;\n', '\tint ret;\n\n'
        '\tif (clone_flags != LSF_CLEANUP_CLONE_FLAGS ||\n'
        '\t    !lsf_factory_cleanup_constructor_current(source, child))\n\t\treturn -EOPNOTSUPP;\n')
    task = replace(task, '\tret = perf_event_init_context(child, clone_flags);\n',
        '\tret = lsf_cleanup_perf_init_context(child, clone_flags);\n')
    return group + '\n' + context + '\n' + task


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-perf-parent-preimage')
    outputs = dict(outputs)
    include = '#include <net/lsf_stream_cleanup_perf.h>\n'
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_constructor.h>\n',
        '#include <net/lsf_stream_cleanup_constructor.h>\n' + include)
    outputs[name] = replace(text, '#include "factory-cleanup-constructor.c"\n',
        '#include "factory-cleanup-constructor.c"\n#include "factory-cleanup-perf.c"\n').encode()
    name = 'kernel/lsf-cleanup-constructor.c'
    text = replace(outputs[name].decode(), '\tretval = perf_event_init_task(p, clone_flags);\n',
        '#ifdef CONFIG_PERF_EVENTS\n'
        '\tretval = lsf_prepaid_cleanup_perf_event_init_task(source, p, clone_flags);\n'
        '#else\n\tretval = perf_event_init_task(p, clone_flags);\n#endif\n')
    outputs[name] = (include + text).encode()
    name = 'kernel/events/core.c'
    text = inputs[name].decode()
    original = definition('perf_event_alloc')
    updated = replace(original, '\tnode = (cpu >= 0) ? cpu_to_node(cpu) : -1;\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t/* Neither user nor kernel observers may introduce unowned\n'
        '\t * task-context/PMU storage for the private cleanup task. */\n'
        '\tif (task && lsf_factory_cleanup_perf_target(task))\n'
        '\t\treturn ERR_PTR(-EOPNOTSUPP);\n#endif\n'
        '\tnode = (cpu >= 0) ? cpu_to_node(cpu) : -1;\n')
    outputs[name] = (include + replace(text, original, updated) +
        '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-cleanup-perf.c"\n#endif\n').encode()
    outputs['kernel/events/lsf-cleanup-perf.c'] = private_perf().encode()
    outputs['include/net/lsf_stream_cleanup_perf.h'] = (OWNED / 'cleanup-perf-private.h').read_bytes()
    outputs['net/factory-cleanup-perf.c'] = (OWNED / 'factory-cleanup-perf.c').read_bytes()
    return outputs
