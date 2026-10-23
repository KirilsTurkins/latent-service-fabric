"""Retained paid pending constructor and cancellable queue-readiness wait.

Initial kthreadd birth remains temporally unqualified. No consumer is selected.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_exit_observer as prior
from tools.host_stream_kernel_device_security import function

OWNED = prior.OWNED
require = prior.require
replace = prior.replace
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_cleanup_constructor_wait.json'
FIXTURE_SHA = '03dcdeb090255a915b7b1f0a4cebf07c4a9e5185454856ec10ab54c718578073'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 8192 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-constructor-wait-fixed-parent')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-constructor-wait-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        not value['source'] and len(value['parentDerived']) == 7 and
        all(value[key] is False for key in ('actualLinuxExecution', 'initialBirthBounded',
            'consumerSelected', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-constructor-wait-source-only')
    return value


def handoff(text):
    old = function(text, 'static void lsf_provider_park_handoff(')
    new = replace(old, '    if (!control)\n        return;\n',
        '    if (!control)\n        return;\n'
        '    if (!lsf_prepaid_acpi_provider_queue_lock(control)) {\n'
        '        lsf_factory_cleanup_provider_hold(control->source);\n        return;\n    }\n')
    new = replace(new, 'out_pool:\n    mutex_unlock(&wq_pool_mutex);\n',
        'out_pool:\n    mutex_unlock(&wq_pool_mutex);\n'
        '    /* The original registration retains WQ lifetime between begin\n'
        '     * and this actual two-grace callback. No mutex changes owner. */\n'
        '    if (control->phase == LSF_PROVIDER_QUEUE_PARKED_RCU) {\n'
        '        WRITE_ONCE(control->constructor_quarantined, 1);\n'
        '        lsf_factory_cleanup_provider_hold(control->source);\n    }\n'
        '    lsf_prepaid_acpi_provider_queue_unlock();\n'
        '    lsf_prepaid_acpi_provider_queue_changed();\n'
        '    lsf_prepaid_cleanup_provider_retirement_kick();\n')
    return replace(text, old, new)


def prepare(text):
    old = function(text, 'int lsf_prepaid_cleanup_provider_queue_prepare(')
    new = replace(old, '    control->preparing = 1;\n',
        '    control->preparing = 1;\n'
        '    control->failed_unlinked = control->constructor_quarantined = 0;\n'
        '    control->constructor_expires = expires;\n    init_completion(&control->born);\n')
    new = replace(new, '    struct lsf_cleanup_provider_storage *storage)\n',
        '    struct lsf_cleanup_provider_storage *storage, unsigned long expires)\n')
    new = replace(new, '    if (error == -EIO || error == -EBUSY) {\n',
        '    if (error == -EIO || error == -EBUSY || READ_ONCE(control->constructor_quarantined)) {\n')
    begin = new.index('    wait_for_completion(&control->prepared);')
    end = new.index('failed:\n', begin)
    new = replace(new, new[begin:end],
        '    /* Actual old callbacks and both RCU stages may still be pending.\n'
        '     * The registration borrow retains real WQ/Control lifetime; this\n'
        '     * SAME caller releases its mutex and returns explicit pending. */\n'
        '    WRITE_ONCE(control->preparing, 0);\n'
        '    lsf_prepaid_acpi_provider_queue_unlock();\n'
        '    lsf_prepaid_acpi_provider_queue_changed();\n'
        '    lsf_prepaid_cleanup_provider_retirement_kick();\n'
        '    return -EINPROGRESS;\n')
    new = replace(new,
        '        if (acquired) {\n'
        '            lsf_prepaid_acpi_provider_queue_unregister(control);\n'
        '            lsf_prepaid_acpi_provider_queue_unlock();\n        }\n',
        '        if (acquired) {\n'
        '            if (initialized_pwq)\n'
        '                WRITE_ONCE(control->constructor_quarantined, 1);\n'
        '            else\n'
        '                lsf_prepaid_acpi_provider_queue_unregister(control);\n'
        '            lsf_prepaid_acpi_provider_queue_unlock();\n'
        '            lsf_prepaid_acpi_provider_queue_changed();\n        }\n')
    new = replace(new, '    if (initialized_pwq) {\n        put_pwq_unlocked(private);\n',
        '    if (initialized_pwq) {\n        WRITE_ONCE(control->failed_unlinked, 1);\n'
        '        put_pwq_unlocked(private);\n')
    new = replace(new, '        wait_for_completion(&control->unlinked_released);\n',
        '        /* The paid registration remains until this real callback\n'
        '         * barrier returns. Neither caller nor terminator invents an\n'
        '         * unlinked-PWQ final-free acknowledgement. */\n')
    new = replace(new, '    if (acquired) {\n'
        '        lsf_prepaid_acpi_provider_queue_unregister(control);\n',
        '    if (acquired) {\n        if (!initialized_pwq)\n'
        '            lsf_prepaid_acpi_provider_queue_unregister(control);\n')
    new = replace(new, '    WRITE_ONCE(control->preparing, 0);\n'
        '    lsf_prepaid_cleanup_provider_retirement_kick();\n    return error;\n',
        '    WRITE_ONCE(control->preparing, 0);\n'
        '    lsf_prepaid_acpi_provider_queue_changed();\n'
        '    lsf_prepaid_cleanup_provider_retirement_kick();\n    return error;\n')
    return replace(text, old, new)


def executor(text):
    text = replace(text, '    unsigned int preparing;\n',
        '    unsigned int preparing, failed_unlinked, constructor_quarantined;\n'
        '    struct completion born;\n    unsigned long constructor_expires;\n')
    text = handoff(prepare(text))
    old = function(text, 'static void lsf_provider_unlinked_barrier(')
    new = replace(old, '    if (control)\n'
        '        complete_all(&control->unlinked_released); /* LAST Control field access. */\n',
        '    if (control) {\n'
        '        complete_all(&control->unlinked_released); /* LAST Control field access. */\n'
        '        lsf_prepaid_acpi_provider_queue_changed();\n'
        '        lsf_prepaid_cleanup_provider_retirement_kick();\n    }\n')
    text = replace(text, old, new)
    old = function(text, 'static void lsf_provider_retire_handoff(struct kthread_work *work)\n')
    new = replace(old, '    if (control->phase != LSF_PROVIDER_QUEUE_RETURNING || control->original_reference ||\n',
        '    if (control->phase == LSF_PROVIDER_QUEUE_RETURNING &&\n'
        '        READ_ONCE(control->failed_unlinked) && completion_done(&control->unlinked_released) &&\n'
        '        lsf_prepaid_acpi_provider_queue_lock(control)) {\n'
        '        lsf_prepaid_acpi_provider_queue_unregister(control);\n'
        '        lsf_prepaid_acpi_provider_queue_unlock();\n'
        '        lsf_prepaid_acpi_provider_queue_changed();\n    }\n'
        '    if (control->phase != LSF_PROVIDER_QUEUE_RETURNING || control->original_reference ||\n')
    text = replace(text, old, new)
    return text+'\n'+(OWNED/'workqueue-cleanup-provider-constructor.c').read_text()


def acpi(text):
    text = replace(text, 'static void *lsf_acpi_provider_registration;\n',
        'static void *lsf_acpi_provider_registration;\n'
        'static DECLARE_WAIT_QUEUE_HEAD(lsf_acpi_provider_constructor_wait);\n')
    text = replace(text, '        sizeof(lsf_acpi_reference_queue_lock) + sizeof(lsf_acpi_reference_queue_live);\n',
        '        sizeof(lsf_acpi_reference_queue_lock) + sizeof(lsf_acpi_reference_queue_live) +\n'
        '        sizeof(lsf_acpi_provider_constructor_wait);\n')
    owned = (OWNED/'acpi-cleanup-provider-constructor.c').read_text()
    owned = replace(owned, 'static DECLARE_WAIT_QUEUE_HEAD(lsf_acpi_provider_constructor_wait);\n', '')
    return replace(text, function(text, 'static void lsf_prepaid_acpi_provider_terminate('), owned)


def transform(outputs, inputs):
    require(not inputs, 'cleanup-constructor-wait-no-new-upstream')
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-constructor-wait-parent-preimage')
    outputs = dict(outputs)
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    text = replace(outputs[name].decode(), '#include <linux/gfp_types.h>\n',
        '#include <linux/gfp_types.h>\n#include <linux/jiffies.h>\n#include <linux/wait.h>\n')
    outputs[name] = replace(text, '#endif\n',
        'struct completion;\n'
        'void lsf_prepaid_acpi_provider_queue_changed(void);\n'
        'int lsf_prepaid_cleanup_provider_queue_pending(void *);\n'
        'int lsf_prepaid_cleanup_provider_wait_ready(unsigned long);\n'
        'int lsf_factory_cleanup_provider_waiter_current(struct lsf_cleanup_task_source);\n'
        'void lsf_factory_cleanup_provider_waiter_cancel(struct lsf_cleanup_task_source);\n'
        'void *lsf_prepaid_cleanup_provider_birth_wait_get(struct lsf_cleanup_task_source, const void *,\n'
        '    struct completion **, unsigned long *);\n'
        'void lsf_prepaid_cleanup_provider_birth_wait_put(void *, int);\n'
        'unsigned long lsf_prepaid_cleanup_provider_birth_remaining(void *);\n#endif\n').encode()
    text = outputs[name].decode()
    text = replace(text, 'int lsf_prepaid_cleanup_provider_create_full(void);\n',
        'int lsf_prepaid_cleanup_provider_create_full(unsigned long);\n')
    outputs[name] = replace(text,
        'int lsf_prepaid_cleanup_provider_queue_prepare(struct lsf_cleanup_task_source, struct lsf_cleanup_provider_storage *);\n',
        'int lsf_prepaid_cleanup_provider_queue_prepare(struct lsf_cleanup_task_source,\n'
        '    struct lsf_cleanup_provider_storage *, unsigned long);\n').encode()
    name = 'net/factory.c'
    text = outputs[name].decode()
    old = function(text, 'static int lsf_factory_open(')
    require(old.index('    factory.opened = 1;\n') < old.index('lsf_prepaid_cleanup_worker_create();'),
        'cleanup-constructor-wait-original-open-publication')
    new = replace(old, '    error = lsf_prepaid_cleanup_worker_create();\n',
        '    /* opened and original mm/tgid/cred/net borrows are published.\n'
        '     * Another open observes opened and cannot enter/reuse this bank.\n'
        '     * Failed construction retains that state until actual retirement. */\n'
        '    mutex_unlock(&factory_lock);\n'
        '    error = lsf_prepaid_cleanup_worker_create();\n'
        '    mutex_lock(&factory_lock);\n')
    outputs[name] = replace(text, old, new).encode()
    name = 'net/factory-cleanup-provider-queue.c'
    outputs[name] += b'\n'+(OWNED/'factory-cleanup-provider-constructor.c').read_bytes()
    name = 'net/acpi-cleanup-provider-queue.c'
    outputs[name] = acpi(outputs[name].decode()).encode()
    name = 'kernel/lsf-cleanup-provider-executor.c'
    outputs[name] = executor(outputs[name].decode()).encode()
    # The full API now returns explicit pending, never a false ready witness.
    name = 'kernel/lsf-cleanup-provider-queue.c'
    text = outputs[name].decode()
    text = replace(text, 'int lsf_prepaid_cleanup_provider_create_full(void)\n',
        'int lsf_prepaid_cleanup_provider_create_full(unsigned long remaining)\n')
    text = replace(text, '    int error;\n',
        '    int error;\n    unsigned long expires;\n'
        '    if (remaining > MAX_JIFFY_OFFSET)\n        return -EINVAL;\n'
        '    if (!remaining)\n        return -ETIMEDOUT;\n'
        '    expires = jiffies + remaining; /* Fixed once BEFORE any new birth. */\n')
    text = replace(text, 'lsf_prepaid_cleanup_provider_queue_prepare(source, &storage)',
        'lsf_prepaid_cleanup_provider_queue_prepare(source, &storage, expires)')
    outputs[name] = replace(text, '    /* WQ initializes the exact six paid parts, registers actual ACPI lifetime,\n'
        '     * constructs the authenticated Task, and performs same-queue parking. */\n',
        '    /* WQ initializes the exact six paid parts and authentic Task.\n'
        '     * -EINPROGRESS means original-queue parking remains retained,\n'
        '     * not ready; use the explicit finite wait outside factory_lock. */\n').encode()
    name = 'kernel/lsf-cleanup-provider-initialize.c'
    outputs[name] = replace(outputs[name].decode(),
        function(outputs[name].decode(), 'struct task_struct *lsf_prepaid_cleanup_provider_task_create('),
        (OWNED/'kthread-cleanup-provider-constructor.c').read_text()).encode()
    return outputs
