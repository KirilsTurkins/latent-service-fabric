"""Generation-bound resumption after real device child final returns.

This uninstalled layer consumes the unchanged maintained recipient derivation.
It adds no allocator, work item, queue, owner, retry or retirement certificate.
Shared queue/bootstrap/instrumentation and physical runtime gates stay false.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_delivery as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_retirement.json'
FIXTURE_SHA = '8ef1b7bf76dc1f5ef0e00898f7526bab7622482b9c36d923815fe528f65da5d5'
GATES = prior.GATES
authenticate = prior.authenticate
replace = prior.replace
require = prior.require


def preimages():
    with FIXTURE.open('rb') as stream:
        raw = stream.read(256 * 1024 + 1)
    require(len(raw) <= 256 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'device-retirement-fixed-derived-preimages')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-device-retirement-derived-preimages.v1' and
        value['parentObjectSourceCommit'] == '1625510fc6b6bcd32505511729ea355cae226b38' and
        value['parentDerivedDigestTableSha256'] == 'ab4199d3ec24d87e68754b6567ddc90bd1f8b41f046c8b5db719e5cac9c03dc3' and
        len(value['selectedWholeDerivedFiles']) == 7 and len(value['sections']) == 11 and
        all(value[key] is False for key in ('kernelRuntimeExecuted', 'physicalQueueQualified',
            'productionInstallation', 'completeAllocationClosure')), 'device-retirement-derived-origin')
    return value


def fixture():
    preimages()
    return prior.fixture()


def function(text, prefix):
    row = preimages()['sections'][prefix]
    require(text.count(prefix) == 1, 'device-retirement-function-occurrence')
    start = text.index(prefix)
    end = text.find('\n}\n', start)
    require(end >= 0, 'device-retirement-function-end')
    raw = text[start:end + 3]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'], 'device-retirement-function-preimage')
    return raw


SNAPSHOT = '''/* Caller holds the SAME pool_lock and has already validated its actual
 * constructor or returning child. Copy only original scalar identities before
 * final return/unlock; no replaceable cell or private address escapes here. */
static void lsf_factory_device_firmware_snapshot_locked(
    struct lsf_prepaid_key *owner, struct lsf_prepaid_ticket *pci)
{
    struct lsf_factory_device_firmware *owned;
    *owner = (struct lsf_prepaid_key){0};
    *pci = (struct lsf_prepaid_ticket){0};
    if (!factory.pages || !factory.device || !factory.device->firmware.slot)
        return;
    owned = lsf_factory_device_firmware_locked();
    if (!owned) {
        lsf_factory_device_firmware_poison();
        return;
    }
    *owner = factory.device->key;
    *pci = owned->pci;
}

'''
LOCALS = '    struct lsf_prepaid_key retirement_owner;\n    struct lsf_prepaid_ticket retirement_pci;\n'
CAPTURE = '    lsf_factory_device_firmware_snapshot_locked(&retirement_owner, &retirement_pci);\n'
RESUME = 'lsf_factory_device_firmware_schedule(retirement_owner, retirement_pci);'


def scheduler(text):
    raw = function(text, 'static void lsf_factory_device_firmware_schedule(void)\n')
    pending = '    if (lsf_factory_device_registration_pending_locked())\n        goto out;\n'
    queue = '    if (!lsf_device_queue(&factory.pool, factory.device->key,\n'
    dispatch = '    if (lsf_prepaid_acpi_queue_reference_put(work))\n'
    require(raw.count(pending) == raw.count(queue) == raw.count(dispatch) == 1 and
        raw.index(pending) < raw.index(queue) < raw.index('    spin_unlock_irqrestore(&pool_lock, flags);\n') <
        raw.index(dispatch), 'device-retirement-original-child-queue-fence')
    updated = replace(raw, 'static void lsf_factory_device_firmware_schedule(void)\n',
        'static void lsf_factory_device_firmware_schedule(\n'
        '    struct lsf_prepaid_key original_owner, struct lsf_prepaid_ticket original_pci)\n')
    updated = replace(updated, '    if (!factory.device || !factory.device->firmware.slot)\n',
        '    /* Stale final returns cannot target a later backing incarnation.\n'
        '     * This is only a wake, never a new admission or physical refund. */\n'
        '    if (!original_owner.generation || !original_pci.slot || !original_pci.generation ||\n'
        '        !factory.pages || !factory.device || !factory.device->firmware.slot ||\n'
        '        factory.device->key.slot != original_owner.slot ||\n'
        '        factory.device->key.generation != original_owner.generation)\n')
    updated = replace(updated, '    if (!owned)\n        goto poison;\n',
        '    if (!owned)\n        goto poison;\n'
        '    if (owned->pci.slot != original_pci.slot || owned->pci.generation != original_pci.generation)\n'
        '        goto out;\n')
    return replace(text, raw, SNAPSHOT + updated)


def caller(text, prefix, anchor, flags='    unsigned long flags;\n'):
    raw = function(text, prefix)
    updated = replace(raw, flags, flags + LOCALS)
    require(updated.count(anchor) == 1, 'device-retirement-validated-capture-anchor')
    updated = replace(updated, anchor, CAPTURE + anchor)
    updated = replace(updated, 'lsf_factory_device_firmware_schedule();', RESUME)
    return replace(text, raw, updated)


def old_callers(outputs):
    name = 'net/factory-device-firmware.c'
    text = scheduler(outputs[name].decode())
    text = caller(text, 'void lsf_factory_device_firmware_constructor_leave(void)\n',
        '    factory.device->constructor_active = 0;\n')
    text = caller(text, 'int lsf_factory_device_firmware_retire(const void *address)\n',
        '    owned->retirement = 1;\n')
    outputs[name] = text.encode()
    for name, prefix, anchor in [
        ('net/factory-device-core.c', 'void lsf_factory_device_core_tail_finish(const void *kobject)\n',
         '    owned->core_tail_active = 0;\n'),
        ('net/factory-device-sysfs.c', 'int lsf_factory_device_sysfs_release(struct lsf_device_registration_source source,\n',
         '    ticket = (struct lsf_prepaid_ticket){member.slot, member.generation};\n'),
        ('net/factory-device-uevent.c', 'int lsf_factory_device_uevent_return(const void *address, unsigned int kind)\n',
         '        ticket = (struct lsf_prepaid_ticket){source.slot, source.generation};\n')]:
        text = outputs[name].decode()
        if name.endswith('uevent.c'):
            # Preserve this actual lookup-success extent and its indentation.
            raw = function(text, prefix)
            updated = replace(raw, '    unsigned long flags;\n', '    unsigned long flags;\n' + LOCALS)
            updated = replace(updated, anchor, '    ' + CAPTURE + anchor)
            outputs[name] = replace(text, raw, replace(updated,
                'lsf_factory_device_firmware_schedule();', RESUME)).encode()
        else:
            outputs[name] = caller(text, prefix, anchor).encode()
    for name, prefix, check, finish in [
        ('net/factory-device-registration.c',
         'int lsf_factory_device_registration_return_finish(struct lsf_device_registration_source source)\n',
         '    if (!lsf_device_registration_kind(source.kind) ||\n'
         '        !lsf_factory_device_registration_record_locked(source, LSF_PREPAID_QUEUED) ||\n',
         '        !lsf_device_finish(&factory.pool, factory.device->key, ticket, source.kind))\n'),
        ('net/factory-device-recipient.c',
         'int lsf_factory_device_recipient_finish(struct lsf_device_registration_source source)\n',
         '    if (!lsf_factory_device_recipient_current_locked(source, NULL) ||\n',
         '        !lsf_device_queue(&factory.pool, factory.device->key, ticket, LSF_DEVICE_RECIPIENT_WORK) ||\n'
         '        !lsf_device_finish(&factory.pool, factory.device->key, ticket, LSF_DEVICE_RECIPIENT_WORK))\n')]:
        text = outputs[name].decode()
        raw = function(text, prefix)
        updated = replace(raw, '    unsigned long flags;\n', '    unsigned long flags;\n' + LOCALS)
        replacement = check[:-4] + ')\n        goto poison;\n' + CAPTURE + '    if (' + finish[8:]
        updated = replace(updated, check + finish, replacement)
        outputs[name] = replace(text, raw, replace(updated,
            'lsf_factory_device_firmware_schedule();', RESUME)).encode()
    name = 'net/factory-device-recipient.c'
    outputs[name] = caller(outputs[name].decode(),
        'static void lsf_factory_device_recipient_signal_callback(struct rcu_head *head)\n',
        '    ticket = (struct lsf_prepaid_ticket){source.slot, source.generation};\n',
        '    unsigned long flags, value = (unsigned long)head;\n').encode()


def security_final_returns(text):
    raw = function(text, 'int lsf_factory_blob_finish(struct lsf_factory_blob copy, unsigned int kind)\n')
    anchor = ('    if (copy.domain == LSF_FACTORY_OWNER_DEVICE) {\n'
        '        result = lsf_factory_device_security_finish_locked(copy, kind);\n'
        '        spin_unlock_irqrestore(&pool_lock, flags);\n        return result;\n    }\n')
    updated = replace(raw, anchor,
        '    if (copy.domain == LSF_FACTORY_OWNER_DEVICE) {\n'
        '        struct lsf_prepaid_key retirement_owner;\n'
        '        struct lsf_prepaid_ticket retirement_pci;\n'
        '        if (!lsf_factory_device_security_record_locked(copy)) {\n'
        '            lsf_factory_device_firmware_poison();\n'
        '            spin_unlock_irqrestore(&pool_lock, flags);\n            return 0;\n        }\n'
        '        lsf_factory_device_firmware_snapshot_locked(&retirement_owner, &retirement_pci);\n'
        '        result = lsf_factory_device_security_finish_locked(copy, kind);\n'
        '        spin_unlock_irqrestore(&pool_lock, flags);\n'
        '        if (result == 1)\n            ' + RESUME + '\n        return result;\n    }\n')
    text = replace(text, raw, updated)
    raw = function(text, 'int lsf_factory_sidcache_destroy(const void *address)\n')
    anchor = '    if (result == 1 && copy.domain == LSF_FACTORY_OWNER_DEVICE) {\n'
    updated = replace(raw, anchor, anchor +
        '        struct lsf_prepaid_key retirement_owner;\n'
        '        struct lsf_prepaid_ticket retirement_pci;\n'
        '        lsf_factory_device_firmware_snapshot_locked(&retirement_owner, &retirement_pci);\n')
    updated = replace(updated, '        spin_unlock_irqrestore(&pool_lock, flags);\n        return result;\n',
        '        spin_unlock_irqrestore(&pool_lock, flags);\n'
        '        if (result == 1)\n            ' + RESUME + '\n        return result;\n')
    return replace(text, raw, updated)


def transform(outputs):
    for name, row in preimages()['selectedWholeDerivedFiles'].items():
        require(name in outputs and len(outputs[name]) == row['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == row['sha256'],
            'device-retirement-whole-derived-preimage')
    outputs = dict(outputs)
    old_callers(outputs)
    name = 'net/factory.c'
    outputs[name] = security_final_returns(outputs[name].decode()).encode()
    require(all(b'lsf_factory_device_firmware_schedule();' not in raw
        for name, raw in outputs.items() if name.startswith('net/') and name.endswith('.c')),
        'device-retirement-unscoped-resume-remains')
    return outputs


def derive(inputs):
    authenticate(inputs)
    return transform(prior.derive(inputs))
