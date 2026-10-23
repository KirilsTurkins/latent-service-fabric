"""Actual taskstats/accounting writer exclusion; original exit hooks untouched.

Source composition only. No consumer selection or runtime qualification.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_provider_nonfinal as prior

OWNED = prior.OWNED
require = prior.require
replace = prior.replace
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_cleanup_exit_observer.json'
FIXTURE_SHA = 'e8e908206e2728d39312f39b8e0472428bae42712bd7456a80aea19a79594fe4'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 48 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-exit-observer-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-exit-observer-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 4 and len(value['sections']) == 8 and len(value['parentDerived']) == 2 and
        all(value[key] is False for key in ('actualObserverExecution', 'actualCompanionPut',
            'bootstrapQualified', 'fullConstructorClosure', 'productionInstallation')),
        'cleanup-exit-observer-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-exit-observer-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == expected['gitBlob'],
            'cleanup-exit-observer-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-exit-observer-definition-preimage')


def definition(name):
    return preimages()['sections'][name]['text']


def register_taskstats():
    text = replace(definition('register_taskstats'),
        'static int cmd_attr_register_cpumask(struct genl_info *info)\n',
        'static int lsf_cleanup_taskstats_register_original(struct genl_info *info)\n')
    return text + '''
static int cmd_attr_register_cpumask(struct genl_info *info)
{
#ifdef CONFIG_LSF_STREAM_FACTORY
    int error = lsf_cleanup_taskstats_prepare_begin();
    if (error)
        return error;
    error = lsf_cleanup_taskstats_register_original(info);
    lsf_cleanup_taskstats_prepare_end();
    return error;
#else
    return lsf_cleanup_taskstats_register_original(info);
#endif
}
'''


def enable_accounting():
    text = replace(definition('sys_acct'),
        'SYSCALL_DEFINE1(acct, const char __user *, name)\n',
        'static long lsf_cleanup_acct_original(const char __user *name)\n')
    return text + '''
SYSCALL_DEFINE1(acct, const char __user *, name)
{
#ifdef CONFIG_LSF_STREAM_FACTORY
    int tracked = name && task_active_pid_ns(current) == &init_pid_ns;
    long error;
    if (tracked) {
        error = lsf_cleanup_acct_prepare_begin();
        if (error)
            return error;
    }
    error = lsf_cleanup_acct_original(name);
    if (tracked)
        lsf_cleanup_acct_prepare_end();
    return error;
#else
    return lsf_cleanup_acct_original(name);
#endif
}
'''


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-exit-observer-parent-preimage')
    outputs = dict(outputs)
    for name, raw in inputs.items():
        if name not in outputs:
            outputs[name] = raw
    include = '#include <net/lsf_stream_cleanup_exit_observer.h>\n'
    name = 'kernel/taskstats.c'
    require(outputs[name] == inputs[name], 'cleanup-exit-observer-taskstats-original')
    text = replace(outputs[name].decode(),
        'static DEFINE_PER_CPU(struct listener_list, listener_array);\n',
        'static DEFINE_PER_CPU(struct listener_list, listener_array);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <linux/mutex.h>\n' + include +
        '#include "lsf-cleanup-observer-taskstats.c"\n#endif\n')
    outputs[name] = replace(text, definition('register_taskstats'), register_taskstats()).encode()
    name = 'kernel/acct.c'
    require(outputs[name] == inputs[name], 'cleanup-exit-observer-acct-original')
    text = replace(outputs[name].decode(), 'static DEFINE_MUTEX(acct_on_mutex);\n',
        'static DEFINE_MUTEX(acct_on_mutex);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + include +
        '#include "lsf-cleanup-observer-acct.c"\n#endif\n')
    outputs[name] = replace(text, definition('sys_acct'), enable_accounting()).encode()
    name = 'net/factory.c'
    outputs[name] = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_observer.h>\n',
        '#include <net/lsf_stream_cleanup_observer.h>\n' + include).encode()
    name = 'net/factory-cleanup-observer.c'
    text = replace(outputs[name].decode(),
        '#if defined(CONFIG_TRACEPOINTS) && defined(CONFIG_KPROBES) && defined(CONFIG_PROC_EVENTS)\n',
        '#if defined(CONFIG_TRACEPOINTS) && defined(CONFIG_KPROBES) && defined(CONFIG_PROC_EVENTS) && \\\n    defined(CONFIG_TASKSTATS) && defined(CONFIG_BSD_PROCESS_ACCT)\n', count=3)
    text = replace(text, '        lsf_cleanup_connector_seal_bytes();\n',
        '        lsf_cleanup_connector_seal_bytes() + lsf_cleanup_taskstats_seal_bytes() +\n'
        '        lsf_cleanup_acct_seal_bytes();\n')
    text = replace(text, '    factory.cleanup_observer_prebirth = 1u;\n',
        '    error = lsf_cleanup_taskstats_prebirth_seal();\n'
        '    if (error)\n        goto connector_rollback;\n'
        '    error = lsf_cleanup_acct_prebirth_seal();\n'
        '    if (error)\n        goto taskstats_rollback;\n'
        '    factory.cleanup_observer_prebirth = 1u;\n')
    text = replace(text, 'kprobe_rollback:\n',
        'taskstats_rollback:\n    lsf_cleanup_taskstats_prebirth_rollback();\n'
        'connector_rollback:\n    lsf_cleanup_connector_prebirth_rollback();\n'
        'kprobe_rollback:\n')
    # Only the ordinary prebank rollback path; error labels above are separate.
    text = replace(text, '    lsf_cleanup_connector_prebirth_rollback();\n    lsf_cleanup_kprobe_prebirth_rollback();\n',
        '    lsf_cleanup_acct_prebirth_rollback();\n    lsf_cleanup_taskstats_prebirth_rollback();\n'
        '    lsf_cleanup_connector_prebirth_rollback();\n    lsf_cleanup_kprobe_prebirth_rollback();\n')
    outputs[name] = text.encode()
    for name, raw in {
        'kernel/lsf-cleanup-observer-taskstats.c': 'taskstats-cleanup-observer.c',
        'kernel/lsf-cleanup-observer-acct.c': 'acct-cleanup-observer.c',
        'include/net/lsf_stream_cleanup_exit_observer.h': 'cleanup-exit-observer-private.h',
    }.items():
        outputs[name] = (OWNED/raw).read_bytes()
    return outputs
