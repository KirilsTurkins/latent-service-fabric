"""Whole maintained kernel-clone/thread caller tails, still disconnected.

No observer, subsystem or bootstrap gate is waived by retaining these tails.
The original pending consumer continues to refuse until coherent closure.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_audit as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_clone.json'
FIXTURE_SHA = 'dd1f2bcb8da6042bc3cd2aa48704b0ad686f71c22c361e7bf1122582a02f445d'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 32 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-clone-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-clone-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        value['archiveSha256'] == prior.preimages()['archiveSha256'] and
        len(value['source']) == 2 and len(value['sections']) == 3 and len(value['parentDerived']) == 4 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'pendingConsumerCallsFullClone', 'observerClosure', 'bootstrapQualified',
            'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-clone-source-origin')
    return value


def definition(name):
    return preimages()['sections'][name]['text']


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-clone-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-clone-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-clone-definition-preimage')


def private_clone():
    clone = replace(definition('kernel_clone'), 'pid_t kernel_clone(struct kernel_clone_args *args)\n',
        'pid_t lsf_prepaid_cleanup_kernel_clone(struct lsf_cleanup_task_source source,\n'
        '    struct kernel_clone_args *args)\n')
    clone = replace(clone, '\tu64 clone_flags = args->flags;\n',
        '\tu64 clone_flags = args ? args->flags : 0;\n')
    clone = replace(clone, '\tpid_t nr;\n', '\tpid_t nr;\n\n'
        '\tif (!lsf_prepaid_cleanup_clone_args_current(source, args))\n\t\treturn -EOPNOTSUPP;\n')
    clone = replace(clone, '\tp = copy_process(NULL, trace, NUMA_NO_NODE, args);\n',
        '\tp = lsf_prepaid_cleanup_copy_process(source, args, NUMA_NO_NODE);\n')
    thread = replace(definition('kernel_thread'),
        'pid_t kernel_thread(int (*fn)(void *), void *arg, const char *name,\n'
        '\t\t    unsigned long flags)\n',
        'pid_t lsf_prepaid_cleanup_kernel_thread(struct lsf_cleanup_task_source source,\n'
        '    int (*fn)(void *), void *arg, const char *name, unsigned long flags)\n')
    thread = replace(thread, '\treturn kernel_clone(&args);\n',
        '\treturn lsf_prepaid_cleanup_kernel_clone(source, &args);\n')
    return clone + '\n' + thread


def private_creator():
    text = replace(definition('create_kthread'),
        'static void create_kthread(struct kthread_create_info *create)\n',
        'static void __maybe_unused lsf_cleanup_create_kthread_full(struct lsf_cleanup_request *owned)\n')
    text = replace(text, '\tint pid;\n',
        '\tint pid;\n\tstruct kthread_create_info *create;\n'
        '\tstruct lsf_cleanup_task_source source;\n\n'
        '\t/* Actual request birth/current/source BEFORE create or name reads. */\n'
        '\tif (!lsf_factory_cleanup_constructor_request(owned, sizeof(*owned), &source)) {\n'
        '\t\tlsf_factory_cleanup_stack_poison((struct lsf_cleanup_task_source){0});\n'
        '\t\treturn;\n\t}\n\tcreate = &owned->create;\n')
    text = replace(text, '\tpid = kernel_thread(kthread, create, create->full_name,\n',
        '\tpid = lsf_prepaid_cleanup_kernel_thread(source, lsf_prepaid_cleanup_kthread_entry,\n'
        '\t\t\t    create, create->full_name,\n')
    text = replace(text, '\t\tkfree(create->full_name);\n',
        '\t\t/* Name and create are embedded in the original held bank. */\n')
    text = replace(text, '\t\t\tkfree(create);\n',
        '\t\t\t/* Interrupted opener: retain the real original request. */\n')
    return text


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-clone-parent-preimage')
    outputs = dict(outputs)
    include = '#include <net/lsf_stream_cleanup_clone.h>\n'
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_perf.h>\n',
        '#include <net/lsf_stream_cleanup_perf.h>\n' + include)
    outputs[name] = replace(text, '#include "factory-cleanup-perf.c"\n',
        '#include "factory-cleanup-perf.c"\n#include "factory-cleanup-clone.c"\n').encode()
    name = 'kernel/kthread.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_constructor.h>\n',
        '#include <net/lsf_stream_cleanup_constructor.h>\n' + include)
    outputs[name] = replace(text, '#include "lsf-cleanup-constructor-irq.c"\n',
        '#include "lsf-cleanup-constructor-irq.c"\n#include "lsf-cleanup-clone-args.c"\n').encode()
    name = 'kernel/lsf-cleanup-constructor.c'
    text = outputs[name].decode()
    anchor = '\t\treturn ERR_PTR(-EOPNOTSUPP);\n'
    require(text.count(anchor) == 1, 'cleanup-clone-only-pre-birth-profile-guard')
    outputs[name] = (include + replace(text, anchor, anchor +
        '\tif (!lsf_prepaid_cleanup_clone_args_current(source, args))\n'
        '\t\treturn ERR_PTR(-EOPNOTSUPP);\n')).encode()
    name = 'kernel/fork.c'
    outputs[name] = replace(outputs[name].decode(), '#include "lsf-cleanup-constructor.c"\n',
        '#include "lsf-cleanup-constructor.c"\n#include "lsf-cleanup-clone.c"\n').encode()
    outputs['kernel/lsf-cleanup-clone.c'] = private_clone().encode()
    outputs['kernel/lsf-cleanup-clone-args.c'] = ((OWNED / 'kernel-cleanup-clone.c').read_bytes() +
        b'\n' + private_creator().encode())
    outputs['net/factory-cleanup-clone.c'] = (OWNED / 'factory-cleanup-clone.c').read_bytes()
    outputs['include/net/lsf_stream_cleanup_clone.h'] = (OWNED / 'cleanup-clone-private.h').read_bytes()
    return outputs
