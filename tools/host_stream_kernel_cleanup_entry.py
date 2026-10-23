"""Private maintained kthread entry without bank-request allocator escape.

Full copy_process ownership and IRQ/bootstrap qualification remain absent. This
layer does not call the entry, publish a task, or enable a running worker.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_lifecycle as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_entry.json'
FIXTURE_SHA = '116b255bef5c80b120a2b3823accf904961d8f5d999d80e0e912467aa936e9aa'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 16 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-entry-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-entry-source.v1' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        set(value['source']) == {'kernel/kthread.c'} and len(value['sections']) == 2 and
        len(value['parentDerived']) == 4 and value['entrySourceImplemented'] is True and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'fullConstructorClosure', 'productionInstallation')), 'cleanup-entry-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-entry-whole-membership')
    for name, row in value['source'].items():
        require(type(inputs[name]) is bytes and len(inputs[name]) == row['bytes'] and
            hashlib.sha256(inputs[name]).hexdigest() == row['sha256'], 'cleanup-entry-whole-source')
    for row in value['sections'].values():
        raw = row['text'].encode()
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'] and
            inputs[row['source']].decode().count(row['text']) == 1, 'cleanup-entry-definition-preimage')


def private_entry():
    original = preimages()['sections']['kthread']['text']
    text = replace(original, 'static int kthread(void *_create)\n',
        'int lsf_prepaid_cleanup_kthread_entry(void *_create)\n')
    text = replace(text, '\t/* Copy data: it\'s on kthread\'s stack */\n',
        '\t/* The fixed request remains in its original charged bank. */\n')
    text = replace(text, '\tstruct kthread_create_info *create = _create;\n',
        '\tstruct kthread_create_info *create;\n')
    text = replace(text, '\tint (*threadfn)(void *data) = create->threadfn;\n',
        '\tint (*threadfn)(void *data);\n')
    text = replace(text, '\tvoid *data = create->data;\n', '\tvoid *data;\n')
    text = replace(text, '\tint ret;\n\n\tself = to_kthread(current);\n', '''\tint ret;
    struct lsf_cleanup_request *owned;
    struct lsf_cleanup_task_source source;
    void *request_address, *metadata_address;

    /* Actual current task, all generations and child addresses are validated
     * BEFORE reading _create, worker_private or the request's callback data. */
    if (!lsf_factory_cleanup_entry_current(&request_address, &metadata_address)) {
        lsf_factory_cleanup_stack_poison((struct lsf_cleanup_task_source){0});
        /* Cannot safely read an unrecognised metadata result/completion. The
         * whole original bank/ref stays quarantined; no ready result exists. */
        do_exit(0);
    }
    owned = request_address;
    source = owned->source;
    self = metadata_address;
    if (_create != &owned->create || owned->create.threadfn != kthread_worker_fn ||
        owned->create.data != &owned->worker || owned->create.full_name != owned->name ||
        current->vfork_done != &self->exited) {
        lsf_factory_cleanup_stack_poison(source);
        done = xchg(&owned->create.done, NULL);
        if (done) {
            owned->create.result = ERR_PTR(-EIO);
            complete(done); /* LAST request/completion access. */
        }
        kthread_exit(-EIO);
    }
    create = &owned->create;
    threadfn = create->threadfn;
    data = create->data;
\tself = to_kthread(current);
''')
    # The actual interrupted-opener branch still exits the actual Linux task.
    # Neither bank request nor embedded name can be given to the normal heap.
    text = replace(text, '\t\tkfree(create->full_name);\n\t\tkfree(create);\n',
        '\t\t/* Original request/name remain charged through physical task\n'
        '\t\t * and stack return. No completion owner remains to notify. */\n')
    return text


def transform(outputs, inputs):
    authenticate(inputs)
    for name, row in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == row['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == row['sha256'],
            'cleanup-entry-parent-preimage')
    outputs = dict(outputs)
    original = preimages()['sections']['kthread']['text']
    require(outputs['kernel/kthread.c'].decode().count(original) == 1,
        'cleanup-entry-original-entry-preserved')
    name = 'include/net/lsf_stream_cleanup_lifecycle.h'
    outputs[name] = replace(outputs[name].decode(), 'void lsf_prepaid_cleanup_retire_one(void);\n',
        'void lsf_prepaid_cleanup_retire_one(void);\n'
        'int lsf_prepaid_cleanup_kthread_entry(void *);\n'
        'int lsf_factory_cleanup_entry_current(void **, void **);\n').encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(), '    struct task_struct *cleanup_retire_task;\n',
        '    struct task_struct *cleanup_retire_task;\n'
        '    unsigned int cleanup_entry_started;\n').encode()
    name = 'net/factory.c'
    outputs[name] = replace(outputs[name].decode(), '#include "factory-cleanup-lifecycle.c"\n',
        '#include "factory-cleanup-lifecycle.c"\n#include "factory-cleanup-entry.c"\n').encode()
    name = 'kernel/kthread.c'
    outputs[name] = replace(outputs[name].decode(), '#include "lsf-cleanup-lifecycle.c"\n',
        '#include "lsf-cleanup-lifecycle.c"\n#include "lsf-cleanup-entry.c"\n').encode()
    outputs['net/factory-cleanup-entry.c'] = (OWNED / 'factory-cleanup-entry.c').read_bytes()
    outputs['kernel/lsf-cleanup-entry.c'] = private_entry().encode()
    return outputs


def derive(inputs):
    # The only entry whole source is already authenticated in the lifecycle
    # union. Preserve its complete membership and add no fallback source tree.
    return transform(prior.derive(inputs), {'kernel/kthread.c': inputs['kernel/kthread.c']})
