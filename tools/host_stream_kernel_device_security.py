"""Explicit tagged NodeFixed owner propagation for mandatory SIGIO security.

The grouped recipient implementation remains uninstalled; callback/receive,
instrumentation, shared queue, cache-drain and physical proof gates stay open.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_recipient as prior
from tools import host_stream_kernel_maintained as maintained

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_security.json'
EXTRAS = {'fs/fcntl.c'}
DEFINITIONS = {'security_file_send_sigiotask', 'selinux_file_send_sigiotask',
    'sigio_perm', 'send_sigio_to_task', 'send_sigio', 'kill_fasync_rcu', 'kill_fasync',
    'sock_wake_async', 'sk_wake_async_rcu',
    'lsm_for_each_hook', 'call_int_hook', '__CALL_STATIC_INT', 'LSM_RET_DEFAULT'}
GATES = prior.GATES + ('deviceSecurityCarrierQualified', 'actualDeviceSecurityExecuted',
    'deviceSecurityCachesDrained', 'completeDeviceSecurityClosure')
replace = prior.replace
require = prior.require
SECURITY_KINDS = ('AVC_NODE', 'AVC_XPERMS', 'AVC_DECISION', 'AVC_DATA', 'SIDCACHE',
    'AUDIT_STRING', 'AUDIT_BUFFER', 'AUDIT_SKB', 'AUDIT_HEAD')


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-security-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-security-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-security-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-security-definitions')
    require(all(value[name] is False for name in GATES), 'device-security-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-security-definition-occurrence')
    end = text.find(row.get('terminator', '\n}\n'), starts[0])
    require(end >= 0, 'device-security-definition-end')
    raw = text[starts[0]:end + len(row.get('terminator', '\n}\n'))]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'], 'device-security-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-security-whole-membership')
    maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name in DEFINITIONS:
        row = value['sections'][name]
        section(inputs[row['source']].decode(), name)


def function(text, prefix):
    require(text.count(prefix) == 1, 'device-security-selected-function-occurrence')
    start = text.index(prefix)
    end = text.find('\n}\n', start)
    require(end >= 0, 'device-security-selected-function-end')
    return text[start:end + 3]


def carrier_headers(outputs):
    text = outputs['net/device-prepaid.h'].decode()
    text = replace(text, '    LSF_DEVICE_RECIPIENT_SIGQUEUE\n',
        '    LSF_DEVICE_RECIPIENT_SIGQUEUE,\n' +
        ',\n'.join('    LSF_DEVICE_' + name for name in SECURITY_KINDS) + '\n')
    outputs['net/device-prepaid.h'] = replace(text,
        '        kind == LSF_DEVICE_RECIPIENT_SIGQUEUE;\n',
        '        kind == LSF_DEVICE_RECIPIENT_SIGQUEUE ||\n' +
        ' ||\n'.join('        kind == LSF_DEVICE_' + name for name in SECURITY_KINDS) + ';\n').encode()
    outputs['net/prepaid.h'] = replace(outputs['net/prepaid.h'].decode(),
        '    lsf_u64 cache_anchor;\n',
        '    lsf_u64 cache_anchor;\n    unsigned int security_cache_location;\n'
        '    lsf_u64 security_cache_identity;\n').encode()
    text = outputs['net/factory-private.h'].decode()
    original = ('struct lsf_factory_blob {\n    struct lsf_factory_context *context;\n'
        '    struct lsf_prepaid_ticket ticket;\n};\n')
    outputs['net/factory-private.h'] = replace(text, original,
        '#include <net/lsf_stream_device_recipient.h>\n#include "device-owner-carrier.h"\n'
        'void lsf_factory_blob_poison(struct lsf_factory_blob);\n').encode()
    for name in ('device-owner-carrier.h', 'device-security-prepaid.h', 'factory-device-security.c'):
        outputs['net/' + name] = (OWNED / name).read_bytes()
    text = replace(outputs['net/factory.c'].decode(), '#include "device-recipient-allocator.h"\n',
        '#include "device-recipient-allocator.h"\n#include "device-security-prepaid.h"\n')
    outputs['net/factory.c'] = replace(text, '#include "factory-device-recipient.c"\n',
        '#include "factory-device-recipient.c"\n#include "factory-device-security.c"\n').encode()


def generic_factory(text):
    raw = function(text, 'void *lsf_factory_child_allocate(')
    updated = replace(raw, '    context = lsf_factory_context_current(parent.context);\n',
        '    if (!lsf_factory_blob_shape(parent)) {\n'
        '        lsf_factory_device_firmware_poison();\n'
        '        spin_unlock_irqrestore(&pool_lock, flags);\n        return NULL;\n    }\n'
        '    if (parent.domain == LSF_FACTORY_OWNER_DEVICE) {\n'
        '        result = lsf_factory_device_security_allocate_locked(parent, bytes, kind);\n'
        '        spin_unlock_irqrestore(&pool_lock, flags);\n        return result;\n    }\n'
        '    context = lsf_factory_context_current(parent.context);\n')
    text = replace(text, raw, updated)
    raw = function(text, 'static int lsf_factory_blob_lookup_locked(')
    updated = replace(raw, '    struct lsf_prepaid_key key;\n',
        '    struct lsf_prepaid_key key;\n    int device;\n')
    updated = replace(updated, '    if (!factory.pages)\n',
        '    if (!copy)\n        return -1;\n'
        '    device = lsf_factory_device_security_lookup_locked(address, kind, copy);\n'
        '    if (device != LSF_DEVICE_SECURITY_DELEGATE)\n        return device;\n'
        '    if (!factory.pages)\n')
    updated = replace(updated, '    copy->context = &factory.contexts[key.slot];\n    copy->ticket = ticket;\n',
        '    *copy = (struct lsf_factory_blob){.context = &factory.contexts[key.slot], .ticket = ticket};\n')
    text = replace(text, raw, updated)
    text = replace(text, '    copy->context = context;\n    copy->ticket = ticket;\n',
        '    *copy = (struct lsf_factory_blob){.context = context, .ticket = ticket};\n')
    raw = function(text, 'int lsf_factory_blob_finish(')
    updated = replace(raw, '    context = lsf_factory_context_current(copy.context);\n',
        '    if (!lsf_factory_blob_shape(copy)) {\n'
        '        lsf_factory_device_firmware_poison();\n'
        '        spin_unlock_irqrestore(&pool_lock, flags);\n        return 0;\n    }\n'
        '    if (copy.domain == LSF_FACTORY_OWNER_DEVICE) {\n'
        '        result = lsf_factory_device_security_finish_locked(copy, kind);\n'
        '        spin_unlock_irqrestore(&pool_lock, flags);\n        return result;\n    }\n'
        '    context = lsf_factory_context_current(copy.context);\n')
    text = replace(text, raw, updated)
    text = replace(text, 'copy.context != lsf_factory_context_current(parent.context)',
        '!lsf_factory_blob_same_owner(copy, parent)')
    raw = function(text, 'int lsf_factory_audit_head_current(')
    updated = replace(raw, '        factory.pool.contexts[copy->context->key.slot].poisoned = 1;\n',
        '        if (copy->domain == LSF_FACTORY_OWNER_DEVICE)\n'
        '            lsf_factory_device_firmware_poison();\n'
        '        else\n            factory.pool.contexts[copy->context->key.slot].poisoned = 1;\n')
    text = replace(text, raw, updated)
    for name, action in [('publish', 'lsf_factory_device_security_publish_locked(copy, 0, anchor)'),
                         ('queue', 'lsf_factory_device_security_queue_locked(copy)'),
                         ('destroy', '(lsf_factory_device_security_queue_locked(copy) == 1 && '
                          'lsf_factory_device_security_finish_locked(copy, LSF_PREPAID_SIDCACHE) ? 1 : -1)')]:
        raw = function(text, 'int lsf_factory_sidcache_' + name + '(')
        anchor = '    result = lsf_factory_blob_lookup_locked(address, LSF_PREPAID_SIDCACHE, &copy);\n'
        updated = replace(raw, anchor, anchor +
            '    if (result == 1 && copy.domain == LSF_FACTORY_OWNER_DEVICE) {\n'
            '        result = ' + action + ';\n'
            '        spin_unlock_irqrestore(&pool_lock, flags);\n        return result;\n    }\n')
        text = replace(text, raw, updated)
    return text


def factory_avc(text):
    raw = function(text, 'int lsf_factory_avc_phase(')
    updated = replace(raw, '    context = lsf_factory_context_current(copy.context);\n',
        '    if (!lsf_factory_blob_shape(copy))\n        goto invalid;\n'
        '    if (copy.domain == LSF_FACTORY_OWNER_DEVICE) {\n'
        '        result = lsf_factory_device_security_phase_locked(copy, phase);\n'
        '        spin_unlock_irqrestore(&pool_lock, flags);\n        return result;\n    }\n'
        '    context = lsf_factory_context_current(copy.context);\n')
    text = replace(text, raw, updated)
    raw = function(text, 'int lsf_factory_avc_replace(')
    updated = replace(raw, '        if (owned)\n            prior_key = prior.context->key;\n',
        '        if (owned && prior.domain == LSF_FACTORY_OWNER_APPLICATION)\n'
        '            prior_key = prior.context->key;\n')
    anchor = ('    if (!lsf_prepaid_avc_replace(&factory.pool, copy.context->key, copy.ticket,\n'
        '                                prior_key, prior.ticket, owned, bucket))\n        goto invalid;\n')
    updated = replace(updated, anchor,
        '    if (!lsf_factory_blob_shape(copy) || (owned && !lsf_factory_blob_shape(prior)))\n'
        '        goto invalid;\n'
        '    if (copy.domain == LSF_FACTORY_OWNER_DEVICE ||\n'
        '        (owned && prior.domain == LSF_FACTORY_OWNER_DEVICE)) {\n'
        '        if (!lsf_factory_security_avc_replace_locked(copy, owned ? &prior : NULL, bucket))\n'
        '            goto invalid;\n'
        '    } else {\n' + anchor + '    }\n')
    text = replace(text, raw, updated)
    raw = function(text, 'int lsf_factory_avc_queue(')
    anchor = '    result = lsf_factory_blob_lookup_locked(address, LSF_PREPAID_AVC_NODE, &copy);\n'
    updated = replace(raw, anchor, anchor +
        '    if (result == 1 && copy.domain == LSF_FACTORY_OWNER_DEVICE) {\n'
        '        result = lsf_factory_device_security_queue_locked(copy);\n'
        '        spin_unlock_irqrestore(&pool_lock, flags);\n        return result;\n    }\n')
    return replace(text, raw, updated)


def complete_owner_comparisons(outputs):
    name = 'security/selinux/lsf_avc_private.c'
    text = outputs[name].decode()
    text = replace(text, '    struct lsf_factory_context *context;\n',
        '    struct lsf_factory_blob owner;\n')
    text = replace(text, 'copy->context != walk->context',
        '!lsf_factory_blob_same_owner(*copy, walk->owner)')
    text = replace(text, 'walk.context = copy->context;', 'walk.owner = *copy;')
    text = replace(text, 'walk.context = copy.context;', 'walk.owner = copy;', 2)
    text = replace(text, 'copy.context != source->context',
        '!lsf_factory_blob_same_owner(copy, *source)', 2)
    outputs[name] = text.encode()
    for name, old, new, count in [
        ('net/audit-skb-private.c', 'head_birth.context != source.context', '!lsf_factory_blob_same_owner(head_birth, source)', 1),
        ('net/packet-skb-private.c', 'head_birth.context != source.context', '!lsf_factory_blob_same_owner(head_birth, source)', 1),
        ('net/packet-skb-private.c', 'source.context != parent.context', '!lsf_factory_blob_same_owner(source, parent)', 1),
        ('security/selinux/netlabel.c', 'copy.context == source->context', 'lsf_factory_blob_same_owner(copy, *source)', 1),
        ('net/netlabel/lsf_netlabel_private.c', 'child.context != copy.context', '!lsf_factory_blob_same_owner(child, copy)', 2)]:
        outputs[name] = replace(outputs[name].decode(), old, new, count).encode()
    # These are known carrier branches, not the separate context-only
    # application protocol/drain APIs. Preserve that original application
    # poison while refusing device/unknown errors through the actual domain.
    for name, expression, count in [
        ('net/audit-skb-private.c', 'source.context', 3),
        ('net/packet-skb-private.c', 'source.context', 3),
        ('net/packet-skb-private.c', 'parent.context', 1),
        ('security/selinux/lsf_avc_private.c', 'copy->context', 1),
        ('security/selinux/lsf_avc_private.c', 'copy.context', 2),
        ('security/selinux/netlabel.c', 'source->context', 1),
        ('net/netlabel/lsf_netlabel_private.c', 'copy.context', 1),
        ('net/ipv4/lsf_bind_private.c', 'source->context', 1),
        ('net/ipv4/lsf_bind_private.c', 'source.context', 2),
        ('net/ipv4/lsf_bind_private.c', 'copy.context', 1),
        ('net/ipv4/lsf_route_private.c', 'source->context', 1),
        ('net/ipv4/lsf_route_private.c', 'source.context', 3)]:
        carrier = ('*' + expression.split('->', 1)[0]) if '->' in expression else expression.split('.', 1)[0]
        outputs[name] = replace(outputs[name].decode(), 'lsf_factory_poison(' + expression + ')',
            'lsf_factory_blob_poison(' + carrier + ')', count).encode()


def device_cache_drains(outputs):
    """Keep original application drains; clone their real cache/RCU algorithm.

    Device candidates carry scalar generation/parent/cache identity only.
    The actual pointer is derived after the original cache lock and (for SID)
    current-policy table identity check. A finite scan is no final-free proof.
    """
    name = 'net/factory-private.h'
    text = outputs[name].decode()
    declarations = '''int lsf_factory_device_security_candidate(unsigned int, unsigned int,
    struct lsf_device_registration_source *, unsigned int *, lsf_u64 *);
int lsf_factory_device_security_current(struct lsf_device_registration_source,
    unsigned int, lsf_u64, void **);
void lsf_prepaid_device_avc_drain(void);
void lsf_prepaid_device_sidcache_drain(void);
struct sidtab;
void lsf_prepaid_device_sidcache_detach(struct sidtab *, struct lsf_device_registration_source);
'''
    outputs[name] = replace(text, 'void lsf_prepaid_avc_drain(struct lsf_factory_context *);\n',
        'void lsf_prepaid_avc_drain(struct lsf_factory_context *);\n' + declarations).encode()
    name = 'security/selinux/lsf_avc_private.c'
    text = outputs[name].decode()
    raw = function(text, 'void lsf_prepaid_avc_drain(')
    private = replace(raw, 'void lsf_prepaid_avc_drain(struct lsf_factory_context *context)',
        'void lsf_prepaid_device_avc_drain(void)')
    private = replace(private, '    struct lsf_prepaid_ticket ticket;\n',
        '    struct lsf_device_registration_source candidate;\n    lsf_u64 identity;\n')
    private = replace(private,
        'lsf_factory_avc_candidate(context, slot, &ticket, &bucket)',
        'lsf_factory_device_security_candidate(slot, LSF_DEVICE_SECURITY_AVC_NODE,\n'
        '                &candidate, &bucket, &identity)')
    private = replace(private, '            continue;\n        spin_lock_irqsave(',
        '            continue;\n        bucket--;\n        spin_lock_irqsave(')
    private = replace(private, 'lsf_factory_avc_current(context, ticket, bucket, &address)',
        'lsf_factory_device_security_current(candidate, bucket + 1u, identity, &address)')
    outputs[name] = (text + '\n' + private).encode()
    name = 'security/selinux/ss/lsf_audit_string_private.c'
    text = outputs[name].decode()
    raw = function(text, 'void lsf_prepaid_sidcache_drain(')
    private = replace(raw, 'void lsf_prepaid_sidcache_drain(struct lsf_factory_context *context)',
        'void lsf_prepaid_device_sidcache_drain(void)')
    private = replace(private, '    struct lsf_prepaid_ticket ticket;\n',
        '    struct lsf_device_registration_source candidate;\n    unsigned int location;\n')
    private = replace(private, 'lsf_factory_sidcache_candidate(context, slot, &ticket, &anchor)',
        'lsf_factory_device_security_candidate(slot, LSF_DEVICE_SECURITY_SIDCACHE,\n'
        '                &candidate, &location, &anchor)')
    private = replace(private, 'lsf_prepaid_sidcache_detach(policy->sidtab, context, ticket)',
        'lsf_prepaid_device_sidcache_detach(policy->sidtab, candidate)')
    outputs[name] = (text + '\n' + private).encode()
    name = 'security/selinux/ss/lsf_sidcache_private.c'
    text = outputs[name].decode()
    require(text.count('void lsf_prepaid_sidcache_detach(') == 2 and text.endswith('#endif\n'),
        'device-security-sidcache-both-config-preimage')
    raw = text[text.index('void lsf_prepaid_sidcache_detach('):]
    private = replace(raw, 'void lsf_prepaid_sidcache_detach(struct sidtab *table,\n'
        '    struct lsf_factory_context *context, struct lsf_prepaid_ticket ticket)',
        'void lsf_prepaid_device_sidcache_detach(struct sidtab *table,\n'
        '    struct lsf_device_registration_source candidate)', 2)
    private = replace(private,
        'lsf_factory_sidcache_current(context, ticket,\n            (lsf_u64)(unsigned long)table, &address)',
        'lsf_factory_device_security_current(candidate, 0,\n            (lsf_u64)(unsigned long)table, &address)')
    private = replace(private, 'lsf_factory_poison(context);', 'lsf_factory_device_uevent_poison();', 2)
    private = replace(private, '    (void)ticket;\n', '    (void)candidate;\n')
    outputs[name] = (text + '\n#if CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE > 0\n' + private).encode()
    name = 'net/factory.c'
    text = outputs[name].decode()
    text = replace(text, '    /* Closing a descriptor is not final-free. No __free_pages, object release,\n',
        '    lsf_prepaid_device_sidcache_drain();\n'
        '#ifdef LSF_STREAM_AVC_SOURCE\n    lsf_prepaid_device_avc_drain();\n#endif\n'
        '    /* Device cache scans, like application scans, leave actual RCU\n'
        '     * callbacks and any legitimate late descendants charged. No single\n'
        '     * pass is complete retirement or an acknowledgement of backing. */\n'
        '    /* Closing a descriptor is not final-free. No __free_pages, object release,\n')
    outputs[name] = text.encode()


def private_fcntl(inputs):
    text = inputs['fs/fcntl.c'].decode()
    pieces = []
    for name in ('sigio_perm', 'send_sigio_to_task', 'send_sigio', 'kill_fasync_rcu', 'kill_fasync'):
        raw = section(text, name)
        raw = replace(raw, name + '(', 'lsf_prepaid_device_' + name +
            '(struct lsf_device_registration_source source, ')
        if name == 'send_sigio':
            raw = replace(raw, 'void lsf_prepaid_device_send_sigio(',
                'static void lsf_prepaid_device_send_sigio(')
        guard = ('\tif (!lsf_factory_device_recipient_current(source, NULL))\n'
            '\t\treturn' + (' 0' if name == 'sigio_perm' else '') + ';\n')
        if name == 'sigio_perm':
            raw = replace(raw, '\tint ret;\n', '\tint ret;\n\n' + guard)
        elif name == 'send_sigio_to_task':
            raw = replace(raw, '\tint signum = READ_ONCE(fown->signum);\n',
                '\tint signum;\n\n' + guard + '\tsignum = READ_ONCE(fown->signum);\n')
        elif name == 'send_sigio':
            raw = replace(raw, '\tstruct pid *pid;\n', '\tstruct pid *pid;\n\n' + guard)
        else:
            raw = replace(raw, '\n{\n', '\n{\n' + guard)
        if name == 'sigio_perm':
            raw = replace(raw, 'security_file_send_sigiotask(p, fown, sig)',
                'lsf_prepaid_device_security_file_send_sigiotask(source, p, fown, sig)')
        elif name == 'send_sigio_to_task':
            raw = replace(raw, 'sigio_perm(p, fown, signum)',
                'lsf_prepaid_device_sigio_perm(source, p, fown, signum)')
            raw = replace(raw, 'do_send_sig_info(', 'lsf_prepaid_device_do_send_sig_info(source, ', 2)
        elif name == 'send_sigio':
            raw = replace(raw, 'send_sigio_to_task(', 'lsf_prepaid_device_send_sigio_to_task(source, ', 2)
        elif name == 'kill_fasync_rcu':
            raw = replace(raw, 'send_sigio(fown, fa->fa_fd, band)',
                'lsf_prepaid_device_send_sigio(source, fown, fa->fa_fd, band)')
        else:
            raw = replace(raw, 'kill_fasync_rcu(rcu_dereference(*fp), sig, band)',
                'lsf_prepaid_device_kill_fasync_rcu(source, rcu_dereference(*fp), sig, band)')
        pieces.append(raw)
    return ''.join(pieces)


def security_dispatch():
    return '''int lsf_prepaid_device_security_file_send_sigiotask(
    struct lsf_device_registration_source source, struct task_struct *tsk,
    struct fown_struct *fown, int sig)
{
    struct lsm_static_call *scall;
    struct lsf_factory_blob owner;
    int rc = LSM_RET_DEFAULT(file_send_sigiotask);
    if (lsf_factory_device_recipient_blob(source, &owner) != 1)
        return -EOPNOTSUPP;
    /* Same actual active-hook order/default as call_int_hook. Authenticate
     * every configured hook before any unclosed callback can run. */
    lsm_for_each_hook(scall, file_send_sigiotask) {
#ifdef CONFIG_SECURITY_SELINUX
        if (!lsf_prepaid_device_selinux_sigio_hook(scall->hl->hook.file_send_sigiotask)) {
            lsf_factory_device_uevent_poison();
            return -EOPNOTSUPP;
        }
#else
        lsf_factory_device_uevent_poison();
        return -EOPNOTSUPP;
#endif
    }
    lsm_for_each_hook(scall, file_send_sigiotask) {
#ifdef CONFIG_SECURITY_SELINUX
        rc = lsf_prepaid_device_selinux_file_send_sigiotask(tsk, fown, sig, &owner);
        if (rc == -EOPNOTSUPP)
            lsf_factory_device_uevent_poison();
        if (rc != LSM_RET_DEFAULT(file_send_sigiotask))
            break;
#else
        return -EOPNOTSUPP;
#endif
    }
    return rc;
}
'''


def private_socket_async(inputs):
    raw = section(inputs['net/socket.c'].decode(), 'sock_wake_async')
    raw = replace(raw, 'int sock_wake_async(',
        'static int lsf_prepaid_device_sock_wake_async(struct lsf_device_registration_source source, ')
    raw = replace(raw, '\n{\n', '\n{\n'
        '\tif (!lsf_factory_device_recipient_current(source, NULL))\n'
        '\t\treturn -EOPNOTSUPP;\n')
    socket = replace(raw, 'kill_fasync(', 'lsf_prepaid_device_kill_fasync(source, ', 2)
    raw = section(inputs['include/net/sock.h'].decode(), 'sk_wake_async_rcu')
    raw = replace(raw, 'static inline void sk_wake_async_rcu(',
        'void lsf_prepaid_device_sk_wake_async_rcu(struct lsf_device_registration_source source, ')
    raw = replace(raw, '\n{\n', '\n{\n'
        '\tif (!sk) {\n\t\tlsf_factory_device_uevent_poison();\n\t\treturn;\n\t}\n'
        '\tif (!lsf_factory_device_recipient_current(source, sk))\n\t\treturn;\n')
    core = replace(raw, 'sock_wake_async(rcu_dereference(sk->sk_wq), how, band)',
        'lsf_prepaid_device_sock_wake_async(source, rcu_dereference(sk->sk_wq), how, band)')
    return socket + '\n' + core


def private_selinux(raw):
    require(section(raw, 'selinux_file_send_sigiotask') == raw, 'device-security-selinux-preimage')
    declaration, body = raw.split('\n{\n', 1)
    declaration = replace(declaration, 'static int selinux_file_send_sigiotask(',
        'int lsf_prepaid_device_selinux_file_send_sigiotask(')
    closing = declaration.rfind(')')
    declaration = declaration[:closing] + ', const struct lsf_factory_blob *source' + declaration[closing:]
    body = replace(body, '\tstruct file_security_struct *fsec;\n',
        '\tstruct file_security_struct *fsec;\n\n'
        '\tif (!source || !lsf_factory_blob_shape(*source) ||\n'
        '\t    source->domain != LSF_FACTORY_OWNER_DEVICE ||\n'
        '\t    source->device.kind != LSF_DEVICE_RECIPIENT_KIND_WORK ||\n'
        '\t    !lsf_factory_device_recipient_current(source->device, NULL))\n'
        '\t\treturn -EOPNOTSUPP;\n')
    body = replace(body, '\tu32 sid = task_sid_obj(tsk);\n', '\tu32 sid;\n')
    body = replace(body, '\t\treturn -EOPNOTSUPP;\n',
        '\t\treturn -EOPNOTSUPP;\n\tsid = task_sid_obj(tsk);\n')
    body = replace(body, 'avc_has_perm(', 'lsf_prepaid_avc_has_perm(')
    body = replace(body, 'SECCLASS_PROCESS, perm, NULL);',
        'SECCLASS_PROCESS, perm, NULL, source);')
    return declaration + '\n{\n' + body + '''
bool lsf_prepaid_device_selinux_sigio_hook(
    int (*candidate)(struct task_struct *, struct fown_struct *, int))
{
    return candidate == selinux_file_send_sigiotask;
}
'''


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    carrier_headers(outputs)
    outputs['net/factory.c'] = generic_factory(outputs['net/factory.c'].decode()).encode()
    outputs['net/factory-avc.c'] = factory_avc(outputs['net/factory-avc.c'].decode()).encode()
    complete_owner_comparisons(outputs)
    device_cache_drains(outputs)
    name = 'net/packet-factory.c'
    text = replace(outputs[name].decode(),
        '        copy->context = &factory.contexts[key.slot];\n'
        '        copy->ticket = (struct lsf_prepaid_ticket){i, record->generation};\n',
        '        *copy = (struct lsf_factory_blob){.context = &factory.contexts[key.slot],\n'
        '            .ticket = {i, record->generation}};\n')
    text = replace(text, '        if (record->kind == audit_kind)\n',
        '        if (record->kind == audit_kind ||\n'
        '            (kind == LSF_PREPAID_PACKET_SKB && record->kind == LSF_DEVICE_AUDIT_SKB) ||\n'
        '            (kind == LSF_PREPAID_PACKET_HEAD && record->kind == LSF_DEVICE_AUDIT_HEAD))\n')
    outputs[name] = text.encode()
    name = 'net/factory-device-uevent.c'
    text = replace(outputs[name].decode(),
        '(record->kind == LSF_PREPAID_PACKET_SKB || record->kind == LSF_PREPAID_AUDIT_SKB)',
        '(record->kind == LSF_PREPAID_PACKET_SKB || record->kind == LSF_PREPAID_AUDIT_SKB ||\n'
        '              record->kind == LSF_DEVICE_AUDIT_SKB)')
    outputs[name] = replace(text,
        '(record->kind == LSF_PREPAID_PACKET_HEAD || record->kind == LSF_PREPAID_AUDIT_HEAD)',
        '(record->kind == LSF_PREPAID_PACKET_HEAD || record->kind == LSF_PREPAID_AUDIT_HEAD ||\n'
        '              record->kind == LSF_DEVICE_AUDIT_HEAD)').encode()
    outputs['include/net/lsf_stream_device_recipient_security.h'] = (
        OWNED / 'device-recipient-security-private.h').read_bytes()
    include = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_device_recipient_security.h>\n#endif\n')
    name = 'security/security.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_device_uevent_consumer.h>\n',
        '#include <net/lsf_stream_device_uevent_consumer.h>\n' + include)
    raw = section(text, 'security_file_send_sigiotask')
    outputs[name] = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' +
        security_dispatch() + '#endif\n').encode()
    name = 'security/selinux/hooks.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_device_uevent_consumer.h>\n',
        '#include <net/lsf_stream_device_uevent_consumer.h>\n' + include)
    raw = section(text, 'selinux_file_send_sigiotask')
    outputs[name] = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' +
        private_selinux(raw) + '#endif\n').encode()
    name = 'fs/fcntl.c'
    outputs[name] += ('\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "../net/factory-private.h"\n'
        '#include <net/lsf_stream_device_recipient_security.h>\n'
        '#include "lsf-device-recipient-fcntl.c"\n#endif\n').encode()
    outputs['fs/lsf-device-recipient-fcntl.c'] = private_fcntl(inputs).encode()
    name = 'net/core/sock.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_protocol_private.h>\n',
        '#include <net/lsf_stream_protocol_private.h>\n' + include)
    outputs[name] = (text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-device-recipient-sock.c"\n#endif\n').encode()
    outputs['net/core/lsf-device-recipient-sock.c'] = private_socket_async(inputs).encode()
    return outputs
