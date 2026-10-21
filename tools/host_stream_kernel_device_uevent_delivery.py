"""Authenticated, uninstalled uevent continuation source consumers.

This derivation preserves the separate tap/bank prefix and original ordinary
callbacks. It is source preparation, not evidence of an installed provider,
complete recipient callback/allocation closure or actual Linux execution.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_uevent as prior
from tools import host_stream_kernel_maintained as maintained

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_uevent_delivery.json'
EXTRAS = {'lib/kobject_uevent.c', 'drivers/pci/pci-driver.c', 'net/core/filter.c', 'drivers/of/device.c'}
DEFINITIONS = {'kobject_synth_uevent', 'alloc_uevent_skb', 'uevent_net_broadcast_untagged',
    'uevent_net_broadcast_tagged', 'kobject_uevent_net_broadcast', 'kobject_uevent_env',
    'get_kobj_path_length', 'fill_kobj_path', 'kobject_get_path', 'kobject_rename', 'kobject_move',
    'dev_uevent_filter', 'dev_uevent_name', 'dev_driver_uevent', 'dev_uevent', 'uevent_show',
    'device_namespace', 'device_uevent_ops', 'pci_uevent', 'pci_bus_type', 'pci_dev_type',
    'sk_filter_trim_cap', 'security_sock_rcv_skb', 'selinux_socket_sock_rcv_skb',
    'skb_clone', 'skb_kfree_head', 'kfree_skbmem', 'pskb_expand_head', 'skb_copy',
    '__pskb_copy_fclone', 'skb_copy_expand', 'skb_release_data', 'of_device_uevent',
    'netlink_trim', 'netlink_broadcast_deliver', 'netlink_skb_set_owner_r',
    'netlink_skb_destructor', 'netlink_recvmsg'}
GATES = prior.GATES + ('actualEnvPathCallbackExecuted', 'actualReceiverSecurityExecuted',
    'actualUeventSkbRetirementExecuted', 'completeUeventCallbackClosure')

replace = prior.replace
require = prior.require


def core_tail_borrow(outputs):
    """Extend only the real callback extent, never a future queued task."""
    text = outputs['net/factory-device.c'].decode()
    text = replace(text, '    struct task_struct *constructor_task;\n',
        '    struct task_struct *constructor_task, *core_tail_task;\n')
    outputs['net/factory-device.c'] = text.encode()
    text = outputs['net/factory-device-core.c'].decode()
    text = replace(text,
        '        owned->returned || owned->core_tail_active || owned->core_tail_complete)\n',
        '        owned->returned || owned->core_tail_active || owned->core_tail_complete ||\n'
        '        factory.device->core_tail_task)\n')
    text = replace(text, '    owned->core_tail_active = 1;\n',
        '    owned->core_tail_active = 1;\n'
        '    factory.device->core_tail_task = current;\n')
    anchor = ('    spin_lock_irqsave(&pool_lock, flags);\n'
        '    if (lsf_factory_device_core_parent(kobject,\n')
    text = replace(text, anchor,
        '    spin_lock_irqsave(&pool_lock, flags);\n'
        '    /* Revoke the EXACT current callback borrow before every later\n'
        '     * validation/error/queue path. The original bank retains this\n'
        '     * state even if a poisoned record can no longer be looked up.\n'
        '     * A foreign task never clears the real callback task borrow. */\n'
        '    if (!factory.device || factory.device->core_tail_task != current)\n'
        '        goto poison;\n'
        '    factory.device->core_tail_task = NULL;\n'
        '    if (lsf_factory_device_core_parent(kobject,\n')
    outputs['net/factory-device-core.c'] = text.encode()
    return outputs


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-uevent-delivery-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-uevent-delivery-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-uevent-delivery-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-uevent-delivery-definitions')
    require(set(value['priorProjectedSections']) == {'skb_clone', 'skb_kfree_head',
        'kfree_skbmem', 'pskb_expand_head', 'skb_copy', '__pskb_copy_fclone',
        'skb_copy_expand', 'skb_release_data'}, 'device-uevent-delivery-projection-membership')
    require(all(value[name] is False for name in GATES), 'device-uevent-delivery-uninstalled')
    return value


def section(text, name, projected=False):
    row = fixture()['priorProjectedSections' if projected else 'sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    ending = row.get('terminator', '\n}\n')
    expected = 2 if projected and name in {'__pskb_copy_fclone', 'skb_copy_expand'} else 1
    require(len(starts) == expected, 'device-uevent-delivery-definition-occurrence')
    candidates = []
    for start in starts:
        end = text.find(ending, start)
        require(end >= 0, 'device-uevent-delivery-definition-end')
        candidates.append(text[start:end + len(ending)])
    if projected:
        require(row['prefixOccurrences'] == expected and candidates.count(row['text']) == 1,
            'device-uevent-delivery-projected-occurrence')
        require([raw for raw in candidates if raw != row['text']] ==
            [fixture()['sections'][name]['text']] * (expected - 1),
            'device-uevent-delivery-original-config-off-definition')
        raw = row['text']
    else:
        raw = candidates[0]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'],
        'device-uevent-delivery-definition-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-uevent-delivery-whole-membership')
    maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def private_env(raw):
    require(section(raw, 'kobject_uevent_env') == raw, 'device-uevent-env-preimage')
    text = replace(raw, 'int kobject_uevent_env(struct kobject *kobj, enum kobject_action action,',
        'static int lsf_prepaid_device_uevent_env(\n'
        '\t\tstruct lsf_device_registration_source source, struct kobject *kobj, enum kobject_action action,')
    text = replace(text, '\tconst char *action_string = kobject_actions[action];\n',
        '\tconst char *action_string;\n')
    text = replace(text, '\tint retval = 0;\n', '\tint retval = 0;\n\tunsigned int depth = 0;\n'
        '\tstruct lsf_device_registration_source actual;\n\n'
        '\tif ((unsigned int)action >= ARRAY_SIZE(kobject_actions) ||\n'
        '\t    lsf_factory_device_uevent_kobject(kobj, &actual) != 1 ||\n'
        '\t    source.kind != actual.kind || source.address != actual.address ||\n'
        '\t    source.slot != actual.slot || source.generation != actual.generation ||\n'
        '\t    source.pci_slot != actual.pci_slot || source.pci_generation != actual.pci_generation ||\n'
        '\t    lsf_factory_device_uevent_current(source) != 1)\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '\taction_string = kobject_actions[action];\n')
    # Keep the original REMOVE mark; preflight precedes every actual callback.
    text = replace(text, '\tpr_debug("kobject: \'%s\' (%p): %s\\n",',
        '\tif (IS_ENABLED(CONFIG_UEVENT_HELPER) || envp_ext ||\n'
        '\t    !lsf_prepaid_device_uevent_device(kobj))\n'
        '\t\treturn -EOPNOTSUPP;\n\n'
        '\tpr_debug("kobject: \'%s\' (%p): %s\\n",')
    text = replace(text, '\twhile (!top_kobj->kset && top_kobj->parent)\n'
        '\t\ttop_kobj = top_kobj->parent;\n',
        '\twhile (!top_kobj->kset && top_kobj->parent) {\n'
        '\t\tif (++depth > LSF_DEVICE_UEVENT_MAX_ANCESTORS)\n'
        '\t\t\treturn -EOPNOTSUPP;\n'
        '\t\ttop_kobj = top_kobj->parent;\n\t}\n')
    text = replace(text, '\t/* skip the event, if the filter returns zero. */\n',
        '\tif (!lsf_prepaid_device_uevent_ops_known(uevent_ops))\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '\t/* skip the event, if the filter returns zero. */\n')
    text = replace(text, 'env = kzalloc(sizeof(struct kobj_uevent_env), GFP_KERNEL);',
        'env = lsf_factory_device_uevent_allocate(source, sizeof(*env), LSF_DEVICE_UEVENT_KIND_ENV);')
    text = replace(text, 'devpath = kobject_get_path(kobj, GFP_KERNEL);',
        'devpath = lsf_prepaid_device_uevent_path(source, kobj);')
    text = replace(text, '\tkfree(devpath);\n\tkfree(env);\n',
        '\tif (devpath && lsf_factory_device_uevent_return(devpath, LSF_DEVICE_UEVENT_KIND_PATH) != 1)\n'
        '\t\tretval = -EOPNOTSUPP;\n'
        '\tif (env && lsf_factory_device_uevent_return(env, LSF_DEVICE_UEVENT_KIND_ENV) != 1)\n'
        '\t\tretval = -EOPNOTSUPP;\n')
    return text


def private_alloc_skb(raw):
    require(section(raw, 'alloc_uevent_skb') == raw, 'device-uevent-skb-birth-preimage')
    text = replace(raw, 'static struct sk_buff *alloc_uevent_skb(struct kobj_uevent_env *env,',
        'static struct sk_buff *lsf_prepaid_device_alloc_uevent_skb(\n'
        '\t\tstruct lsf_device_registration_source source, struct kobj_uevent_env *env,')
    text = replace(text, '\tsize_t len;\n',
        '\tsize_t len, action_length, path_length;\n'
        '\tunsigned long path_bytes;\n'
        '\tstruct lsf_device_registration_source path_source;\n\n'
        '\tif (source.kind != LSF_DEVICE_UEVENT_KIND_ENV || source.address != env ||\n'
        '\t    lsf_factory_device_uevent_current(source) != 1 ||\n'
        '\t    env->buflen < 0 || (unsigned int)env->buflen > sizeof(env->buf) ||\n'
        '\t    lsf_factory_device_uevent_path_bytes(devpath, &path_source, &path_bytes) != 1 ||\n'
        '\t    path_source.pci_slot != source.pci_slot ||\n'
        '\t    path_source.pci_generation != source.pci_generation)\n'
        '\t\treturn NULL;\n'
        '\taction_length = strnlen(action_string, 16);\n'
        '\tpath_length = strnlen(devpath, path_bytes);\n'
        '\tif (!action_length || action_length == 16 || path_length == path_bytes ||\n'
        '\t    action_length + path_length + 2 > LSF_DEVICE_UEVENT_MAX_HEAD_BYTES - env->buflen)\n'
        '\t\treturn NULL;\n')
    text = replace(text, 'len = strlen(action_string) + strlen(devpath) + 2;',
        'len = action_length + path_length + 2;')
    text = replace(text, 'skb = alloc_skb(len + env->buflen, GFP_KERNEL);',
        'skb = lsf_prepaid_device_uevent_skb_new(source, len + env->buflen);')
    return text


def wrapper(raw, prelude):
    declaration, body = raw.split('\n{\n', 1)
    return declaration + '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + prelude + (
        '\t{\n#endif\n') + body[:-2] + '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t}\n#endif\n}\n'


def private_copy(raw, name):
    require(name in {'skb_copy', '__pskb_copy_fclone', 'skb_copy_expand'} and
        section(raw, name) == raw, 'device-uevent-copy-preimage')
    names = {'skb_copy': 'copy', '__pskb_copy_fclone': 'copy_partial',
        'skb_copy_expand': 'copy_expand'}
    declaration, body = raw.split('\n{\n', 1)
    declaration = replace(declaration, 'struct sk_buff *' + name + '(',
        'static struct sk_buff *lsf_prepaid_device_uevent_' + names[name] + '(\n'
        '\t\tstruct lsf_device_registration_source source, ')
    guard = '\tif (!lsf_prepaid_device_uevent_linear(skb, source)'
    if name == '__pskb_copy_fclone':
        guard += (' || fclone || headroom < 0 ||\n'
            '\t    (unsigned int)headroom > LSF_DEVICE_UEVENT_MAX_HEAD_BYTES - skb->len')
        body = replace(body, 'struct sk_buff *n = __alloc_skb(size, gfp_mask, flags, NUMA_NO_NODE);',
            'struct sk_buff *n = lsf_prepaid_device_uevent_skb_new(source, size);\n'
            '\t(void)flags;')
    elif name == 'skb_copy_expand':
        guard += (' || newheadroom < 0 || newtailroom < 0 ||\n'
            '\t    (unsigned int)newheadroom > LSF_DEVICE_UEVENT_MAX_HEAD_BYTES - skb->len ||\n'
            '\t    (unsigned int)newtailroom > LSF_DEVICE_UEVENT_MAX_HEAD_BYTES - skb->len - newheadroom')
        body = replace(body, 'n = __alloc_skb(newheadroom + skb->len + newtailroom,\n'
            '\t\t\tgfp_mask, skb_alloc_rx_flag(skb),\n\t\t\tNUMA_NO_NODE);',
            'n = lsf_prepaid_device_uevent_skb_new(source, newheadroom + skb->len + newtailroom);')
    else:
        body = replace(body, 'n = __alloc_skb(size, gfp_mask,\n'
            '\t\t\tskb_alloc_rx_flag(skb), NUMA_NO_NODE);',
            'n = lsf_prepaid_device_uevent_skb_new(source, size);')
    return declaration + '\n{\n' + guard + ')\n\t\treturn NULL;\n\t{\n' + body[:-2] + '\t}\n}\n'


def skb_dispatch(raw, name):
    row = fixture()['priorProjectedSections'][name]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'],
        'device-uevent-skb-dispatch-preimage')
    if name == 'skb_kfree_head':
        return wrapper(raw, '\tif (lsf_factory_device_uevent_return(head, LSF_DEVICE_UEVENT_KIND_HEAD))\n'
            '\t\treturn;\n')
    if name == 'kfree_skbmem':
        return wrapper(raw, '\tif (lsf_factory_device_uevent_return(skb, LSF_DEVICE_UEVENT_KIND_SKB))\n'
            '\t\treturn;\n')
    prelude = ('\tstruct lsf_device_registration_source source;\n'
        '\tint uevent_owned = lsf_factory_device_uevent_birth(skb, LSF_DEVICE_UEVENT_KIND_SKB, &source);\n')
    if name == 'skb_release_data':
        return wrapper(raw, prelude + '\tif (uevent_owned < 0 ||\n'
            '\t    (uevent_owned && !lsf_prepaid_device_uevent_linear(skb, source)))\n'
            '\t\treturn;\n')
    functions = {
        'skb_clone': ('clone', 'skb, source', 'NULL'),
        'pskb_expand_head': ('expand', 'skb, nhead, ntail, source', '-EOPNOTSUPP'),
        'skb_copy': ('copy', 'source, skb, gfp_mask', 'NULL'),
        '__pskb_copy_fclone': ('copy_partial', 'source, skb, headroom, gfp_mask, fclone', 'NULL'),
        'skb_copy_expand': ('copy_expand', 'source, skb, newheadroom, newtailroom, gfp_mask', 'NULL'),
    }
    require(name in functions, 'device-uevent-skb-dispatch-operation')
    function, arguments, failure = functions[name]
    return wrapper(raw, prelude + '\tif (uevent_owned)\n'
        '\t\treturn uevent_owned < 0 ? ' + failure + ' : lsf_prepaid_device_uevent_' +
        function + '(' + arguments + ');\n')


def filter_guard(raw):
    require(section(raw, 'sk_filter_trim_cap') == raw, 'device-uevent-filter-preimage')
    text = replace(raw, '\tif (filter) {\n',
        '\tif (filter) {\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (uevent_owned) {\n\t\t\trcu_read_unlock();\n'
        '\t\t\treturn -EOPNOTSUPP;\n\t\t}\n#endif\n')
    # BPF configuration is checked before its real cgroup callback; a socket
    # filter is checked inside the ORIGINAL RCU extent, avoiding a stale test.
    return wrapper(text, '\tstruct lsf_device_registration_source source;\n'
        '\tint uevent_owned = lsf_factory_device_uevent_birth(skb, LSF_DEVICE_UEVENT_KIND_SKB, &source);\n'
        '\tif (uevent_owned < 0 || (uevent_owned &&\n'
        '\t    (IS_ENABLED(CONFIG_BPF_SYSCALL) || sk->sk_family != PF_NETLINK)))\n'
        '\t\treturn -EOPNOTSUPP;\n')


def security_guard(raw):
    require(section(raw, 'security_sock_rcv_skb') == raw, 'device-uevent-security-preimage')
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tstruct lsm_static_call *scall;\n'
        '\tint uevent_owned = lsf_factory_device_uevent_birth(skb, LSF_DEVICE_UEVENT_KIND_SKB, &source);\n'
        '\tif (uevent_owned < 0 || (uevent_owned && sk->sk_family != PF_NETLINK))\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '\tif (uevent_owned) {\n\t\tlsm_for_each_hook(scall, socket_sock_rcv_skb) {\n'
        '#ifdef CONFIG_SECURITY_SELINUX\n'
        '\t\t\tif (!lsf_prepaid_device_selinux_socket_hook(scall->hl->hook.socket_sock_rcv_skb))\n'
        '\t\t\t\treturn -EOPNOTSUPP;\n'
        '#else\n\t\t\treturn -EOPNOTSUPP;\n#endif\n\t\t}\n\t}\n')


def env_dispatch(raw):
    require(section(raw, 'kobject_uevent_env') == raw, 'device-uevent-main-dispatch-preimage')
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tint uevent_owned = lsf_factory_device_uevent_kobject(kobj, &source);\n'
        '\tif (uevent_owned < 0)\n\t\treturn -EOPNOTSUPP;\n'
        '\tif (uevent_owned)\n'
        '\t\treturn lsf_prepaid_device_uevent_env(source, kobj, action, envp_ext);\n')


def alloc_skb_dispatch(raw):
    require(section(raw, 'alloc_uevent_skb') == raw, 'device-uevent-birth-dispatch-preimage')
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tint uevent_owned = lsf_factory_device_uevent_birth(env, LSF_DEVICE_UEVENT_KIND_ENV, &source);\n'
        '\tif (uevent_owned)\n'
        '\t\treturn uevent_owned < 0 ? NULL : lsf_prepaid_device_alloc_uevent_skb(source, env, action_string, devpath);\n')


def unsupported_kobject_operation(raw, name, expression):
    require(name in {'kobject_synth_uevent', 'kobject_rename', 'kobject_move', 'uevent_show'} and
        section(raw, name) == raw, 'device-uevent-extra-operation-preimage')
    # Classification alone is sufficient to refuse an unsupported operation.
    # It does not borrow the constructor task or mutate a valid private device.
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tif (lsf_factory_device_uevent_kobject(' + expression + ', &source))\n'
        '\t\treturn -EOPNOTSUPP;\n')


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    core_tail_borrow(outputs)
    include = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_device_uevent_consumer.h>\n#endif\n')
    text = outputs['net/device-prepaid.h'].decode()
    text = replace(text, '    LSF_DEVICE_IDR_NODE\n',
        '    LSF_DEVICE_IDR_NODE,\n    LSF_DEVICE_UEVENT_ENV,\n'
        '    LSF_DEVICE_UEVENT_PATH,\n    LSF_DEVICE_UEVENT_SKB,\n    LSF_DEVICE_UEVENT_HEAD\n')
    outputs['net/device-prepaid.h'] = replace(text, 'kind == LSF_DEVICE_IDR_NODE;\n',
        'kind == LSF_DEVICE_IDR_NODE || kind == LSF_DEVICE_UEVENT_ENV ||\n'
        '        kind == LSF_DEVICE_UEVENT_PATH || kind == LSF_DEVICE_UEVENT_SKB ||\n'
        '        kind == LSF_DEVICE_UEVENT_HEAD;\n').encode()
    text = replace(outputs['net/factory.c'].decode(), '#include "device-prepaid.h"\n',
        '#include "device-prepaid.h"\n#include <linux/kobject.h>\n#include <linux/skbuff.h>\n'
        '#include <net/lsf_stream_device_uevent_consumer.h>\n'
        '#include "device-uevent-allocator.h"\n')
    outputs['net/factory.c'] = replace(text, '#include "factory-device-sysfs.c"\n',
        '#include "factory-device-sysfs.c"\n#include "factory-device-uevent.c"\n').encode()
    outputs['include/net/lsf_stream_device_uevent_consumer.h'] = (OWNED / 'device-uevent-consumer-private.h').read_bytes()
    outputs['net/device-uevent-allocator.h'] = (OWNED / 'device-uevent-allocator.h').read_bytes()
    outputs['net/factory-device-uevent.c'] = (OWNED / 'factory-device-uevent.c').read_bytes()

    filename = 'lib/kobject_uevent.c'
    text = replace(outputs[filename].decode(), '#include <net/net_namespace.h>\n',
        '#include <net/net_namespace.h>\n#include <linux/limits.h>\n' + include +
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-device-uevent-kobject.c"\n#endif\n')
    raw = section(text, 'alloc_uevent_skb')
    text = replace(text, raw, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' +
        private_alloc_skb(raw) + '#endif\n' + alloc_skb_dispatch(raw))
    raw = section(text, 'kobject_uevent_env')
    text = replace(text, raw, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' +
        private_env(raw) + '#endif\n' + env_dispatch(raw))
    raw = section(text, 'kobject_synth_uevent')
    outputs[filename] = replace(text, raw,
        unsupported_kobject_operation(raw, 'kobject_synth_uevent', 'kobj')).encode()
    outputs['lib/lsf-device-uevent-kobject.c'] = (OWNED / 'device-uevent-kobject.c').read_bytes()

    filename = 'lib/kobject.c'
    text = replace(outputs[filename].decode(), '#include <net/lsf_stream_device_sysfs.h>\n',
        '#include <net/lsf_stream_device_sysfs.h>\n' + include)
    for name in ('kobject_rename', 'kobject_move'):
        raw = section(text, name)
        text = replace(text, raw, unsupported_kobject_operation(raw, name, 'kobj'))
    outputs[filename] = text.encode()
    filename = 'drivers/base/core.c'
    text = replace(outputs[filename].decode(), '#include <net/lsf_stream_device_sysfs.h>\n',
        '#include <net/lsf_stream_device_sysfs.h>\n' + include)
    raw = section(text, 'device_uevent_ops')
    text = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-device-uevent-callbacks.c"\n#endif\n')
    raw = section(text, 'uevent_show')
    outputs[filename] = replace(text, raw,
        unsupported_kobject_operation(raw, 'uevent_show', '&dev->kobj')).encode()
    outputs['drivers/base/lsf-device-uevent-callbacks.c'] = (OWNED / 'device-uevent-callbacks.c').read_bytes()

    filename = 'drivers/pci/pci-driver.c'
    text = replace(outputs[filename].decode(), '#include "pci.h"\n', '#include "pci.h"\n' + include)
    raw = section(text, 'pci_uevent')
    outputs[filename] = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'int lsf_prepaid_device_uevent_pci_bus_known(const struct bus_type *candidate)\n'
        '{\n\treturn candidate == &pci_bus_type && candidate->uevent == pci_uevent;\n}\n#endif\n').encode()
    filename = 'drivers/pci/probe.c'
    text = replace(outputs[filename].decode(), '#include <net/lsf_stream_device_core.h>\n',
        '#include <net/lsf_stream_device_core.h>\n' + include)
    raw = section(text, 'pci_dev_type')
    outputs[filename] = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'int lsf_prepaid_device_uevent_pci_type_known(const struct device_type *candidate)\n'
        '{\n\treturn candidate == &pci_dev_type;\n}\n#endif\n').encode()

    filename = 'net/core/skbuff.c'
    text = replace(outputs[filename].decode(), '#include "../factory-private.h"\n',
        '#include "../factory-private.h"\n#include <net/lsf_stream_device_uevent_consumer.h>\n'
        'static bool lsf_prepaid_device_uevent_linear(const struct sk_buff *,\n'
        '\tstruct lsf_device_registration_source);\n')
    text = replace(text, '#include "../packet-skb-private.c"\n',
        '#include "../packet-skb-private.c"\n#include "../device-uevent-skb.c"\n')
    text = replace(text, '#include "../packet-copy-private.c"\n',
        '#include "../packet-copy-private.c"\n#include "../device-uevent-copy.c"\n')
    for name in fixture()['priorProjectedSections']:
        raw = section(text, name, projected=True)
        text = replace(text, raw, skb_dispatch(raw, name))
    outputs[filename] = text.encode()
    outputs['net/device-uevent-skb.c'] = (OWNED / 'device-uevent-skb.c').read_bytes()
    outputs['net/device-uevent-copy.c'] = ''.join(private_copy(
        section(inputs['net/core/skbuff.c'].decode(), name), name)
        for name in ('skb_copy', '__pskb_copy_fclone', 'skb_copy_expand')).encode()

    filename = 'net/core/filter.c'
    text = replace(outputs[filename].decode(), '#include "dev.h"\n', '#include "dev.h"\n' + include)
    raw = section(text, 'sk_filter_trim_cap')
    outputs[filename] = replace(text, raw, filter_guard(raw)).encode()
    filename = 'security/security.c'
    text = replace(outputs[filename].decode(), '#include <net/lsf_stream_device_sysfs.h>\n',
        '#include <net/lsf_stream_device_sysfs.h>\n' + include)
    raw = section(text, 'security_sock_rcv_skb')
    outputs[filename] = replace(text, raw, security_guard(raw)).encode()
    filename = 'security/selinux/hooks.c'
    text = replace(outputs[filename].decode(), '#include <net/lsf_stream_device_sysfs.h>\n',
        '#include <net/lsf_stream_device_sysfs.h>\n' + include)
    raw = section(text, 'selinux_socket_sock_rcv_skb')
    outputs[filename] = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'bool lsf_prepaid_device_selinux_socket_hook(int (*candidate)(struct sock *, struct sk_buff *))\n'
        '{\n\treturn candidate == selinux_socket_sock_rcv_skb;\n}\n#endif\n').encode()
    return outputs
