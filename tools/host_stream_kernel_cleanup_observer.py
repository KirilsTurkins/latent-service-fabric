"""Opt-in observer admission source; current full consumer stays disconnected.

This preserves actual notification calls and original callback/unregister
algorithms. No seal execution, observer/native closure or kernel enablement.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_close as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_observer.json'
FIXTURE_SHA = '56d203ba01c8ac9d33ac74e586d3fad5fb16fe70d3386129bf63f874882815cf'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 64 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-observer-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-observer-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 14 and len(value['sections']) == 21 and len(value['parentDerived']) == 1 and
        all(value[name] is False for name in ('sealExecuted', 'factoryCallsObserverEnter',
            'factoryCallsFullWorkerCreate', 'pendingConsumerCallsFullClone', 'taskCreated',
            'executorReady', 'actualIrqExecution', 'actualRcuExecution', 'physicalBackingReturned',
            'nativeLedgerQualified', 'observerClosure', 'bootstrapQualified',
            'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-observer-source-origin')
    return value


def definition(name):
    return preimages()['sections'][name]['text']


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-observer-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-observer-whole-source')
        if 'gitBlob' in expected:
            require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() ==
                expected['gitBlob'], 'cleanup-observer-exact-upstream-git-blob')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-observer-definition-preimage')
    config = inputs['selected.config'].decode()
    for name, selected in value['selected'].items():
        require(config.splitlines().count(name + '=' + selected) == 1,
            'cleanup-observer-actual-selected-configuration')


def trace_add():
    text = definition('trace_add')
    text = replace(text, '\tint ret;\n', '\tint ret;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tlockdep_assert_held(&tracepoints_mutex);\n'
        '\tif (lsf_cleanup_tracepoint_state.sealed)\n\t\treturn -EOPNOTSUPP;\n#endif\n')
    return replace(text, '\trelease_probes(old);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (!old && tp_funcs) {\n'
        '\t\tif (lsf_cleanup_tracepoint_state.heads == ~0u)\n'
        '\t\t\tlsf_cleanup_tracepoint_state.uncertain = 1u;\n'
        '\t\telse\n\t\t\tlsf_cleanup_tracepoint_state.heads++;\n\t}\n#endif\n'
        '\trelease_probes(old);\n')


def trace_remove():
    return replace(definition('trace_remove'), '\trelease_probes(old);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (old && !tp_funcs) {\n'
        '\t\tif (!lsf_cleanup_tracepoint_state.heads)\n'
        '\t\t\tlsf_cleanup_tracepoint_state.uncertain = 1u;\n'
        '\t\telse\n\t\t\tlsf_cleanup_tracepoint_state.heads--;\n\t}\n#endif\n'
        '\trelease_probes(old);\n')


def module_coming():
    text = definition('module_coming')
    return replace(text, '\tif (!mod->num_tracepoints)\n\t\treturn 0;\n',
        '\tif (!mod->num_tracepoints)\n\t\treturn 0;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_cleanup_tracepoint_module_check(mod))\n\t\treturn -EOPNOTSUPP;\n#endif\n')


def register_kprobe():
    text = definition('register_kprobe')
    return replace(text, '\tmutex_lock(&kprobe_mutex);\n',
        '\tmutex_lock(&kprobe_mutex);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_cleanup_kprobe_observers.sealed) {\n'
        '\t\tret = -EOPNOTSUPP;\n\t\tgoto out;\n\t}\n#endif\n')


def register_kretprobe():
    original = definition('register_kretprobe')
    actual = replace(original, 'int register_kretprobe(struct kretprobe *rp)\n',
        'static int lsf_cleanup_original_register_kretprobe(struct kretprobe *rp)\n')
    wrapper = '''int register_kretprobe(struct kretprobe *rp)
{
#ifdef CONFIG_LSF_STREAM_FACTORY
    int error, result;
    /* Full real preparation extent, before rethook/objpool allocation. */
    error = lsf_cleanup_kretprobe_prepare_begin();
    if (error)
        return error;
    result = lsf_cleanup_original_register_kretprobe(rp);
    lsf_cleanup_kretprobe_prepare_end();
    return result;
#else
    return lsf_cleanup_original_register_kretprobe(rp);
#endif
}
'''
    return actual + '\n' + wrapper


def unregister(name, argument_type, argument_name):
    original = definition(name)
    public = 'unregister_kretprobes' if name == 'unregister_kretprobes' else 'unregister_kprobes'
    signature = f'void {public}({argument_type} **{argument_name}, int num)\n'
    actual = replace(original, signature,
        f'static void lsf_cleanup_original_{public}({argument_type} **{argument_name}, int num)\n')
    wrapper = f'''void {public}({argument_type} **{argument_name}, int num)
{{
#ifdef CONFIG_LSF_STREAM_FACTORY
    int tracked = lsf_cleanup_kprobe_retire_begin();
#endif
    /* Whole original disarm, real RCU, selected rethook and arch final tail. */
    lsf_cleanup_original_{public}({argument_name}, num);
#ifdef CONFIG_LSF_STREAM_FACTORY
    if (tracked)
        lsf_cleanup_kprobe_retire_end();
#endif
}}
'''
    return actual + '\n' + wrapper


def connector_reject():
    text = replace(definition('connector_ack'),
        'static void cn_proc_ack(int err, int rcvd_seq, int rcvd_ack)\n',
        'static void lsf_cleanup_cn_proc_reject(int err, int rcvd_seq, int rcvd_ack,\n'
        '    struct netlink_skb_parms *nsp)\n')
    text = replace(text, '\tif (atomic_read(&proc_event_num_listeners) < 1)\n',
        '\tif (!nsp || !nsp->portid)\n')
    # Unlike ordinary broadcast ack, first-LISTEN refusal must reach its real
    # requestor even when there are zero listeners. Same original wire fields.
    return replace(text, '\tsend_msg(msg);\n',
        '\tcn_netlink_send_mult(msg, msg->len, nsp->portid, 0, GFP_KERNEL, NULL, NULL);\n')


def connector_control():
    text = definition('connector_ctl')
    text = replace(text, '\tif (nsp->sk) {\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tmutex_lock(&lsf_cleanup_connector_state.mutex);\n'
        '\tif (mc_op == PROC_CN_MCAST_LISTEN && lsf_cleanup_connector_state.sealed) {\n'
        '\t\tmutex_unlock(&lsf_cleanup_connector_state.mutex);\n'
        '\t\tlsf_cleanup_cn_proc_reject(EOPNOTSUPP, msg->seq, msg->ack, nsp);\n'
        '\t\treturn;\n\t}\n#endif\n'
        '\tif (nsp->sk) {\n')
    return replace(text, 'out:\n\tcn_proc_ack(err, msg->seq, msg->ack);\n',
        'out:\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tmutex_unlock(&lsf_cleanup_connector_state.mutex);\n#endif\n'
        '\tcn_proc_ack(err, msg->seq, msg->ack);\n')


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-observer-parent-preimage')
    outputs = dict(outputs)
    for name, raw in inputs.items():
        if name != 'selected.config' and name not in outputs:
            outputs[name] = raw
    include = '#include <net/lsf_stream_cleanup_observer.h>\n'
    name = 'kernel/tracepoint.c'
    require(outputs[name] == inputs[name], 'cleanup-observer-tracepoint-whole-original')
    text = replace(outputs[name].decode(), 'static DEFINE_MUTEX(tracepoints_mutex);\n',
        'static DEFINE_MUTEX(tracepoints_mutex);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + include +
        'static struct { unsigned int sealed, heads, uncertain; } lsf_cleanup_tracepoint_state;\n'
        '#ifdef CONFIG_MODULES\nstatic int lsf_cleanup_tracepoint_module_check(struct module *);\n'
        '#endif\n#endif\n')
    text = replace(text, definition('trace_add'), trace_add())
    text = replace(text, definition('trace_remove'), trace_remove())
    text = replace(text, definition('module_coming'), module_coming())
    outputs[name] = (text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-observer-tracepoint.c"\n#endif\n').encode()
    name = 'kernel/kprobes.c'
    require(outputs[name] == inputs[name], 'cleanup-observer-kprobe-whole-original')
    text = replace(outputs[name].decode(), 'static DEFINE_MUTEX(kprobe_mutex);\n',
        'static DEFINE_MUTEX(kprobe_mutex);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + include +
        'static struct { unsigned int sealed, preparing, retiring, uncertain; }\n'
        '    lsf_cleanup_kprobe_observers;\n'
        'static int lsf_cleanup_kretprobe_prepare_begin(void);\n'
        'static void lsf_cleanup_kretprobe_prepare_end(void);\n'
        'static int lsf_cleanup_kprobe_retire_begin(void);\n'
        'static void lsf_cleanup_kprobe_retire_end(void);\n#endif\n')
    for key, new in [('register_kprobe', register_kprobe()),
        ('register_kretprobe', register_kretprobe()),
        ('unregister_kprobes', unregister('unregister_kprobes', 'struct kprobe', 'kps')),
        ('unregister_kretprobes', unregister('unregister_kretprobes', 'struct kretprobe', 'rps'))]:
        text = replace(text, definition(key), new)
    outputs[name] = (text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-observer-kprobe.c"\n#endif\n').encode()
    name = 'drivers/connector/cn_proc.c'
    require(outputs[name] == inputs[name], 'cleanup-observer-connector-whole-original')
    text = replace(outputs[name].decode(), 'static atomic_t proc_event_num_listeners = ATOMIC_INIT(0);\n',
        'static atomic_t proc_event_num_listeners = ATOMIC_INIT(0);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <linux/mutex.h>\n' + include +
        'static struct { struct mutex mutex; unsigned int sealed; } lsf_cleanup_connector_state = {\n'
        '    .mutex = __MUTEX_INITIALIZER(lsf_cleanup_connector_state.mutex),\n};\n#endif\n')
    text = replace(text, definition('connector_ack'), definition('connector_ack') +
        '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + connector_reject() + '#endif\n')
    text = replace(text, definition('connector_ctl'), connector_control())
    outputs[name] = (text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-observer.c"\n#endif\n').encode()
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_close.h>\n',
        '#include <net/lsf_stream_cleanup_close.h>\n' + include)
    text = replace(text, '    unsigned int opened, reply_pending, inflight, uncertain;\n',
        '    unsigned int opened, reply_pending, inflight, uncertain, cleanup_observer_prebirth;\n')
    text = replace(text, '#include "factory-cleanup-close.c"\n',
        '#include "factory-cleanup-close.c"\n#include "factory-cleanup-observer.c"\n')
    old = ('    if (lsf_prepaid_cleanup_irq_bootstrap_bytes() >\n'
        '        LSF_BOOTSTRAP_CEILING - sizeof(factory) - sizeof(lsf_device_uevent_taps) -\n'
        '            LSF_BACKING_BYTES - 2u * sizeof(void *))\n')
    outputs[name] = replace(text, old, '    if (!lsf_cleanup_bootstrap_fits())\n').encode()
    for name, original in {
        'kernel/lsf-cleanup-observer-tracepoint.c':'tracepoint-cleanup-observer.c',
        'kernel/lsf-cleanup-observer-kprobe.c':'kprobe-cleanup-observer.c',
        'drivers/connector/lsf-cleanup-observer.c':'connector-cleanup-observer.c',
        'net/factory-cleanup-observer.c':'factory-cleanup-observer.c',
        'include/net/lsf_stream_cleanup_observer.h':'cleanup-observer-private.h',
    }.items():
        outputs[name] = (OWNED/original).read_bytes()
    return outputs
