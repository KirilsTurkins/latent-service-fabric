"""Finite existing-companion put: real atomic nonfinal branch only.

Final/invalid/saturated references retain the actual borrow and native charge.
No ordinary provider put or destructor changes.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_provider_queue as prior
from tools.host_stream_kernel_device_security import function

OWNED = prior.OWNED
require = prior.require
replace = prior.replace
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_cleanup_provider_nonfinal.json'
FIXTURE_SHA = '261907775933b41a76b72d561920c333cf1f51e1501d4b91be339c0f42e89573'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 32 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-provider-nonfinal-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-provider-nonfinal-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 6 and len(value['sections']) == 5 and len(value['parentDerived']) == 3 and
        all(value[key] is False for key in ('actualAtomicExecution', 'actualCompanionPut',
            'providerQualified', 'nativeCapacityRefunded', 'productionInstallation')),
        'cleanup-provider-nonfinal-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-provider-nonfinal-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == expected['gitBlob'],
            'cleanup-provider-nonfinal-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-provider-nonfinal-definition-preimage')


def definition(name):
    return preimages()['sections'][name]['text']


def atomic_nonfinal():
    text = replace(definition('refcount_dec_not_one'), 'bool refcount_dec_not_one(refcount_t *r)',
        'static int lsf_cleanup_provider_ref_put_nonfinal(refcount_t *r)')
    text = replace(text, '\t\tif (unlikely(val == REFCOUNT_SATURATED))\n\t\t\treturn true;\n',
        '\t\tif (unlikely(val == REFCOUNT_SATURATED))\n\t\t\treturn -EOVERFLOW;\n'
        '\t\tif ((int)val < 0)\n\t\t\treturn -EIO;\n')
    text = replace(text, '\t\tif (val == 1)\n\t\t\treturn false;\n',
        '\t\tif (val == 1)\n\t\t\treturn -EOPNOTSUPP;\n')
    text = replace(text, '\t\tif (new > val) {\n'
        '\t\t\tWARN_ONCE(new > val, "refcount_t: underflow; use-after-free.\\n");\n'
        '\t\t\treturn true;\n\t\t}\n',
        '\t\tif (new > val)\n\t\t\treturn -EIO;\n')
    return replace(text, '\treturn true;\n', '\treturn 0;\n')


def firmware_put(text):
    old = function(text, 'static void lsf_factory_device_firmware_put(')
    new = replace(old, '    int finished = 0;\n', '    int finished = 0, put_error = 0;\n')
    new = replace(new, '    /* No dereference of companion after put. A concurrent invalidation may\n'
        '     * revoke currentness, but cannot retire/reuse this descriptor or PCI view. */\n',
        '    /* Revalidate the same real borrow before the atomic put. Invalidation\n'
        '     * cannot retire/reuse this descriptor or PCI view under this lock. */\n')
    new = replace(new, '        acpi_dev_put(companion);\n',
        '        /* The actual atomic put runs below under the same metadata\n'
        '         * lock as invalidation. No destructor or allocator is called. */\n')
    new = replace(new, '    owned->companion = NULL;\n',
        '    if (companion) {\n'
        '        if (!companion->dev.kobj.state_initialized)\n'
        '            put_error = -EIO;\n'
        '        else\n'
        '            put_error = lsf_cleanup_provider_ref_put_nonfinal(&companion->dev.kobj.kref.refcount);\n'
        '        if (put_error) {\n'
        '            owned->put_error = put_error;\n'
        '            goto poison; /* Actual reference/descriptor/PCI/native charge retained. */\n'
        '        }\n'
        '        /* LAST companion field access was the successful release CAS.\n'
        '         * A concurrent remaining owner may now perform final free. */\n'
        '    }\n'
        '    owned->companion = NULL;\n')
    return replace(text, old, new)


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-provider-nonfinal-parent-preimage')
    outputs = dict(outputs)
    name = 'net/factory-device-firmware.c'
    text = replace(outputs[name].decode(),
        '    unsigned int revoked, retirement, queued, putting, returned;\n',
        '    unsigned int revoked, retirement, queued, putting, returned;\n    int put_error;\n')
    text = firmware_put(text)
    # This static leaf accepts only the already-proven real borrowed kref in
    # the one exact callback. It is not exported as an object/admission API.
    text = replace(text, 'static void lsf_factory_device_firmware_put(',
        '#include "factory-cleanup-provider-nonfinal.c"\n\n'
        'static void lsf_factory_device_firmware_put(')
    query = '''
static int lsf_factory_device_firmware_retirement_error(void)
{
    struct lsf_factory_device_firmware *owned;
    unsigned long flags;
    int error = 0;
    spin_lock_irqsave(&pool_lock, flags);
    owned = lsf_factory_device_firmware_locked();
    if (owned)
        error = owned->put_error;
    spin_unlock_irqrestore(&pool_lock, flags);
    return error;
}
'''
    outputs[name] = (text+query).encode()
    name = 'net/factory.c'
    text = outputs[name].decode()
    old = function(text, 'static ssize_t lsf_factory_read(')
    new = replace(old, '    else if (count == sizeof(factory.reply) && factory.reply_pending) {\n',
        '    else if (lsf_factory_device_firmware_retirement_error())\n'
        '        error = lsf_factory_device_firmware_retirement_error();\n'
        '    else if (count == sizeof(factory.reply) && factory.reply_pending) {\n')
    text = replace(text, old, new)
    old = function(text, 'static ssize_t lsf_factory_write(')
    new = replace(old,
        '    if (!lsf_factory_actor(file) || READ_ONCE(factory.uncertain) || factory.reply_pending ||\n',
        '    if (!lsf_factory_actor(file)) {\n        error = -EPERM;\n        goto out;\n    }\n'
        '    error = lsf_factory_device_firmware_retirement_error();\n'
        '    if (error)\n        goto out;\n'
        '    if (READ_ONCE(factory.uncertain) || factory.reply_pending ||\n')
    outputs[name] = replace(text, old, new).encode()
    outputs['net/factory-cleanup-provider-nonfinal.c'] = atomic_nonfinal().encode()
    return outputs
