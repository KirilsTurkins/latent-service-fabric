"""WIP grouped uevent consumer: actual tap/bank mutual admission, uninstalled.

The real cross-namespace multicast receiver path requires all-net tap admission
refusal during a private bank. Ordinary delivery is never bypassed. Remaining
environment/path/SKB/callback producer closure is explicitly NOT implemented by
this source prefix; no normal factory registration is enabled.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_sysfs as prior
from tools import host_stream_kernel_maintained as maintained

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_uevent.json'
NETLINK = 'net/netlink/af_netlink.c'
TAP_HEADER = 'include/linux/netlink.h'
EXTRAS = {TAP_HEADER, 'drivers/net/nlmon.c'}
DEFINITIONS = {'netlink_add_tap', '__netlink_remove_tap', 'netlink_remove_tap',
    'netlink_deliver_tap', 'do_one_broadcast', '__netlink_sendskb',
    'netlink_setsockopt', 'nlmon_open', 'nlmon_close', 'netlink_tap'}
GATES = prior.GATES + ('actualUeventDeliveryExecuted', 'completeUeventClosure',
    'actualTapAdmissionExecuted', 'completeTapFenceQualified')
replace = prior.replace
require = prior.require


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-uevent-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-uevent-maintained-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-uevent-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-uevent-original-definitions')
    require(all(value[name] is False for name in GATES), 'device-uevent-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-uevent-definition-occurrence')
    ending = row.get('terminator', '\n}\n')
    end = text.find(ending, starts[0])
    require(end >= 0, 'device-uevent-definition-end')
    raw = text[starts[0]:end + len(ending)]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'],
        'device-uevent-definition-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-uevent-whole-membership')
    maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def tap_header(raw):
    require(section(raw, 'netlink_tap') == raw, 'device-uevent-tap-header-preimage')
    return replace(raw, '\tstruct list_head list;\n', '\tstruct list_head list;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t/* Internal publication marker: never allocation authority. */\n'
        '\tunsigned int lsf_device_uevent_admitted;\n#endif\n')


def tap_add(raw):
    require(section(raw, 'netlink_add_tap') == raw, 'device-uevent-tap-add-preimage')
    return replace(raw, '\tmutex_lock(&nn->netlink_tap_lock);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n'
        '\t\tint error = lsf_factory_device_tap_admit(nt);\n'
        '\t\tif (error)\n\t\t\treturn error;\n\t}\n#endif\n'
        '\tmutex_lock(&nn->netlink_tap_lock);\n')


def tap_remove(raw):
    require(section(raw, 'netlink_remove_tap') == raw, 'device-uevent-tap-remove-preimage')
    return replace(raw, '\tsynchronize_net();\n', '\tsynchronize_net();\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (!ret)\n\t\tlsf_factory_device_tap_retired(nt);\n#endif\n')


def factory_gate(text):
    text = replace(text, '#include <linux/mutex.h>\n',
        '#include <linux/mutex.h>\n#include <linux/netlink.h>\n#include <linux/limits.h>\n')
    text = replace(text, '#include <net/lsf_stream_device_sysfs.h>\n',
        '#include <net/lsf_stream_device_sysfs.h>\n#include <net/lsf_stream_device_uevent.h>\n')
    text = replace(text, 'static DEFINE_SPINLOCK(pool_lock);\n',
        'static DEFINE_SPINLOCK(pool_lock);\n#include "factory-device-uevent-taps.c"\n')
    text = replace(text, 'sizeof(factory) + LSF_BACKING_BYTES < LSF_BOOTSTRAP_CEILING',
        'sizeof(factory) + sizeof(lsf_device_uevent_taps) + LSF_BACKING_BYTES < LSF_BOOTSTRAP_CEILING')
    text = replace(text, '    if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))\n        return -EPERM;\n',
        '    if (!ns_capable(&init_user_ns, CAP_SYS_ADMIN))\n        return -EPERM;\n'
        '    if (!current->nsproxy || current->nsproxy->net_ns != &init_net)\n'
        '        return -EOPNOTSUPP;\n')
    text = replace(text, '    /* Never alloc_pages_exact:',
        '    error = lsf_factory_device_uevent_bank_enter();\n'
        '    if (error)\n        goto out;\n'
        '    /* Never alloc_pages_exact:')
    text = replace(text, '    if (!factory.pages) {\n        error = -ENOMEM;\n',
        '    if (!factory.pages) {\n'
        '        lsf_factory_device_uevent_bank_allocation_failed();\n        error = -ENOMEM;\n')
    return text


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    text = inputs[NETLINK].decode()
    # Public delivery and every ordinary recipient are untouched. This source
    # boundary refuses a tap before publication instead of dropping its TX.
    anchor = '#include <net/netlink.h>\n'
    text = replace(text, anchor, anchor + '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_device_uevent.h>\n#endif\n')
    for name, operation in (('netlink_add_tap', tap_add), ('netlink_remove_tap', tap_remove)):
        raw = section(text, name)
        text = replace(text, raw, operation(raw))
    outputs[NETLINK] = text.encode()
    text = outputs[TAP_HEADER].decode()
    raw = section(text, 'netlink_tap')
    outputs[TAP_HEADER] = replace(text, raw, tap_header(raw)).encode()
    outputs['net/factory.c'] = factory_gate(outputs['net/factory.c'].decode()).encode()
    outputs['include/net/lsf_stream_device_uevent.h'] = (OWNED / 'device-uevent-private.h').read_bytes()
    outputs['net/factory-device-uevent-taps.c'] = (OWNED / 'factory-device-uevent-taps.c').read_bytes()
    return outputs
