"""Authenticated recipient lifetime and signal allocation source prefix.

The source is uninstalled. Full callback, mandatory SIGIO LSM/cache/audit,
instrumentation and receive-tail wiring are explicit remaining obligations.
This module does not certify them or borrow an application AVC owner.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_uevent_delivery as prior
from tools import host_stream_kernel_maintained as maintained

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_recipient.json'
EXTRAS = {'kernel/signal.c', 'kernel/rcu/tree.c', 'include/linux/rcupdate.h'}
DEFINITIONS = {'__sigqueue_alloc', '__sigqueue_free', '__send_signal_locked',
    'send_signal_locked', 'do_send_sig_info', '__netlink_sendskb',
    'netlink_overrun', 'netlink_rcv_wake', 'call_rcu', '__call_rcu_common', 'rcu_do_batch'}
GATES = prior.GATES + ('actualRecipientSignalExecuted', 'completeRecipientSignalClosure',
    'actualReceiveTailExecuted', 'completeReceiveTailClosure',
    'recipientSigioSecurityOwned', 'recipientInstrumentationOwned',
    'actualRecipientRcuExecuted', 'recipientSignalRcuPhysicallyQualified')
replace = prior.replace
require = prior.require


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-recipient-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-recipient-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-recipient-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-recipient-definitions')
    require(all(value[name] is False for name in GATES), 'device-recipient-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    prefix, ending = row['prefix'], row.get('terminator', '\n}\n')
    starts = [i for i in range(len(text)) if text.startswith(prefix, i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-recipient-definition-occurrence')
    start = starts[0]
    end = text.find(ending, start)
    require(end >= 0, 'device-recipient-definition-end')
    raw = text[start:end + len(ending)]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'],
        'device-recipient-definition-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-recipient-whole-membership')
    maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name, row in value['sections'].items():
        if name in DEFINITIONS:
            section(inputs[row['source']].decode(), name)


def private_signals(inputs):
    text = inputs['kernel/signal.c'].decode()
    pieces = []
    raw = section(text, '__sigqueue_alloc')
    raw = replace(raw, '__sigqueue_alloc(int sig,',
        'lsf_prepaid_device_sigqueue_alloc(struct lsf_device_registration_source source, int sig,')
    raw = replace(raw, '\tlong sigpending;\n',
        '\tlong sigpending;\n\n'
        '\t/* Only the real non-preallocated SIGIO sender chain enters here. */\n'
        '\tif (sigqueue_flags || !lsf_factory_device_recipient_current(source, NULL))\n'
        '\t\treturn NULL;\n\t(void)gfp_flags;\n')
    raw = replace(raw, 'kmem_cache_alloc(sigqueue_cachep, gfp_flags)',
        'lsf_factory_device_recipient_signal_allocate(source)')
    pieces.append(raw)
    raw = section(text, '__send_signal_locked')
    raw = replace(raw, '__send_signal_locked(int sig,',
        'lsf_prepaid_device_send_signal_locked_inner(struct lsf_device_registration_source source, int sig,')
    raw = replace(raw, '__sigqueue_alloc(sig, t, GFP_ATOMIC, override_rlimit, 0)',
        'lsf_prepaid_device_sigqueue_alloc(source, sig, t, GFP_ATOMIC, override_rlimit, 0)')
    pieces.append(raw)
    raw = section(text, 'send_signal_locked')
    raw = replace(raw, 'int send_signal_locked(int sig,',
        'static int lsf_prepaid_device_send_signal_locked(struct lsf_device_registration_source source, int sig,')
    raw = replace(raw, '__send_signal_locked(sig, info, t, type, force)',
        'lsf_prepaid_device_send_signal_locked_inner(source, sig, info, t, type, force)')
    pieces.append(raw)
    raw = section(text, 'do_send_sig_info')
    raw = replace(raw, 'int do_send_sig_info(int sig,',
        'int lsf_prepaid_device_do_send_sig_info(struct lsf_device_registration_source source, int sig,')
    raw = replace(raw, '\tint ret = -ESRCH;\n',
        '\tint ret = -ESRCH;\n\n'
        '\tif (!lsf_factory_device_recipient_current(source, NULL))\n'
        '\t\treturn -EOPNOTSUPP;\n')
    raw = replace(raw, 'send_signal_locked(sig, info, p, type)',
        'lsf_prepaid_device_send_signal_locked(source, sig, info, p, type)')
    pieces.append(raw)
    return ''.join(pieces)


def final_signal_return(raw):
    require(section(raw, '__sigqueue_free') == raw, 'device-recipient-signal-return-preimage')
    text = replace(raw, '\n{\n', '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_device_registration_source source;\n'
        '\tint private_signal = lsf_factory_device_recipient_signal_birth(q, &source);\n'
        '\tif (private_signal < 0)\n\t\treturn;\n'
        '\tif (private_signal && (q->flags & SIGQUEUE_PREALLOC)) {\n'
        '\t\tlsf_factory_device_uevent_poison();\n\t\treturn;\n\t}\n#endif\n')
    return replace(text, '\tkmem_cache_free(sigqueue_cachep, q);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (private_signal) {\n'
        '\t\t(void)lsf_factory_device_recipient_signal_return(q);\n\t\treturn;\n\t}\n#endif\n'
        '\tkmem_cache_free(sigqueue_cachep, q);\n')


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    text = outputs['net/device-prepaid.h'].decode()
    text = replace(text, '    LSF_DEVICE_UEVENT_HEAD\n',
        '    LSF_DEVICE_UEVENT_HEAD,\n    LSF_DEVICE_RECIPIENT_WORK,\n'
        '    LSF_DEVICE_RECIPIENT_SIGQUEUE\n')
    outputs['net/device-prepaid.h'] = replace(text,
        '        kind == LSF_DEVICE_UEVENT_HEAD;\n',
        '        kind == LSF_DEVICE_UEVENT_HEAD || kind == LSF_DEVICE_RECIPIENT_WORK ||\n'
        '        kind == LSF_DEVICE_RECIPIENT_SIGQUEUE;\n').encode()
    text = replace(outputs['net/factory.c'].decode(), '#include "device-uevent-allocator.h"\n',
        '#include "device-uevent-allocator.h"\n#include <linux/signal_types.h>\n'
        '#include <linux/rcupdate.h>\n'
        '#include <net/lsf_stream_device_recipient.h>\n#include "device-recipient-allocator.h"\n')
    outputs['net/factory.c'] = replace(text, '#include "factory-device-uevent.c"\n',
        '#include "factory-device-uevent.c"\n#include "factory-device-recipient.c"\n').encode()
    outputs['include/net/lsf_stream_device_recipient.h'] = (OWNED / 'device-recipient-private.h').read_bytes()
    outputs['net/device-recipient-allocator.h'] = (OWNED / 'device-recipient-allocator.h').read_bytes()
    outputs['net/factory-device-recipient.c'] = (OWNED / 'factory-device-recipient.c').read_bytes()

    name = 'kernel/signal.c'
    text = replace(outputs[name].decode(), '#include <asm/syscall.h>\t/* for syscall_get_* */\n',
        '#include <asm/syscall.h>\t/* for syscall_get_* */\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_device_recipient.h>\n#endif\n')
    raw = section(text, '__sigqueue_free')
    text = replace(text, raw, final_signal_return(raw))
    raw = section(text, 'do_send_sig_info')
    outputs[name] = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-device-recipient-signal.c"\n#endif\n').encode()
    outputs['kernel/lsf-device-recipient-signal.c'] = private_signals(inputs).encode()
    return outputs
