"""Real same-queue lifetime, finite birth and original physical retirement.

Source composition only; all runtime, geometry and consumer gates stay false.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_provider_retirement as prior
from tools import host_stream_kernel_cleanup_provider_initialize as initialize
from tools.host_stream_kernel_device_security import function

OWNED = prior.OWNED
require = prior.require
replace = prior.replace
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_cleanup_provider_queue.json'
FIXTURE_SHA = '90d662020c649d36c5b687dd2ca4a364e8360b8969cafb1c3cf586a7a82849ba'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 48 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-provider-queue-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-provider-queue-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 4 and len(value['sections']) == 3 and len(value['parentDerived']) == 15 and
        all(value[key] is False for key in ('taskCreated', 'queueLifetimeExecuted', 'actualRcuExecution',
            'physicalRetirementQualified', 'compiledGeometryFits', 'consumerSelected', 'productionInstallation')),
        'cleanup-provider-queue-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-provider-queue-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-provider-queue-whole-source')
        if 'gitBlob' in expected:
            require(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == expected['gitBlob'],
                'cleanup-provider-queue-upstream-blob')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-provider-queue-definition-preimage')


def parked_original_lifetime(text):
    text = replace(text, '    LSF_PROVIDER_QUEUE_EMPTY, LSF_PROVIDER_QUEUE_PARKING,\n',
        '    LSF_PROVIDER_QUEUE_EMPTY, LSF_PROVIDER_QUEUE_PREPARING, LSF_PROVIDER_QUEUE_PARKING,\n')
    text = replace(text, '    struct kthread_work handoff;\n    struct completion prepared;\n',
        '    struct kthread_work handoff, retire, release_barrier;\n'
        '    struct completion prepared, unlinked_released;\n'
        '    atomic_t retire_pending;\n    unsigned int preparing;\n')
    text = replace(text, '        INIT_LIST_HEAD(&original->pwqs_node);\n',
        '        INIT_LIST_HEAD(&original->pwqs_node);\n'
        '        original->plugged = true;\n'
        '        /* Keep the REAL original-provider PWQ borrow linked behind\n'
        '         * private. Original destroy_workqueue cannot RCU-free wq\n'
        '         * until this borrowed original PWQ actually releases. */\n'
        '        link_pwq(original);\n')
    text = replace(text, '    if (control->phase != LSF_PROVIDER_QUEUE_EMPTY || !original ||\n',
        '    if (control->phase != LSF_PROVIDER_QUEUE_PREPARING || !original ||\n')
    text = replace(text,
        '    if (!lsf_provider_pwq_quiescent_locked(original) || !list_empty(&original->pwqs_node) ||\n'
        '        !lsf_provider_slots_are(wq, control->private)) {\n',
        '    if (!lsf_provider_pwq_quiescent_locked(original) ||\n'
        '        !lsf_provider_slots_are(wq, control->private) ||\n'
        '        wq->pwqs.next != &control->private->pwqs_node ||\n'
        '        control->private->pwqs_node.next != &original->pwqs_node ||\n'
        '        original->pwqs_node.next != &wq->pwqs) {\n')
    text = replace(text,
        '    return phase == LSF_PROVIDER_QUEUE_PARKING || phase == LSF_PROVIDER_QUEUE_PARKED_RCU ||\n',
        '    return phase == LSF_PROVIDER_QUEUE_PREPARING || phase == LSF_PROVIDER_QUEUE_PARKING ||\n'
        '        phase == LSF_PROVIDER_QUEUE_PARKED_RCU ||\n')
    old = function(text, 'void lsf_prepaid_cleanup_provider_pwq_drop(')
    new = '''void lsf_prepaid_cleanup_provider_pwq_drop(void *address)
{
    struct lsf_cleanup_provider_control *control;
    struct pool_workqueue *pwq = address;
    control = lsf_factory_cleanup_provider_control_get(NULL);
    if (!control)
        return;
    if (READ_ONCE(control->phase) == LSF_PROVIDER_QUEUE_PARKING &&
        READ_ONCE(control->original) == pwq) {
        lockdep_assert_held(&pwq->pool->lock);
        if (pwq->refcnt == 2)
            kthread_queue_work(pwq_release_worker, &control->handoff);
    }
    lsf_factory_cleanup_provider_control_put(control);
}
'''
    text = replace(text, old, new)
    old = function(text, 'int lsf_prepaid_cleanup_provider_attributes_bound(')
    new = '''int lsf_prepaid_cleanup_provider_attributes_bound(struct workqueue_struct *candidate)
{
    struct lsf_cleanup_provider_control *control;
    unsigned int phase;
    int bound = 0;
    control = lsf_factory_cleanup_provider_control_get(NULL);
    if (!control)
        return 0;
    if (READ_ONCE(control->wq) == candidate) {
        phase = READ_ONCE(control->phase);
        bound = phase == LSF_PROVIDER_QUEUE_PREPARING || phase == LSF_PROVIDER_QUEUE_PARKING ||
            phase == LSF_PROVIDER_QUEUE_PARKED_RCU || phase == LSF_PROVIDER_QUEUE_LIVE ||
            phase == LSF_PROVIDER_QUEUE_RETURNING;
    }
    lsf_factory_cleanup_provider_control_put(control);
    return bound;
}
'''
    text = replace(text, old, new)
    old = function(text, 'static int lsf_provider_worker_entry(')
    new = replace(old, '    return 0;\n',
        '    if (READ_ONCE(((struct worker *)worker)->task) != current ||\n'
        '        READ_ONCE(((struct worker *)worker)->pool) != pool) {\n'
        '        lsf_factory_cleanup_provider_hold(source);\n        return -EIO;\n    }\n'
        '    return 0;\n')
    text = replace(text, old, new)
    old = initialize.worker_create()
    new = replace(old, '    struct worker_pool *pool, struct worker *paid)\n',
        '    struct worker_pool *pool, struct worker *paid, int *birth_error)\n')
    new = replace(new, '\tint id;\n', '\tint id;\n\t*birth_error = -EOPNOTSUPP;\n')
    new = replace(new, '\tif (id < 0) {\n', '\tif (id < 0) {\n\t\t*birth_error = id;\n')
    new = replace(new, '\tworker = lsf_provider_alloc_worker(source, pool, paid);\n',
        '\t*birth_error = -ENOMEM;\n\tworker = lsf_provider_alloc_worker(source, pool, paid);\n')
    new = replace(new, '\t\tif (IS_ERR(worker->task)) {\n',
        '\t\tif (IS_ERR(worker->task)) {\n\t\t\t*birth_error = PTR_ERR(worker->task);\n')
    new = replace(new, '\t\t\tlsf_factory_cleanup_provider_hold(source);\n',
        '\t\t\t*birth_error = -EIO;\n\t\t\tlsf_factory_cleanup_provider_hold(source);\n')
    new = replace(new, '\treturn worker;\n', '\t*birth_error = 0;\n\treturn worker;\n')
    new = replace(new, '\tlsf_factory_cleanup_provider_hold(source);\n\treturn NULL;\n',
        '\treturn NULL;\n')
    return replace(text, old, new)


def pending_task(text):
    text = replace(text, '    WRITE_ONCE(lsf_cleanup_pending, owned);\n',
        '    if (!lsf_factory_cleanup_provider_submit(source, worker)) {\n'
        '        spin_unlock(&kthread_create_lock);\n        return ERR_PTR(-EOPNOTSUPP);\n    }\n'
        '    WRITE_ONCE(lsf_cleanup_pending, owned);\n')
    text = replace(text, '        if (xchg(&owned->create.done, NULL)) {\n',
        '        if (xchg(&owned->create.done, NULL)) {\n'
        '            lsf_factory_cleanup_provider_task_failed(source);\n')
    text = replace(text, '    task = owned->create.result;\n',
        '    task = owned->create.result;\n'
        '    if (IS_ERR(task))\n        lsf_factory_cleanup_provider_task_failed(source);\n')
    return text


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-provider-queue-parent-preimage')
    outputs = dict(outputs)
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    text = outputs[name].decode()
    text = replace(text, '#include <net/lsf_stream_cleanup_provider_operation.h>\n',
        '#include <net/lsf_stream_cleanup_provider_operation.h>\n'
        '#include <net/lsf_stream_device_firmware.h>\n#include <linux/gfp_types.h>\n')
    declarations = '''unsigned long lsf_prepaid_acpi_provider_bootstrap_bytes(void);
int lsf_prepaid_acpi_provider_queue_acquire(void *, struct workqueue_struct **);
int lsf_prepaid_acpi_provider_queue_lock(void *);
void lsf_prepaid_acpi_provider_queue_unlock(void);
void lsf_prepaid_acpi_provider_queue_unregister(void *);
void lsf_prepaid_cleanup_provider_queue_terminate(void *);
int lsf_prepaid_cleanup_provider_queue_available(void);
int lsf_prepaid_cleanup_provider_queue_prepare(struct lsf_cleanup_task_source, struct lsf_cleanup_provider_storage *);
void lsf_prepaid_cleanup_provider_queue_detached(const void *);
void lsf_prepaid_cleanup_provider_retirement_kick(void);
int lsf_prepaid_cleanup_provider_retirement_kick_held(void *);
int lsf_prepaid_cleanup_provider_create_full(void);
int lsf_prepaid_cleanup_provider_destroy_full(void);
int lsf_factory_cleanup_provider_submit(struct lsf_cleanup_task_source, const void *);
void lsf_factory_cleanup_provider_task_failed(struct lsf_cleanup_task_source);
int lsf_factory_cleanup_provider_cancel_unsubmitted(struct lsf_cleanup_task_source);
int lsf_factory_cleanup_provider_unused_worker_finish(struct lsf_cleanup_task_source);
int lsf_factory_cleanup_provider_core_retired(struct lsf_cleanup_task_source);
int lsf_factory_cleanup_provider_request_close(void);
void lsf_factory_cleanup_provider_queue_closed(void);
int lsf_factory_cleanup_provider_close_ready(struct lsf_cleanup_task_source);
int lsf_factory_cleanup_provider_profile_ready(void);
void *lsf_factory_cleanup_provider_control_get(const void *);
void lsf_factory_cleanup_provider_control_put(const void *);
int lsf_factory_cleanup_provider_control_seal(struct lsf_cleanup_task_source, const void *);
int lsf_prepaid_cleanup_provider_irq_abort_opener_locked(struct lsf_cleanup_task_source, struct task_struct *);
'''
    outputs[name] = replace(text, '#endif\n', declarations+'#endif\n').encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(), '    unsigned int cleanup_provider_pool_destructed;\n',
        '    unsigned int cleanup_provider_pool_destructed;\n'
        '    unsigned int cleanup_provider_submitted, cleanup_provider_task_failed, cleanup_provider_close_requested;\n'
        '    unsigned int cleanup_provider_control_readers, cleanup_provider_control_retiring;\n').encode()
    name = 'net/factory.c'
    outputs[name] = replace(outputs[name].decode(), '#include "factory-cleanup-provider-retirement.c"\n',
        '#include "factory-cleanup-provider-retirement.c"\n#include "factory-cleanup-provider-queue.c"\n').encode()
    name = 'net/factory-cleanup-provider-initialize.c'
    outputs[name] = replace(outputs[name].decode(),
        '        factory.device->cleanup_task_claimed ||\n',
        '        factory.device->cleanup_task_claimed || factory.device->cleanup_provider_submitted ||\n').encode()
    name = 'net/factory-cleanup-provider-retirement.c'
    text = outputs[name].decode()
    text = replace(text, '    record = lsf_provider_part_record_locked(source, part, address);\n'
        '    if (!record || !lsf_provider_part_queue_locked(source, record))\n',
        '    record = lsf_provider_part_record_locked(source, part, address);\n'
        '    if (part == LSF_PROVIDER_CONTROL &&\n'
        '        (!factory.device->cleanup_provider_control_retiring || factory.device->cleanup_provider_control_readers))\n'
        '        goto poison;\n'
        '    if (!record || !lsf_provider_part_queue_locked(source, record))\n')
    # Both real physical callback completion paths notify outside pool_lock.
    require(text.count('    if (result)\n        wake_up_process(kthreadd_task);\n') == 2,
        'cleanup-provider-queue-two-actual-physical-notifications')
    outputs[name] = text.replace('    if (result)\n        wake_up_process(kthreadd_task);\n',
        '    if (result) {\n        wake_up_process(kthreadd_task);\n'
        '        lsf_prepaid_cleanup_provider_retirement_kick();\n    }\n').encode()
    name = 'net/factory-cleanup-descendants.c'
    text = outputs[name].decode()
    old = function(text, 'void lsf_factory_cleanup_final_drain(')
    outputs[name] = replace(text, old, replace(old, '    spin_unlock_irqrestore(&pool_lock, flags);\n',
        '    spin_unlock_irqrestore(&pool_lock, flags);\n'
        '    lsf_prepaid_cleanup_provider_retirement_kick();\n')).encode()
    name = 'net/factory-cleanup-constructor.c'
    text = outputs[name].decode()
    old = function(text, 'void lsf_factory_cleanup_abort_drain(')
    outputs[name] = replace(text, old, replace(old, '    spin_unlock_irqrestore(&pool_lock, flags);\n',
        '    spin_unlock_irqrestore(&pool_lock, flags);\n'
        '    lsf_prepaid_cleanup_provider_retirement_kick();\n')).encode()
    name = 'net/factory-device-firmware.c'
    outputs[name] = replace(outputs[name].decode(),
        '    if (finished)\n        (void)lsf_factory_device_pci_return(pci);\n',
        '    if (finished) {\n        (void)lsf_factory_device_pci_return(pci);\n'
        '        lsf_prepaid_cleanup_provider_retirement_kick();\n    }\n').encode()
    name = 'net/factory-cleanup-observer.c'
    text = replace(outputs[name].decode(), '        LSF_BACKING_BYTES + 2u * sizeof(void *);\n',
        '        LSF_BACKING_BYTES + 2u * sizeof(void *) + lsf_prepaid_acpi_provider_bootstrap_bytes();\n')
    outputs[name] = text.encode()
    name = 'kernel/lsf-cleanup-close.c'
    outputs[name] = replace(outputs[name].decode(), '    struct task_struct *task;\n',
        '    struct task_struct *task;\n'
        '    if (lsf_prepaid_cleanup_provider_destroy_full())\n        return;\n').encode()
    name = 'kernel/lsf-cleanup-provider-initialize.c'
    outputs[name] = pending_task(outputs[name].decode()).encode()
    name = 'kernel/kthread.c'
    outputs[name] = replace(outputs[name].decode(), '#include "lsf-cleanup-provider-initialize.c"\n',
        '#include "lsf-cleanup-provider-initialize.c"\n#include "lsf-cleanup-provider-queue.c"\n').encode()
    name = 'kernel/lsf-cleanup-provider-executor.c'
    outputs[name] = (parked_original_lifetime(outputs[name].decode())+'\n'+
        (OWNED/'workqueue-cleanup-provider-queue.c').read_text()).encode()
    name = 'kernel/workqueue.c'
    text = outputs[name].decode()
    # At this point the private PWQ was actually unlinked and unplugged its
    # original successor. Seal Control's WQ read before original pool/RCU tail.
    old = function(text, 'static void pwq_release_workfn(struct kthread_work *work)\n')
    new = replace(old, '\n\tif (wq->flags & WQ_UNBOUND) {\n',
        '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (owned)\n\t\tlsf_prepaid_cleanup_provider_queue_detached(pwq);\n#endif\n'
        '\tif (wq->flags & WQ_UNBOUND) {\n')
    outputs[name] = replace(text, old, new).encode()
    name = 'drivers/acpi/osl.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_device_firmware.h>\n',
        '#include <net/lsf_stream_device_firmware.h>\n'
        '#include <net/lsf_stream_cleanup_provider_executor.h>\n')
    text = replace(text, '#include "../../net/acpi-cleanup-provider-executor.c"\n',
        '#include "../../net/acpi-cleanup-provider-executor.c"\n'
        '#include "../../net/acpi-cleanup-provider-queue.c"\n')
    outputs[name] = replace(text, '\tlsf_prepaid_acpi_reference_queue_state(false);\n',
        '\tlsf_prepaid_acpi_provider_terminate();\n').encode()
    outputs['net/factory-cleanup-provider-queue.c'] = (OWNED/'factory-cleanup-provider-queue.c').read_bytes()
    outputs['kernel/lsf-cleanup-provider-queue.c'] = (OWNED/'kthread-cleanup-provider-queue.c').read_bytes()
    outputs['net/acpi-cleanup-provider-queue.c'] = (OWNED/'acpi-cleanup-provider-queue.c').read_bytes()
    return outputs
