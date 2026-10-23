"""Actual Root-owned task-fork AVC/SID/audit route; uninstalled source only.

This adds no ordinary cache adoption, PCI impersonation, alternate ledger or
bootstrap qualification. Enabled audit task contexts and perf remain open.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_constructor as prior
from tools.host_stream_kernel_device_security import function

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_security.json'
FIXTURE_SHA = 'aca415288ab4154e0d0138823a10320970da398607837fd773a1be790a744867'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 64 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-security-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-security-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        value['archiveSha256'] == prior.preimages()['archiveSha256'] and
        len(value['source']) == 1 and len(value['sections']) == 2 and len(value['parentDerived']) == 10 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'enabledAuditTaskClosure', 'perfInheritanceClosure', 'bootstrapQualified',
            'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-security-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-security-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-security-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-security-definition-preimage')


def root_carrier(text):
    text = replace(text, '    LSF_FACTORY_OWNER_DEVICE = 1\n',
        '    LSF_FACTORY_OWNER_DEVICE = 1,\n    LSF_FACTORY_OWNER_CLEANUP = 2\n')
    text = replace(text, 'struct lsf_factory_context;\n',
        '#include "cleanup-security-carrier.h"\nstruct lsf_factory_context;\n')
    text = replace(text, '    struct lsf_device_registration_source device;\n',
        '    struct lsf_device_registration_source device;\n    struct lsf_cleanup_security_source cleanup;\n')
    empty = '''static inline int lsf_root_security_empty(struct lsf_cleanup_security_source source)
{
    return !source.owner.slot && !source.owner.generation && !source.root.slot &&
        !source.root.generation && !source.allocation.slot && !source.allocation.generation &&
        !source.address && !source.kind;
}

'''
    text = replace(text, 'static inline int lsf_factory_blob_shape(',
        empty + 'static inline int lsf_factory_blob_shape(')
    text = replace(text, '        return source.context && !source.device.address',
        '        return lsf_root_security_empty(source.cleanup) && source.context && !source.device.address')
    text = replace(text, '    if (source.domain != LSF_FACTORY_OWNER_DEVICE || source.context ||\n',
        '    if (source.domain == LSF_FACTORY_OWNER_CLEANUP)\n'
        '        return !source.context && !source.device.address && !source.device.kind &&\n'
        '            !source.device.slot && !source.device.generation && !source.device.pci_slot &&\n'
        '            !source.device.pci_generation && lsf_root_security_shape(source.cleanup) &&\n'
        '            source.ticket.slot == source.cleanup.allocation.slot &&\n'
        '            source.ticket.generation == source.cleanup.allocation.generation;\n'
        '    if (!lsf_root_security_empty(source.cleanup) ||\n'
        '        source.domain != LSF_FACTORY_OWNER_DEVICE || source.context ||\n')
    text = replace(text, '    return a.device.pci_slot == b.device.pci_slot &&\n',
        '    if (a.domain == LSF_FACTORY_OWNER_CLEANUP)\n'
        '        return a.cleanup.owner.slot == b.cleanup.owner.slot &&\n'
        '            a.cleanup.owner.generation == b.cleanup.owner.generation &&\n'
        '            a.cleanup.root.slot == b.cleanup.root.slot &&\n'
        '            a.cleanup.root.generation == b.cleanup.root.generation;\n'
        '    return a.device.pci_slot == b.device.pci_slot &&\n')
    return text


def dispatch_security(text):
    # Preserve each complete original PCI helper and add one typed dispatcher.
    # Later callbacks use the actual Root independently of the creating task.
    signatures = {
        'record': ('static struct lsf_prepaid_view *', 'struct lsf_factory_blob source', 'source'),
        'allocate': ('static void *', 'struct lsf_factory_blob source, unsigned long bytes, unsigned int logical_kind', 'source, bytes, logical_kind'),
        'finish': ('static int ', 'struct lsf_factory_blob source, unsigned int logical_kind', 'source, logical_kind'),
        'phase': ('static int ', 'struct lsf_factory_blob source, unsigned int phase', 'source, phase'),
        'publish': ('static int ', 'struct lsf_factory_blob source, unsigned int location, lsf_u64 identity', 'source, location, identity'),
        'queue': ('static int ', 'struct lsf_factory_blob source', 'source'),
    }
    for name, (result, parameters, arguments) in signatures.items():
        symbol = 'lsf_factory_device_security_' + name + '_locked'
        original = function(text, result + symbol + '(')
        private = replace(original, symbol + '(', symbol + '_pci(', 1)
        wrapper = '\n\n' + result + symbol + '(' + parameters + ')\n{\n' + \
            '    if (source.domain == LSF_FACTORY_OWNER_CLEANUP)\n' + \
            '        return lsf_cleanup_security_' + name + '_locked(' + arguments + ');\n' + \
            '    return ' + symbol + '_pci(' + arguments + ');\n}'
        text = replace(text, original, private + wrapper)
    symbol = 'lsf_factory_device_security_lookup_locked'
    original = function(text, 'static int ' + symbol + '(')
    private = replace(original, symbol + '(', symbol + '_pci(', 1)
    wrapper = '''

static int lsf_factory_device_security_lookup_locked(const void *address,
    unsigned int logical_kind, struct lsf_factory_blob *copy)
{
    int root = lsf_cleanup_security_lookup_locked(address, logical_kind, copy);
    if (root != LSF_ROOT_SECURITY_DELEGATE)
        return root;
    return lsf_factory_device_security_lookup_locked_pci(address, logical_kind, copy);
}'''
    text = replace(text, original, private + wrapper)
    original = function(text, 'static struct lsf_prepaid_view *lsf_factory_security_avc_record_locked(')
    updated = replace(original, '    if (source.domain == LSF_FACTORY_OWNER_DEVICE) {\n',
        '    if (source.domain == LSF_FACTORY_OWNER_CLEANUP)\n'
        '        return lsf_cleanup_security_avc_record_locked(source, phase, bucket, context);\n'
        '    if (source.domain == LSF_FACTORY_OWNER_DEVICE) {\n')
    text = replace(text, original, updated)
    original = function(text, 'static int lsf_factory_security_avc_replace_locked(')
    updated = replace(original, '    if (source.domain == LSF_FACTORY_OWNER_DEVICE)\n',
        '    if (source.domain != LSF_FACTORY_OWNER_APPLICATION)\n')
    return replace(text, original, updated)


def task_hook():
    original = preimages()['sections']['selinux_task_alloc']['text']
    return replace(original, '\treturn avc_has_perm(sid, sid, SECCLASS_PROCESS, PROCESS__FORK, NULL);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t{\n\t\tstruct lsf_factory_blob source;\n'
        '\t\tint origin = lsf_factory_cleanup_task_constructor_blob(task, &source);\n'
        '\t\tif (origin < 0)\n\t\t\treturn -EIO;\n'
        '\t\tif (origin == 1)\n'
        '\t\t\treturn lsf_prepaid_avc_has_perm(sid, sid, SECCLASS_PROCESS, PROCESS__FORK, NULL, &source);\n'
        '\t}\n#endif\n'
        '\treturn avc_has_perm(sid, sid, SECCLASS_PROCESS, PROCESS__FORK, NULL);\n')


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-security-parent-preimage')
    outputs = dict(outputs)
    outputs['net/cleanup-security-carrier.h'] = (OWNED / 'cleanup-security-carrier.h').read_bytes()
    outputs['net/factory-cleanup-security.c'] = (OWNED / 'factory-cleanup-security.c').read_bytes()
    name = 'net/device-owner-carrier.h'
    outputs[name] = root_carrier(outputs[name].decode()).encode()
    name = 'net/device-prepaid.h'
    text = replace(outputs[name].decode(), '    LSF_DEVICE_CLEANUP_TASK_SECURITY\n',
        '    LSF_DEVICE_CLEANUP_TASK_SECURITY,\n    LSF_DEVICE_ROOT_AVC_NODE = 0x140,\n'
        '    LSF_DEVICE_ROOT_AVC_XPERMS,\n    LSF_DEVICE_ROOT_AVC_DECISION,\n'
        '    LSF_DEVICE_ROOT_AVC_DATA,\n    LSF_DEVICE_ROOT_SIDCACHE,\n'
        '    LSF_DEVICE_ROOT_AUDIT_STRING,\n    LSF_DEVICE_ROOT_AUDIT_BUFFER,\n'
        '    LSF_DEVICE_ROOT_AUDIT_SKB,\n    LSF_DEVICE_ROOT_AUDIT_HEAD\n')
    text = replace(text, '        kind == LSF_DEVICE_CLEANUP_TASK_SECURITY;\n',
        '        kind == LSF_DEVICE_CLEANUP_TASK_SECURITY ||\n'
        '        kind == LSF_DEVICE_ROOT_AVC_NODE || kind == LSF_DEVICE_ROOT_AVC_XPERMS ||\n'
        '        kind == LSF_DEVICE_ROOT_AVC_DECISION || kind == LSF_DEVICE_ROOT_AVC_DATA ||\n'
        '        kind == LSF_DEVICE_ROOT_SIDCACHE || kind == LSF_DEVICE_ROOT_AUDIT_STRING ||\n'
        '        kind == LSF_DEVICE_ROOT_AUDIT_BUFFER || kind == LSF_DEVICE_ROOT_AUDIT_SKB ||\n'
        '        kind == LSF_DEVICE_ROOT_AUDIT_HEAD;\n')
    outputs[name] = text.encode()
    name = 'net/factory-device-security.c'
    outputs[name] = dispatch_security(outputs[name].decode()).encode()
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include "factory-device-security.c"\n',
        '#include "factory-cleanup-security.c"\n#include "factory-device-security.c"\n')
    # These existing branches already dispatch through the typed wrappers above.
    require(text.count('== LSF_FACTORY_OWNER_DEVICE') == 6, 'cleanup-security-generic-dispatch-count')
    text = text.replace('== LSF_FACTORY_OWNER_DEVICE', '!= LSF_FACTORY_OWNER_APPLICATION')
    text = replace(text, '    lsf_prepaid_device_sidcache_drain();\n',
        '    lsf_prepaid_device_sidcache_drain();\n    lsf_prepaid_cleanup_sidcache_drain();\n')
    outputs[name] = replace(text, '    lsf_prepaid_device_avc_drain();\n',
        '    lsf_prepaid_device_avc_drain();\n    lsf_prepaid_cleanup_avc_drain();\n').encode()
    name = 'net/factory-avc.c'
    text = outputs[name].decode()
    require(text.count('== LSF_FACTORY_OWNER_DEVICE') == 4, 'cleanup-security-avc-dispatch-count')
    outputs[name] = text.replace('== LSF_FACTORY_OWNER_DEVICE', '!= LSF_FACTORY_OWNER_APPLICATION').encode()
    name = 'security/selinux/hooks.c'
    outputs[name] = replace(outputs[name].decode(),
        preimages()['sections']['selinux_task_alloc']['text'], task_hook()).encode()
    name = 'security/selinux/lsf_avc_private.c'
    text = outputs[name].decode()
    original = function(text, 'void lsf_prepaid_device_avc_drain(')
    root = original.replace('lsf_prepaid_device_avc_drain', 'lsf_prepaid_cleanup_avc_drain')
    root = root.replace('struct lsf_device_registration_source', 'struct lsf_cleanup_security_source')
    root = root.replace('lsf_factory_device_security_', 'lsf_factory_cleanup_security_')
    root = root.replace('LSF_DEVICE_SECURITY_AVC_NODE', 'LSF_ROOT_SECURITY_AVC_NODE')
    outputs[name] = (text + '\n' + root + '\n').encode()
    name = 'security/selinux/ss/lsf_audit_string_private.c'
    text = outputs[name].decode()
    original = function(text, 'void lsf_prepaid_device_sidcache_drain(')
    root = original.replace('lsf_prepaid_device_sidcache_drain', 'lsf_prepaid_cleanup_sidcache_drain')
    root = root.replace('struct lsf_device_registration_source', 'struct lsf_cleanup_security_source')
    root = root.replace('lsf_factory_device_security_', 'lsf_factory_cleanup_security_')
    root = root.replace('LSF_DEVICE_SECURITY_SIDCACHE', 'LSF_ROOT_SECURITY_SIDCACHE')
    root = root.replace('lsf_prepaid_device_sidcache_detach', 'lsf_prepaid_cleanup_sidcache_detach')
    outputs[name] = (text + '\n' + root + '\n').encode()
    name = 'security/selinux/ss/lsf_sidcache_private.c'
    text = outputs[name].decode()
    begin = text.index('#if CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE > 0\n')
    original = text[begin:]
    require(original.count('void lsf_prepaid_device_sidcache_detach(') == 2,
        'cleanup-security-both-sidcache-profiles')
    root = original.replace('lsf_prepaid_device_sidcache_detach', 'lsf_prepaid_cleanup_sidcache_detach')
    root = root.replace('struct lsf_device_registration_source', 'struct lsf_cleanup_security_source')
    root = root.replace('lsf_factory_device_security_current', 'lsf_factory_cleanup_security_current')
    outputs[name] = (text + '\n' + root).encode()
    return outputs
