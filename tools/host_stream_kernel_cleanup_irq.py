"""Uninstalled single-birth local IRQ relay for final private stack release.

This source layer supplies no real task/IRQ/hotplug/bootstrap qualification.
The ordinary allocator and actual maintained IRQ primitive bodies stay exact.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_entry as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_irq.json'
FIXTURE_SHA = '7ad5bc0ebbb9aafabcbd2e50b741b1264e865d91c9928f9d82ecbf22d28eaa88'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 16 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-irq-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-irq-source.v1' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        value['archiveSha256'] == 'e09b6727e5c521253f0d41694900b9c38fb7604db7d35238a8197aa9f7de2428' and
        len(value['source']) == 5 and len(value['sections']) == 8 and
        len(value['parentDerived']) == 5 and value['irqHandoffSourceImplemented'] is True and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'actualNmiExecution', 'cpuHotplugQualified', 'irqBootstrapOwnerQualified',
            'completeAllocationClosure', 'productionInstallation')),
        'cleanup-irq-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-irq-whole-membership')
    for name, row in value['source'].items():
        require(type(inputs[name]) is bytes and len(inputs[name]) == row['bytes'] and
            hashlib.sha256(inputs[name]).hexdigest() == row['sha256'], 'cleanup-irq-whole-source')
    for row in value['sections'].values():
        raw = row['text'].encode()
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'] and
            inputs[row['source']].decode().count(row['text']) == 1,
            'cleanup-irq-definition-preimage')


PROTOTYPES = '''unsigned long lsf_prepaid_cleanup_irq_bootstrap_bytes(void);
int lsf_factory_cleanup_irq_hint(struct lsf_cleanup_task_source, struct task_struct *,
    unsigned long, void **, unsigned long *);
int lsf_factory_cleanup_irq_published(struct lsf_cleanup_task_source, struct task_struct *);
int lsf_prepaid_cleanup_irq_prepare(struct lsf_cleanup_task_source, struct task_struct *);
int lsf_prepaid_cleanup_irq_arm(struct lsf_cleanup_task_source, struct task_struct *);
int lsf_prepaid_cleanup_stack_capture_deferred(struct task_struct *);
int lsf_prepaid_cleanup_irq_pending(void);
void lsf_prepaid_cleanup_irq_drain(void);
'''


def transform(outputs, inputs):
    authenticate(inputs)
    for name, row in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == row['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == row['sha256'],
            'cleanup-irq-parent-preimage')
    outputs = dict(outputs)
    name = 'include/net/lsf_stream_cleanup_lifecycle.h'
    outputs[name] = replace(outputs[name].decode(), 'void lsf_prepaid_cleanup_retire_one(void);\n',
        'void lsf_prepaid_cleanup_retire_one(void);\n' + PROTOTYPES).encode()
    name = 'kernel/lsf-cleanup-worker.c'
    outputs[name] = replace(outputs[name].decode(), '    struct kthread_worker worker;\n',
        '    struct kthread_worker worker;\n    struct irq_work retire_irq;\n').encode()
    name = 'mm/lsf-cleanup-stack-retire.c'
    text = outputs[name].decode()
    require(text.count('int lsf_prepaid_cleanup_stack_release(struct task_struct *task)\n') == 2,
        'cleanup-irq-both-stack-profiles')
    text = text.replace('int lsf_prepaid_cleanup_stack_release(struct task_struct *task)\n',
        'int lsf_prepaid_cleanup_stack_capture_deferred(struct task_struct *task)\n')
    text = replace(text, '    if (valid && lsf_factory_cleanup_task_publish(source, task))\n',
        '    if (valid && !lsf_prepaid_cleanup_irq_prepare(source, task) &&\n'
        '        lsf_factory_cleanup_task_publish(source, task) &&\n'
        '        !lsf_prepaid_cleanup_irq_arm(source, task))\n')
    outputs[name] = text.encode()
    name = 'kernel/kthread.c'
    text = replace(outputs[name].decode(), '#include <linux/kthread.h>\n',
        '#include <linux/kthread.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <linux/irq_work.h>\n#endif\n')
    text = replace(text, '\t\t    && !lsf_factory_cleanup_retire_pending()\n',
        '\t\t    && !lsf_factory_cleanup_retire_pending()\n'
        '\t\t    && !lsf_prepaid_cleanup_irq_pending()\n')
    text = replace(text, '\t\t       || lsf_cleanup_pending || lsf_factory_cleanup_retire_pending()\n',
        '\t\t       || lsf_cleanup_pending || lsf_factory_cleanup_retire_pending()\n'
        '\t\t       || lsf_prepaid_cleanup_irq_pending()\n')
    text = replace(text, '\t\t\tif (lsf_factory_cleanup_retire_pending()) {\n',
        '\t\t\tif (lsf_prepaid_cleanup_irq_pending()) {\n'
        '\t\t\t\tspin_unlock(&kthread_create_lock);\n'
        '\t\t\t\tlsf_prepaid_cleanup_irq_drain();\n'
        '\t\t\t\tspin_lock(&kthread_create_lock);\n'
        '\t\t\t\tcontinue;\n\t\t\t}\n'
        '\t\t\tif (lsf_factory_cleanup_retire_pending()) {\n')
    outputs[name] = replace(text, '#include "lsf-cleanup-entry.c"\n',
        '#include "lsf-cleanup-entry.c"\n#include "lsf-cleanup-irq.c"\n').encode()
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include "factory-cleanup-entry.c"\n',
        '#include "factory-cleanup-entry.c"\n#include "factory-cleanup-irq.c"\n')
    # The old constant assertion still proves this subtraction cannot wrap.
    # Check the actual extra TU sizeof BEFORE refs/locks/tap reserve/pages.
    outputs[name] = replace(text,
        '    if (!lsf_factory_selected_consumer())\n        return error;\n',
        '    if (!lsf_factory_selected_consumer())\n        return error;\n'
        '    if (lsf_prepaid_cleanup_irq_bootstrap_bytes() >\n'
        '        LSF_BOOTSTRAP_CEILING - sizeof(factory) - sizeof(lsf_device_uevent_taps) -\n'
        '            LSF_BACKING_BYTES - 2u * sizeof(void *))\n'
        '        return -EOPNOTSUPP;\n').encode()
    outputs['kernel/lsf-cleanup-irq.c'] = (OWNED / 'kernel-cleanup-irq.c').read_bytes()
    outputs['net/factory-cleanup-irq.c'] = (OWNED / 'factory-cleanup-irq.c').read_bytes()
    return outputs


def derive(inputs):
    extras = set(preimages()['source'])
    # These newly authenticated IRQ/SMP originals are provenance inputs only:
    # no ordinary body is rewritten or replaced by a private implementation.
    return transform(prior.derive({name: raw for name, raw in inputs.items() if name not in extras}),
        {name: inputs[name] for name in extras})
