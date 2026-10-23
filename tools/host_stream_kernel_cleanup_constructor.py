"""Uninstalled full maintained fork body and actual publication/abort boundaries.

The real remaining LSM/perf/audit/hook allocation graphs remain open.
This function is deliberately not called by the still-refusing creator until
those actual routes and original bootstrap/geometry owners are complete.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_pid as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_constructor.json'
FIXTURE_SHA = 'b6e24094bf9d391ab4ac9e68caa30ecb98d944856f650331f454013c6ff0b4e2'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 192 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-constructor-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-constructor-source.v1' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        value['archiveSha256'] == 'e09b6727e5c521253f0d41694900b9c38fb7604db7d35238a8197aa9f7de2428' and
        len(value['source']) == 9 and len(value['sections']) == 21 and len(value['parentDerived']) == 15 and
        all(value[name] is False for name in ('taskCreated', 'executorReady', 'creatorCallsFullConstructor',
            'taskLsmAllocationClosure', 'perfInheritanceClosure', 'enabledAuditClosure',
            'numaPolicyClosure', 'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-constructor-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-constructor-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-constructor-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-constructor-definition-preimage')


def definition(name):
    return preimages()['sections'][name]['text']


ABORT_STACK = '''int lsf_prepaid_cleanup_constructor_abort_stack(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    struct lsf_cleanup_task_source actual;
    void *address;
    if (current != kthreadd_task || in_interrupt() || irqs_disabled() ||
        lsf_factory_cleanup_lifecycle_source(task, &actual, &address) != 1 || !address ||
        actual.owner.slot != source.owner.slot || actual.owner.generation != source.owner.generation ||
        actual.root.slot != source.root.slot || actual.root.generation != source.root.generation ||
        actual.request.slot != source.request.slot || actual.request.generation != source.request.generation ||
        actual.task.slot != source.task.slot || actual.task.generation != source.task.generation ||
        refcount_read(&task->usage) != 1 || refcount_read(&task->stack_refcount) != 1 ||
        READ_ONCE(task->__state) != TASK_DEAD)
        goto poison;
    /* This actual stack was never visible and has no external reader. Consume
     * the original reference exactly once; never enter the published IRQ hook. */
    if (!refcount_dec_and_test(&task->stack_refcount) ||
        lsf_prepaid_cleanup_stack_abort_unpublished(source, task) ||
        !lsf_factory_cleanup_abort_stack_returned(source, task))
        goto poison;
    return 0;
poison:
    lsf_factory_cleanup_stack_poison(source);
    return -EIO;
}
'''


def private_mpol():
    text = replace(definition('mpol_dup'),
        'struct mempolicy *__mpol_dup(struct mempolicy *old)\n',
        'struct mempolicy *lsf_prepaid_cleanup_mpol_dup(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task, struct mempolicy *old)\n')
    text = replace(text, '\tstruct mempolicy *new = kmem_cache_alloc(policy_cache, GFP_KERNEL);\n',
        '\tstruct mempolicy *new;\n\n'
        '\tif (!old || current != kthreadd_task)\n\t\treturn ERR_PTR(-EOPNOTSUPP);\n'
        '\tnew = lsf_factory_cleanup_child_new(source, task, LSF_CLEANUP_MPOL, task);\n')
    return '''int lsf_prepaid_cleanup_mpol_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment)
        return -EINVAL;
    *bytes = sizeof(struct mempolicy);
    *alignment = __alignof__(struct mempolicy);
    return 0;
}

''' + text


def private_task_security():
    text = replace(definition('security_task_alloc'),
        'int security_task_alloc(struct task_struct *task, unsigned long clone_flags)\n',
        'int lsf_prepaid_cleanup_security_task_alloc(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task, unsigned long clone_flags)\n')
    text = replace(text, '\tint rc = lsm_task_alloc(task);\n',
        '\tint rc = 0;\n\n'
        '\t/* Actual initialized composite bytes, before every original hook. */\n'
        '\tif (!blob_sizes.lbs_task)\n\t\ttask->security = NULL;\n'
        '\telse {\n\t\ttask->security = lsf_factory_cleanup_child_new(source, task,\n'
        '\t\t    LSF_CLEANUP_TASK_SECURITY, task);\n'
        '\t\tif (!task->security)\n\t\t\trc = -ENOMEM;\n\t}\n')
    return '''int lsf_prepaid_cleanup_task_security_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || blob_sizes.lbs_task < 0)
        return -EINVAL;
    *bytes = blob_sizes.lbs_task;
    *alignment = ARCH_KMALLOC_MINALIGN;
    return 0;
}

''' + text


def full_constructor():
    text = definition('copy_process')
    signature = text[:text.index('\n{\n') + 1]
    text = replace(text, signature,
        'struct task_struct *lsf_prepaid_cleanup_copy_process(struct lsf_cleanup_task_source source,\n'
        '    struct kernel_clone_args *args, int node)\n')
    text = replace(text, '\tstruct task_struct *p;\n',
        '\tstruct task_struct *p;\n\tstruct pid *pid = NULL;\n\tint trace = 0;\n')
    text = replace(text, '\tconst u64 clone_flags = args->flags;\n',
        '\tconst u64 clone_flags = args ? args->flags : 0;\n')
    text = replace(text, '\tstruct nsproxy *nsp = current->nsproxy;\n',
        '\tstruct nsproxy *nsp = current->nsproxy;\n\n'
        '\t/* Only the actual fixed cleanup kernel_thread shape. The full\n'
        '\t * creator remains disconnected until the remaining real hook\n'
        '\t * allocation graphs and bootstrap owners are closed. */\n'
        '\tif (current != kthreadd_task || !args || clone_flags != LSF_CLEANUP_CLONE_FLAGS ||\n'
        '\t    !args->kthread || args->user_worker || args->io_thread || args->no_files ||\n'
        '\t    args->fn != lsf_prepaid_cleanup_kthread_entry || !args->fn_arg || !args->name ||\n'
        '\t    args->exit_signal != SIGCHLD || args->stack || args->stack_size || args->tls ||\n'
        '\t    args->set_tid || args->set_tid_size)\n\t\treturn ERR_PTR(-EOPNOTSUPP);\n')
    text = replace(text, '\tp = dup_task_struct(current, node);\n\tif (!p)\n\t\tgoto fork_out;\n',
        '\tp = lsf_prepaid_cleanup_dup_initialized(source, node);\n'
        '\tif (IS_ERR(p)) {\n\t\tretval = PTR_ERR(p);\n\t\tgoto fork_out;\n\t}\n')
    text = replace(text, '\tretval = copy_creds(p, clone_flags);\n',
        '\tretval = lsf_prepaid_cleanup_copy_creds(source, p, clone_flags);\n')
    text = replace(text, '\tdelayacct_tsk_init(p);\t/* Must remain after dup_task_struct() */\n',
        '\tlsf_cleanup_delayacct_init(source, p);\t/* Same original position after dup_task_struct. */\n')
    text = replace(text, '\t\tif (!set_kthread_struct(p))\n',
        '\t\tif (lsf_prepaid_cleanup_kthread_prepare(source, p))\n')
    text = replace(text, '\tretval = copy_sighand(clone_flags, p);\n',
        '\tretval = lsf_cleanup_copy_sighand(source, clone_flags, p);\n')
    text = replace(text, '\tretval = copy_signal(clone_flags, p);\n',
        '\tretval = lsf_cleanup_copy_signal(source, clone_flags, p);\n')
    text = replace(text, '\tp->mempolicy = mpol_dup(p->mempolicy);\n',
        '\t/* Keep the original inline NULL path. A non-NULL policy uses\n'
        '\t * the full maintained copy, alloc_lock and cpuset rebind body. */\n'
        '\tp->mempolicy = p->mempolicy ?\n'
        '\t\tlsf_prepaid_cleanup_mpol_dup(source, p, p->mempolicy) : mpol_dup(p->mempolicy);\n')
    text = replace(text, '\tretval = security_task_alloc(p, clone_flags);\n',
        '#ifdef CONFIG_SECURITY\n'
        '\tretval = lsf_prepaid_cleanup_security_task_alloc(source, p, clone_flags);\n'
        '#else\n\tretval = security_task_alloc(p, clone_flags);\n#endif\n')
    text = replace(text, '\t\tpid = alloc_pid(p->nsproxy->pid_ns_for_children, args->set_tid,\n',
        '\t\tpid = lsf_prepaid_cleanup_alloc_pid(source, p, p->nsproxy->pid_ns_for_children, args->set_tid,\n')
    text = replace(text, '\tp->start_time = ktime_get_ns();\n',
        '\t/* Real VM/IRQ preparation may take original VM locks. Do it before\n'
        '\t * tasklist/sighand locks and before recording private start time. */\n'
        '\tretval = lsf_prepaid_cleanup_constructor_prepare(source, p);\n'
        '\tif (retval)\n\t\tgoto bad_fork_cancel_cgroup;\n\n'
        '\tp->start_time = ktime_get_ns();\n')
    text = replace(text, '\t/* No more failure paths after this point. */\n',
        '\t/* Exact final pre-visibility commit under the REAL original\n'
        '\t * tasklist/sighand locks. Only fixed records/ref/atomics here. */\n'
        '\tif (!lsf_factory_cleanup_task_publish(source, p)) {\n'
        '\t\tretval = -EIO;\n\t\tgoto bad_fork_core_free;\n\t}\n\n'
        '\t/* No more failure paths after this point. */\n')
    text = replace(text, '\tWRITE_ONCE(p->__state, TASK_DEAD);\n\texit_task_stack_account(p);\n'
        '\tput_task_stack(p);\n\tdelayed_free_task(p);\n',
        '\tWRITE_ONCE(p->__state, TASK_DEAD);\n'
        '\tif (!lsf_factory_cleanup_task_abort_begin(source, p))\n\t\tgoto fork_out;\n'
        '\texit_task_stack_account(p);\n'
        '\tif (lsf_prepaid_cleanup_constructor_abort_stack(source, p))\n\t\tgoto fork_out;\n'
        '\t/* Keep the actual original MEMCG/RCU choice and complete real\n'
        '\t * free_task tail. Its usage-one cache guard waits for real children. */\n'
        '\tdelayed_free_task(p);\n')
    return ABORT_STACK + '\n' + text


def irq_preparation():
    return '''int lsf_prepaid_cleanup_irq_prepare(struct lsf_cleanup_task_source source,
    struct task_struct *task)
{
    unsigned long bank_base;
    void *address;
    if (current != kthreadd_task || in_interrupt() || irqs_disabled() ||
        atomic_read_acquire(&lsf_cleanup_irq_hint.phase) != LSF_CLEANUP_IRQ_BORN ||
        !lsf_factory_cleanup_irq_hint(source, task,
            sizeof(struct lsf_cleanup_request), &address, &bank_base) ||
        task != lsf_cleanup_irq_hint.task || address != lsf_cleanup_irq_hint.request ||
        bank_base != lsf_cleanup_irq_hint.bank_base ||
        !lsf_cleanup_irq_source_equal(source, lsf_cleanup_irq_hint.source) ||
        atomic_read(&lsf_cleanup_irq_hint.uncertain))
        return -EIO;
    return atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_BORN,
        LSF_CLEANUP_IRQ_PREPARED) == LSF_CLEANUP_IRQ_BORN ? 0 : -EIO;
}
'''


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-constructor-parent-preimage')
    outputs = dict(outputs)
    name = 'include/net/lsf_stream_cleanup_lifecycle.h'
    text = replace(outputs[name].decode(), '    LSF_CLEANUP_HELD\n',
        '    LSF_CLEANUP_ABORT_STACK_RETURNED,\n    LSF_CLEANUP_HELD\n')
    text = replace(text, 'int lsf_prepaid_cleanup_irq_arm(', 'int lsf_prepaid_cleanup_irq_commit(')
    outputs[name] = replace(text, 'int lsf_prepaid_cleanup_stack_publish(struct lsf_cleanup_task_source,\n'
        '    struct task_struct *);\n', '').encode()
    name = 'include/net/lsf_stream_cleanup_descendants.h'
    outputs[name] = replace(outputs[name].decode(), '    LSF_CLEANUP_FINAL_RETURNED\n',
        '    LSF_CLEANUP_FINAL_ABORT_DESTRUCTORS,\n    LSF_CLEANUP_FINAL_ABORT_WAITING,\n'
        '    LSF_CLEANUP_FINAL_RETURNED\n').encode()
    outputs[name] = replace(outputs[name].decode(), '    LSF_CLEANUP_CHILD_KINDS\n',
        '    LSF_CLEANUP_MPOL,\n    LSF_CLEANUP_TASK_SECURITY,\n    LSF_CLEANUP_CHILD_KINDS\n').encode()
    name = 'net/device-prepaid.h'
    text = replace(outputs[name].decode(), '    LSF_DEVICE_CLEANUP_PID_RADIX\n',
        '    LSF_DEVICE_CLEANUP_PID_RADIX,\n    LSF_DEVICE_CLEANUP_MPOL,\n    LSF_DEVICE_CLEANUP_TASK_SECURITY\n')
    outputs[name] = replace(text, '        kind == LSF_DEVICE_CLEANUP_PID_RADIX;\n',
        '        kind == LSF_DEVICE_CLEANUP_PID_RADIX || kind == LSF_DEVICE_CLEANUP_MPOL ||\n'
        '        kind == LSF_DEVICE_CLEANUP_TASK_SECURITY;\n').encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(),
        '    unsigned int cleanup_child_attempted, cleanup_final_phase;\n',
        '    unsigned int cleanup_child_attempted, cleanup_final_phase, cleanup_vm_prepared;\n').encode()
    include = '#include <net/lsf_stream_cleanup_constructor.h>\n'
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_pid.h>\n',
        '#include <net/lsf_stream_cleanup_pid.h>\n' + include)
    outputs[name] = replace(text, '#include "factory-cleanup-pid.c"\n',
        '#include "factory-cleanup-pid.c"\n#include "factory-cleanup-constructor.c"\n').encode()
    name = 'net/factory-cleanup-task.c'
    text = outputs[name].decode()
    text = replace(text, '    unsigned long actual_task_bytes, actual_alignment;\n',
        '    unsigned long actual_task_bytes, actual_alignment, actual_request_bytes;\n')
    text = replace(text, '    if (lsf_prepaid_cleanup_task_geometry(&actual_task_bytes, &actual_alignment) ||\n',
        '    if (lsf_prepaid_cleanup_request_geometry(&actual_request_bytes) ||\n'
        '        request_bytes != actual_request_bytes ||\n'
        '        lsf_prepaid_cleanup_task_geometry(&actual_task_bytes, &actual_alignment) ||\n')
    text = replace(text, '    memset(*request_address, 0, request_bytes);\n'
        '    memset((char *)page_address(factory.pages) + task_offset, 0, task_bytes);\n',
        '    memset(*request_address, 0, request_bytes);\n'
        '    /* Permanent source/range is born BEFORE task initialization. */\n'
        '    if (lsf_prepaid_cleanup_irq_birth_locked(*source,\n'
        '            (void *)((char *)page_address(factory.pages) + task_offset),\n'
        '            *request_address, (unsigned long)page_address(factory.pages)))\n'
        '        goto poison;\n'
        '    memset((char *)page_address(factory.pages) + task_offset, 0, task_bytes);\n')
    outputs[name] = replace(text,
        '    if ((const void *)task != (char *)page_address(factory.pages) + record->offset ||\n'
        '        !lsf_device_finish(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK))\n',
        '    if ((const void *)task != (char *)page_address(factory.pages) + record->offset ||\n'
        '        lsf_prepaid_cleanup_irq_abort_locked(source, task) ||\n'
        '        !lsf_device_finish(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK))\n').encode()
    name = 'net/factory-cleanup-lifecycle.c'
    text = replace(outputs[name].decode(),
        '    if (factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED) {\n',
        '    if (factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED &&\n'
        '        factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORT_STACK_RETURNED) {\n')
    text = replace(text,
        '        (factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORTING &&\n'
        '         factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED))\n',
        '        (factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORTING &&\n'
        '         factory.device->cleanup_lifecycle != LSF_CLEANUP_STACK_RETURNED &&\n'
        '         factory.device->cleanup_lifecycle != LSF_CLEANUP_ABORT_STACK_RETURNED))\n')
    text = replace(text, '    struct lsf_prepaid_view *metadata;\n',
        '    struct lsf_prepaid_view *metadata, *task_record, *stack_record;\n')
    text = replace(text, '    /* Reserve the REAL final-stack continuation reference before task\n',
        '    task_record = lsf_device_record(&factory.pool, source.owner, source.task, LSF_DEVICE_CLEANUP_TASK);\n'
        '    stack_record = lsf_device_record(&factory.pool, source.owner, factory.device->cleanup_stack, LSF_DEVICE_CLEANUP_STACK);\n'
        '    if (!factory.device->cleanup_vm_prepared || factory.pool.stopped ||\n'
        '        factory.pool.contexts[source.owner.slot].closed || !task_record || !stack_record ||\n'
        '        task_record->deferred != LSF_PREPAID_PRIVATE || stack_record->deferred != LSF_PREPAID_PRIVATE ||\n'
        '        metadata->deferred != LSF_PREPAID_PRIVATE)\n'
        '        goto poison;\n'
        '    /* Reserve the REAL final-stack continuation reference before task\n')
    # Move tryget after the COMPLETE same-lock non-ref admission preflight.
    text = replace(text, '        task->worker_private != (char *)page_address(factory.pages) + metadata->offset ||\n'
        '        !tryget_task_struct(task))\n',
        '        task->worker_private != (char *)page_address(factory.pages) + metadata->offset)\n')
    text = replace(text, '    factory.device->cleanup_retire_task = task;\n',
        '    if (!tryget_task_struct(task))\n        goto poison;\n'
        '    factory.device->cleanup_retire_task = task;\n'
        '    if (lsf_prepaid_cleanup_irq_commit(source, task))\n        goto poison;\n')
    outputs[name] = text.encode()
    name = 'net/factory-cleanup-descendants.c'
    text = replace(outputs[name].decode(), '    case LSF_CLEANUP_PID: return LSF_DEVICE_CLEANUP_PID;\n',
        '    case LSF_CLEANUP_PID: return LSF_DEVICE_CLEANUP_PID;\n'
        '    case LSF_CLEANUP_MPOL: return LSF_DEVICE_CLEANUP_MPOL;\n'
        '    case LSF_CLEANUP_TASK_SECURITY: return LSF_DEVICE_CLEANUP_TASK_SECURITY;\n')
    text = replace(text,
        '    notify = factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_WAITING &&\n',
        '    notify = (factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_WAITING ||\n'
        '        factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_ABORT_WAITING) &&\n')
    text = replace(text,
        '        factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_WAITING &&\n',
        '        (factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_WAITING ||\n'
        '         factory.device->cleanup_final_phase == LSF_CLEANUP_FINAL_ABORT_WAITING) &&\n')
    text = replace(text,
        '    int result = 0, notify = 0;\n    spin_lock_irqsave(&pool_lock, flags);\n',
        '    int result = 0, notify = 0;\n'
        '    if (lsf_factory_cleanup_abort_cache_final(task))\n        return 1;\n'
        '    spin_lock_irqsave(&pool_lock, flags);\n')
    text = replace(text,
        '    if (current != kthreadd_task || in_interrupt() || irqs_disabled())\n        return;\n'
        '    spin_lock_irqsave(&pool_lock, flags);\n',
        '    if (current != kthreadd_task || in_interrupt() || irqs_disabled())\n        return;\n'
        '    if (lsf_factory_cleanup_abort_pending()) {\n'
        '        lsf_factory_cleanup_abort_drain();\n        return;\n    }\n'
        '    spin_lock_irqsave(&pool_lock, flags);\n')
    outputs[name] = text.encode()
    name = 'kernel/lsf-cleanup-descendants.c'
    outputs[name] = replace(outputs[name].decode(), '    case LSF_CLEANUP_PID:\n',
        '    case LSF_CLEANUP_MPOL:\n#ifdef CONFIG_NUMA\n'
        '        return lsf_prepaid_cleanup_mpol_geometry(bytes, alignment);\n'
        '#else\n        return -EOPNOTSUPP;\n#endif\n'
        '    case LSF_CLEANUP_TASK_SECURITY:\n#ifdef CONFIG_SECURITY\n'
        '        return lsf_prepaid_cleanup_task_security_geometry(bytes, alignment);\n'
        '#else\n        return -EOPNOTSUPP;\n#endif\n'
        '    case LSF_CLEANUP_PID:\n').encode()
    name = 'mm/lsf-cleanup-stack-retire.c'
    text = outputs[name].decode()
    require(text.count('int lsf_prepaid_cleanup_stack_publish(') == 2, 'cleanup-constructor-both-vm-profiles')
    text = text.replace('int lsf_prepaid_cleanup_stack_publish(', 'int lsf_prepaid_cleanup_constructor_prepare(')
    text = replace(text,
        '    if (valid && !lsf_prepaid_cleanup_irq_prepare(source, task) &&\n'
        '        lsf_factory_cleanup_task_publish(source, task) &&\n'
        '        !lsf_prepaid_cleanup_irq_arm(source, task))\n',
        '    if (valid && !lsf_prepaid_cleanup_irq_prepare(source, task) &&\n'
        '        lsf_factory_cleanup_constructor_vm_prepared(source, task, stack))\n')
    outputs[name] = (include + text).encode()
    name = 'kernel/lsf-cleanup-irq.c'
    text = replace(outputs[name].decode(), '    LSF_CLEANUP_IRQ_PREPARED,\n',
        '    LSF_CLEANUP_IRQ_BORN,\n    LSF_CLEANUP_IRQ_ABORTED,\n    LSF_CLEANUP_IRQ_PREPARED,\n')
    begin = text.index('int lsf_prepaid_cleanup_irq_prepare(')
    end = text.index('int lsf_prepaid_cleanup_stack_release(', begin)
    text = replace(text, text[begin:end], irq_preparation() + '\n')
    # The remaining unselected old arm stub is replaced by the new helper's
    # own actual unselected refusal; no duplicate commit implementation.
    begin = text.index('int lsf_prepaid_cleanup_irq_arm(')
    end = text.index('int lsf_prepaid_cleanup_stack_release(', begin)
    text = replace(text, text[begin:end], '')
    outputs[name] = text.encode()
    name = 'kernel/kthread.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_descendants.h>\n',
        '#include <net/lsf_stream_cleanup_descendants.h>\n' + include)
    outputs[name] = replace(text, '#include "lsf-cleanup-irq.c"\n',
        '#include "lsf-cleanup-irq.c"\n#include "lsf-cleanup-constructor-irq.c"\n').encode()
    name = 'kernel/lsf-cleanup-lifecycle.c'
    outputs[name] = replace(outputs[name].decode(),
        '    owned = lsf_factory_cleanup_kthread_current(source, task);\n',
        '    owned = lsf_factory_cleanup_kthread_current(source, task);\n'
        '    if (!owned && lsf_factory_cleanup_abort_kthread_absent(source, task))\n'
        '        return 1; /* Original failed metadata allocation has no destructor. */\n').encode()
    name = 'kernel/fork.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_pid.h>\n',
        '#include <net/lsf_stream_cleanup_pid.h>\n' + include)
    old = definition('free_task')
    text = replace(text, old, replace(old, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_cleanup_abort_destruct_begin(tsk) < 0)\n\t\treturn;\n#endif\n'))
    outputs[name] = (text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-constructor.c"\n#endif\n').encode()
    outputs['kernel/lsf-cleanup-constructor.c'] = full_constructor().encode()
    outputs['kernel/lsf-cleanup-constructor-irq.c'] = (OWNED / 'kernel-cleanup-constructor-irq.c').read_bytes()
    outputs['include/net/lsf_stream_cleanup_constructor.h'] = (OWNED / 'cleanup-constructor-private.h').read_bytes()
    outputs['net/factory-cleanup-constructor.c'] = (OWNED / 'factory-cleanup-constructor.c').read_bytes()
    name = 'mm/mempolicy.c'
    text = inputs[name].decode()
    old = definition('mpol_put')
    final = replace(old, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_cleanup_child_live(pol, LSF_CLEANUP_MPOL) < 0)\n\t\treturn;\n#endif\n')
    final = replace(final, '\tkmem_cache_free(policy_cache, pol);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_cleanup_child_finish(pol, LSF_CLEANUP_MPOL))\n\t\treturn;\n#endif\n'
        '\tkmem_cache_free(policy_cache, pol);\n')
    outputs[name] = (include + replace(text, old, final) + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-mpol.c"\n#endif\n').encode()
    outputs['mm/lsf-cleanup-mpol.c'] = private_mpol().encode()
    name = 'security/security.c'
    text = outputs[name].decode()
    old = definition('security_task_free')
    final = replace(old, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tint origin = lsf_factory_cleanup_child_defer(task->security, LSF_CLEANUP_TASK_SECURITY);\n'
        '\tif (origin < 0)\n\t\treturn;\n#endif\n')
    final = replace(final, '\tkfree(task->security);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (origin)\n\t\t(void)lsf_factory_cleanup_child_finish(task->security, LSF_CLEANUP_TASK_SECURITY);\n'
        '\telse\n#endif\n\t\tkfree(task->security);\n')
    outputs[name] = (include + replace(text, old, final) + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-task-security.c"\n#endif\n').encode()
    outputs['security/lsf-cleanup-task-security.c'] = private_task_security().encode()
    return outputs
