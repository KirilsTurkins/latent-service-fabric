"""Uninstalled real cred/signal/delay births and once-only final child drain.

No full copy_process, enabled hook-graph, runtime or bootstrap qualification.
The separately frozen lifecycle, entry and IRQ layers are unchanged inputs.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_irq as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_descendants.json'
FIXTURE_SHA = 'ff4a5327398e9a2d1e70078b82adc1c7fa2636809da38b86511383bb2b00beaf'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 128 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-descendants-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-descendants-source.v1' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        value['archiveSha256'] == 'e09b6727e5c521253f0d41694900b9c38fb7604db7d35238a8197aa9f7de2428' and
        len(value['source']) == 7 and len(value['sections']) == 17 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'fullConstructorClosure', 'lsmCallbackAllocationClosure', 'actualRcuExecution',
            'completeAllocationClosure', 'productionInstallation')),
        'cleanup-descendants-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-descendants-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-descendants-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-descendants-definition-preimage')


def definition(name):
    return preimages()['sections'][name]['text']


def private_creds():
    text = replace(definition('prepare_creds'), 'struct cred *prepare_creds(void)\n',
        'static struct cred *lsf_cleanup_prepare_creds(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *owned_task)\n')
    text = replace(text, '\tnew = kmem_cache_alloc(cred_jar, GFP_KERNEL);\n',
        '\tnew = lsf_factory_cleanup_child_new(source, owned_task, LSF_CLEANUP_CRED, owned_task);\n')
    text = replace(text, '\tif (security_prepare_creds(new, old, GFP_KERNEL_ACCOUNT) < 0)\n',
        '#ifdef CONFIG_SECURITY\n'
        '\tif (lsf_prepaid_cleanup_security_prepare_creds(source, owned_task, new, old, GFP_KERNEL_ACCOUNT) < 0)\n'
        '#else\n\tif (security_prepare_creds(new, old, GFP_KERNEL_ACCOUNT) < 0)\n#endif\n')
    copied = replace(definition('copy_creds'),
        'int copy_creds(struct task_struct *p, unsigned long clone_flags)\n',
        'int lsf_prepaid_cleanup_copy_creds(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *p, unsigned long clone_flags)\n')
    copied = replace(copied, '\tint ret;\n', '\tint ret;\n\n'
        '\tif (clone_flags != LSF_CLEANUP_CLONE_FLAGS || current != kthreadd_task)\n'
        '\t\treturn -EOPNOTSUPP;\n')
    copied = replace(copied, '\tnew = prepare_creds();\n',
        '\tnew = lsf_cleanup_prepare_creds(source, p);\n')
    geometry = '''int lsf_prepaid_cleanup_cred_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment)
        return -EINVAL;
    *bytes = sizeof(struct cred);
    *alignment = __alignof__(struct cred);
    return 0;
}
'''
    return geometry + '\n' + text + '\n' + copied


def private_security():
    text = replace(definition('security_prepare_creds'),
        'int security_prepare_creds(struct cred *new, const struct cred *old, gfp_t gfp)\n',
        'int lsf_prepaid_cleanup_security_prepare_creds(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *owned_task, struct cred *new, const struct cred *old, gfp_t gfp)\n')
    text = replace(text, '\tint rc = lsm_cred_alloc(new, gfp);\n',
        '\tint rc = 0;\n\n'
        '\t/* Preserve the actual initialized composite size, including size-zero.\n'
        '\t * Every original registered hook below still runs. Their complete\n'
        '\t * selected allocation graph is an independent qualification gate. */\n'
        '\tif (blob_sizes.lbs_cred == 0)\n'
        '\t\tnew->security = NULL;\n'
        '\telse {\n'
        '\t\tnew->security = lsf_factory_cleanup_child_new(source, owned_task,\n'
        '\t\t    LSF_CLEANUP_CRED_SECURITY, new);\n'
        '\t\tif (!new->security)\n\t\t\trc = -ENOMEM;\n\t}\n')
    geometry = '''int lsf_prepaid_cleanup_cred_security_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || blob_sizes.lbs_cred < 0)
        return -EINVAL;
    *bytes = blob_sizes.lbs_cred;
    *alignment = ARCH_KMALLOC_MINALIGN;
    return 0;
}
'''
    return geometry + '\n' + text


SIGHAND_WRAPPER = '''/* The original slab type-safety guarantee cannot be borrowed by a carved
 * object. Retain this real, originally charged wrapper through a real RCU GP. */
struct lsf_cleanup_sighand {
    struct sighand_struct value;
    struct rcu_head rcu;
};

static void lsf_cleanup_sighand_return(struct rcu_head *head)
{
    struct lsf_cleanup_sighand *owned = container_of(head, struct lsf_cleanup_sighand, rcu);
    lsf_factory_cleanup_child_finish(&owned->value, LSF_CLEANUP_SIGHAND);
    /* LAST owned/head access. The original bank remains held independently. */
}

static int lsf_cleanup_sighand_defer(struct sighand_struct *sighand)
{
    struct lsf_cleanup_sighand *owned;
    int origin = lsf_factory_cleanup_child_defer(sighand, LSF_CLEANUP_SIGHAND);
    if (origin != 1)
        return origin;
    owned = container_of(sighand, struct lsf_cleanup_sighand, value);
    call_rcu(&owned->rcu, lsf_cleanup_sighand_return);
    return 1;
}
'''


def private_signal():
    sighand = replace(definition('copy_sighand'),
        'static int copy_sighand(u64 clone_flags, struct task_struct *tsk)\n',
        'static int lsf_cleanup_copy_sighand(struct lsf_cleanup_task_source source,\n'
        '    u64 clone_flags, struct task_struct *tsk)\n')
    sighand = replace(sighand, '\tstruct sighand_struct *sig;\n',
        '\tstruct sighand_struct *sig;\n\n'
        '\tif (clone_flags != LSF_CLEANUP_CLONE_FLAGS)\n\t\treturn -EOPNOTSUPP;\n')
    sighand = replace(sighand, '\tsig = kmem_cache_alloc(sighand_cachep, GFP_KERNEL);\n',
        '\tsig = lsf_factory_cleanup_child_new(source, tsk, LSF_CLEANUP_SIGHAND, tsk);\n')
    sighand = replace(sighand, '\trefcount_set(&sig->count, 1);\n',
        '\t/* Execute the REAL slab constructor, including signalfd_wqh. */\n'
        '\tsighand_ctor(sig);\n\trefcount_set(&sig->count, 1);\n')
    signal = replace(definition('copy_signal'),
        'static int copy_signal(unsigned long clone_flags, struct task_struct *tsk)\n',
        'static int lsf_cleanup_copy_signal(struct lsf_cleanup_task_source source,\n'
        '    unsigned long clone_flags, struct task_struct *tsk)\n')
    signal = replace(signal, '\tstruct signal_struct *sig;\n',
        '\tstruct signal_struct *sig;\n\n'
        '\tif (clone_flags != LSF_CLEANUP_CLONE_FLAGS)\n\t\treturn -EOPNOTSUPP;\n')
    signal = replace(signal, '\tsig = kmem_cache_zalloc(signal_cachep, GFP_KERNEL);\n',
        '\tsig = lsf_factory_cleanup_child_new(source, tsk, LSF_CLEANUP_SIGNAL, tsk);\n')
    geometry = '''int lsf_prepaid_cleanup_child_geometry(unsigned int kind, unsigned long *bytes,
    unsigned long *alignment)
{
    if (!bytes || !alignment)
        return -EINVAL;
    switch (kind) {
    case LSF_CLEANUP_CRED:
        return lsf_prepaid_cleanup_cred_geometry(bytes, alignment);
    case LSF_CLEANUP_CRED_SECURITY:
#ifdef CONFIG_SECURITY
        return lsf_prepaid_cleanup_cred_security_geometry(bytes, alignment);
#else
        return -EOPNOTSUPP;
#endif
    case LSF_CLEANUP_SIGHAND:
        *bytes = sizeof(struct lsf_cleanup_sighand);
        *alignment = __alignof__(struct lsf_cleanup_sighand);
        return 0;
    case LSF_CLEANUP_SIGNAL:
        *bytes = sizeof(struct signal_struct);
        *alignment = __alignof__(struct signal_struct);
        return 0;
    case LSF_CLEANUP_DELAY:
#ifdef CONFIG_TASK_DELAY_ACCT
        *bytes = sizeof(struct task_delay_info);
        *alignment = __alignof__(struct task_delay_info);
        return 0;
#else
        return -EOPNOTSUPP;
#endif
    default:
        return -EOPNOTSUPP;
    }
}
'''
    delay = '''#ifdef CONFIG_TASK_DELAY_ACCT
static void lsf_cleanup_delayacct_init(struct lsf_cleanup_task_source source,
    struct task_struct *tsk)
{
    /* Exact original runtime condition; never force delay accounting off. */
    tsk->delays = NULL;
    if (delayacct_on) {
        tsk->delays = lsf_factory_cleanup_child_new(source, tsk, LSF_CLEANUP_DELAY, tsk);
        if (tsk->delays)
            raw_spin_lock_init(&tsk->delays->lock);
    }
}
#else
static void lsf_cleanup_delayacct_init(struct lsf_cleanup_task_source source,
    struct task_struct *tsk) { }
#endif
'''
    return SIGHAND_WRAPPER + '\n' + geometry + '\n' + sighand + '\n' + signal + '\n' + delay


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-descendants-parent-preimage')
    outputs = dict(outputs)
    for name, raw in inputs.items():
        if name not in outputs:
            outputs[name] = raw
    name = 'net/device-prepaid.h'
    text = replace(outputs[name].decode(), '    LSF_DEVICE_CLEANUP_KTHREAD\n',
        '    LSF_DEVICE_CLEANUP_KTHREAD,\n    LSF_DEVICE_CLEANUP_CRED,\n'
        '    LSF_DEVICE_CLEANUP_CRED_SECURITY,\n    LSF_DEVICE_CLEANUP_SIGHAND,\n'
        '    LSF_DEVICE_CLEANUP_SIGNAL,\n    LSF_DEVICE_CLEANUP_DELAY\n')
    outputs[name] = replace(text, 'kind == LSF_DEVICE_CLEANUP_KTHREAD;',
        'kind == LSF_DEVICE_CLEANUP_KTHREAD || kind == LSF_DEVICE_CLEANUP_CRED ||\n'
        '        kind == LSF_DEVICE_CLEANUP_CRED_SECURITY || kind == LSF_DEVICE_CLEANUP_SIGHAND ||\n'
        '        kind == LSF_DEVICE_CLEANUP_SIGNAL || kind == LSF_DEVICE_CLEANUP_DELAY;').encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(), '    unsigned int cleanup_entry_started;\n',
        '    unsigned int cleanup_entry_started;\n'
        '    unsigned int cleanup_child_attempted, cleanup_final_phase;\n').encode()
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_lifecycle.h>\n',
        '#include <net/lsf_stream_cleanup_lifecycle.h>\n'
        '#include <net/lsf_stream_cleanup_descendants.h>\n')
    outputs[name] = replace(text, '#include "factory-cleanup-irq.c"\n',
        '#include "factory-cleanup-irq.c"\n#include "factory-cleanup-descendants.c"\n').encode()
    name = 'net/factory-cleanup-lifecycle.c'
    text = outputs[name].decode()
    old_final = text[text.index('/* Original free_task has already run the real final task destructors.') :]
    require(old_final.count('int lsf_factory_cleanup_task_final(') == 1 and
        hashlib.sha256(old_final.encode()).hexdigest() == preimages()['oldFinalSuffixSha256'],
        'cleanup-descendants-old-final-boundary')
    outputs[name] = replace(text, old_final, '').encode()
    name = 'kernel/fork.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_lifecycle.h>\n',
        '#include <net/lsf_stream_cleanup_lifecycle.h>\n'
        '#include <net/lsf_stream_cleanup_descendants.h>\n'
        'static int lsf_cleanup_sighand_defer(struct sighand_struct *);\n')
    old = definition('put_task_struct')
    text = replace(text, old, replace(old, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_cleanup_task_destruct_begin(tsk) < 0)\n\t\treturn;\n#endif\n'))
    old = definition('free_signal_struct')
    text = replace(text, old, replace(old, '\tkmem_cache_free(signal_cachep, sig);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_cleanup_child_finish(sig, LSF_CLEANUP_SIGNAL))\n\t\treturn;\n#endif\n'
        '\tkmem_cache_free(signal_cachep, sig);\n'))
    old = definition('cleanup_sighand')
    text = replace(text, old, replace(old, '\t\tkmem_cache_free(sighand_cachep, sighand);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (lsf_cleanup_sighand_defer(sighand))\n\t\t\treturn;\n#endif\n'
        '\t\tkmem_cache_free(sighand_cachep, sighand);\n'))
    outputs[name] = text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
    outputs[name] = (outputs[name] + '#include "lsf-cleanup-descendants.c"\n#endif\n').encode()
    name = 'kernel/cred.c'
    text = replace(outputs[name].decode(), '#include <linux/uidgid.h>\n',
        '#include <linux/uidgid.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_cleanup_descendants.h>\n#endif\n')
    old = definition('put_cred_rcu')
    text = replace(text, old, replace(old, '\tkmem_cache_free(cred_jar, cred);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_cleanup_child_finish(cred, LSF_CLEANUP_CRED))\n\t\treturn;\n#endif\n'
        '\tkmem_cache_free(cred_jar, cred);\n'))
    outputs[name] = (text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-cred.c"\n#endif\n').encode()
    name = 'security/security.c'
    text = outputs[name].decode()
    # No global hook dispatch is removed or replaced.
    old = definition('security_cred_free')
    text = replace(text, old, replace(old, '\tkfree(cred->security);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_cleanup_child_finish(cred->security, LSF_CLEANUP_CRED_SECURITY)) {\n'
        '\t\tcred->security = NULL;\n\t\treturn;\n\t}\n#endif\n'
        '\tkfree(cred->security);\n'))
    outputs[name] = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_cleanup_descendants.h>\n#endif\n' + text +
        '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-cleanup-cred-security.c"\n#endif\n').encode()
    name = 'include/linux/delayacct.h'
    text = replace(outputs[name].decode(), '#include <linux/jump_label.h>\n',
        '#include <linux/jump_label.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_cleanup_descendants.h>\n#endif\n')
    old = definition('delayacct_tsk_free')
    text = replace(text, old, replace(old, '\tif (tsk->delays)\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (tsk->delays && lsf_factory_cleanup_child_finish(tsk->delays, LSF_CLEANUP_DELAY)) {\n'
        '\t\ttsk->delays = NULL;\n\t\treturn;\n\t}\n#endif\n\tif (tsk->delays)\n'))
    outputs[name] = text.encode()
    name = 'kernel/kthread.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_lifecycle.h>\n',
        '#include <net/lsf_stream_cleanup_lifecycle.h>\n'
        '#include <net/lsf_stream_cleanup_descendants.h>\n')
    text = replace(text, '\t\t    && !lsf_prepaid_cleanup_irq_pending()\n',
        '\t\t    && !lsf_prepaid_cleanup_irq_pending()\n'
        '\t\t    && !lsf_factory_cleanup_final_pending()\n')
    text = replace(text, '\t\t       || lsf_prepaid_cleanup_irq_pending()\n',
        '\t\t       || lsf_prepaid_cleanup_irq_pending()\n'
        '\t\t       || lsf_factory_cleanup_final_pending()\n')
    outputs[name] = replace(text, '\t\t\tif (lsf_prepaid_cleanup_irq_pending()) {\n',
        '\t\t\tif (lsf_factory_cleanup_final_pending()) {\n'
        '\t\t\t\tspin_unlock(&kthread_create_lock);\n'
        '\t\t\t\tlsf_factory_cleanup_final_drain();\n'
        '\t\t\t\tspin_lock(&kthread_create_lock);\n'
        '\t\t\t\tcontinue;\n\t\t\t}\n'
        '\t\t\tif (lsf_prepaid_cleanup_irq_pending()) {\n').encode()
    outputs['kernel/lsf-cleanup-cred.c'] = private_creds().encode()
    outputs['security/lsf-cleanup-cred-security.c'] = private_security().encode()
    outputs['kernel/lsf-cleanup-descendants.c'] = private_signal().encode()
    outputs['include/net/lsf_stream_cleanup_descendants.h'] = (OWNED / 'cleanup-descendants-private.h').read_bytes()
    outputs['net/factory-cleanup-descendants.c'] = (OWNED / 'factory-cleanup-descendants.c').read_bytes()
    return outputs


def derive(inputs):
    extras = set(preimages()['source'])
    # Some whole originals already belong to earlier authenticated layers.
    prior_names = set(preimages()['parentInputs'])
    require(set(inputs) == prior_names | extras, 'cleanup-descendants-complete-membership')
    return transform(prior.derive({name: inputs[name] for name in prior_names}),
        {name: inputs[name] for name in extras})
