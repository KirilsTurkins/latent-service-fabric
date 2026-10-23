"""Uninstalled maintained init-PID and separately rooted shared-IDR routes.

No complete copy_process, shared bootstrap ownership or Linux qualification.
All earlier source files are frozen inputs; only derived outputs are composed.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_descendants as prior
from tools import host_stream_kernel_device_registration as registration

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_pid.json'
FIXTURE_SHA = 'd438a475d0f64547bbc3f59b23e0a061c33dae0454cb151ad4e2cb1b9015b482'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 96 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-pid-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-pid-source.v1' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        value['archiveSha256'] == 'e09b6727e5c521253f0d41694900b9c38fb7604db7d35238a8197aa9f7de2428' and
        len(value['source']) == 3 and len(value['sections']) == 4 and
        len(value['radixDefinitions']) == 7 and len(value['parentDerived']) == 8 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'fullConstructorClosure', 'sharedPidBootstrapOwnerQualified',
            'actualRcuExecution', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-pid-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-pid-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-pid-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-pid-definition-preimage')
    # These are the exact previously authenticated maintained normal bodies,
    # rather than a copied replacement algorithm or the prior PCI private copy.
    previous = registration.fixture()
    for name, expected in value['radixDefinitions'].items():
        require(previous['sections'][name] == expected, 'cleanup-pid-prior-radix-definition')


def definition(name):
    return preimages()['sections'][name]['text']


def radix_definition(name):
    return preimages()['radixDefinitions'][name]['text']


def private_pid():
    text = replace(definition('alloc_pid'),
        'struct pid *alloc_pid(struct pid_namespace *ns, pid_t *set_tid,\n\t\t      size_t set_tid_size)\n',
        'struct pid *lsf_prepaid_cleanup_alloc_pid(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task, struct pid_namespace *ns, pid_t *set_tid, size_t set_tid_size)\n')
    text = replace(text, '\tint retval = -ENOMEM;\n', '\tint retval = -ENOMEM;\n\n'
        '\t/* Exact actual kernel_thread namespace/argument subset. No supplied\n'
        '\t * namespace is dereferenced until exact init namespace membership. */\n'
        '\tif (current != kthreadd_task || ns != &init_pid_ns || ns->level ||\n'
        '\t    set_tid || set_tid_size)\n\t\treturn ERR_PTR(-EOPNOTSUPP);\n')
    text = replace(text, '\tpid = kmem_cache_alloc(ns->pid_cachep, GFP_KERNEL);\n',
        '\tpid = lsf_factory_cleanup_child_new(source, task, LSF_CLEANUP_PID, task);\n')
    text = replace(text, '\t\tidr_preload(GFP_KERNEL);\n',
        '\t\tretval = lsf_prepaid_cleanup_pid_preload(source, task, pid, &tmp->idr);\n'
        '\t\tif (retval)\n\t\t\tgoto out_free;\n')
    text = replace(text, '\t\t\tnr = idr_alloc_cyclic(&tmp->idr, NULL, pid_min,\n',
        '\t\t\tnr = lsf_prepaid_cleanup_pid_idr_alloc_cyclic(source, task, pid, &tmp->idr, NULL, pid_min,\n')
    text = replace(text, '\tkmem_cache_free(ns->pid_cachep, pid);\n',
        '\t/* Original error order and real IDR unlink ran above. The original\n'
        '\t * bank is retained on any callback/origin uncertainty. */\n'
        '\t(void)lsf_factory_cleanup_child_finish(pid, LSF_CLEANUP_PID);\n')
    geometry = '''int lsf_prepaid_cleanup_pid_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment)
        return -EINVAL;
    /* Exact actual init namespace cache creation operand, including the one
     * flexible upid. sizeof(struct pid) alone would undercharge this object. */
    *bytes = struct_size_t(struct pid, numbers, 1);
    *alignment = __alignof__(struct pid);
    return 0;
}

static int lsf_cleanup_pid_usable(const struct pid *pid)
{
    int origin = lsf_factory_cleanup_pid_origin(pid);
    if (origin != 1)
        return origin;
    if (pid->level || pid->numbers[0].ns != &init_pid_ns) {
        lsf_factory_cleanup_stack_poison((struct lsf_cleanup_task_source){0});
        return -1;
    }
    return 1;
}
'''
    return geometry + '\n' + text


def private_radix():
    text = radix_definition('radix_tree_node_alloc')
    text = replace(text, 'radix_tree_node_alloc(gfp_t gfp_mask,',
        'lsf_cleanup_pid_radix_node_alloc(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task, const struct pid *pid, gfp_t gfp_mask,')
    start = text.index('\tstruct radix_tree_node *ret = NULL;\n')
    end = text.index('out:\n', start) + len('out:\n')
    text = text[:start] + ('\tstruct radix_tree_node *ret;\n\n'
        '\t(void)gfp_mask;\n'
        '\tif (IS_ENABLED(CONFIG_DEBUG_KMEMLEAK))\n\t\treturn NULL;\n'
        '\tret = lsf_factory_cleanup_pid_radix_new(source, task, pid);\n') + text[end:]
    text = replace(text, '\tif (ret) {\n\t\tret->shift = shift;\n',
        '\tif (ret) {\n\t\tradix_tree_node_ctor(ret);\n\t\tret->shift = shift;\n')
    text = replace(text, '\treturn ret;\n',
        '\tif (ret && !lsf_factory_cleanup_pid_radix_publish(source, task, pid, ret))\n'
        '\t\treturn NULL;\n\treturn ret;\n')
    extend = replace(radix_definition('radix_tree_extend'),
        'static int radix_tree_extend(struct radix_tree_root *root, gfp_t gfp,',
        'static int lsf_cleanup_pid_radix_extend(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task, const struct pid *pid, struct radix_tree_root *root, gfp_t gfp,')
    extend = replace(extend, 'radix_tree_node_alloc(gfp, NULL,',
        'lsf_cleanup_pid_radix_node_alloc(source, task, pid, gfp, NULL,')
    free = replace(radix_definition('idr_get_free'),
        'void __rcu **idr_get_free(struct radix_tree_root *root,',
        'void __rcu **lsf_prepaid_cleanup_pid_idr_get_free(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task, const struct pid *pid, struct radix_tree_root *root,')
    free = replace(free, '\tshift = radix_tree_load_root(root, &child, &maxindex);\n',
        '\tif (root != &init_pid_ns.idr.idr_rt ||\n'
        '\t    !lsf_factory_cleanup_pid_constructing(source, task, pid))\n'
        '\t\treturn ERR_PTR(-EOPNOTSUPP);\n\n'
        '\tshift = radix_tree_load_root(root, &child, &maxindex);\n')
    free = replace(free, 'radix_tree_extend(root, gfp, start, shift)',
        'lsf_cleanup_pid_radix_extend(source, task, pid, root, gfp, start, shift)')
    free = replace(free, 'radix_tree_node_alloc(gfp, node, root, shift,',
        'lsf_cleanup_pid_radix_node_alloc(source, task, pid, gfp, node, root, shift,')
    geometry = '''int lsf_prepaid_cleanup_pid_radix_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment)
        return -EINVAL;
    *bytes = sizeof(struct radix_tree_node);
    *alignment = __alignof__(struct radix_tree_node);
    return 0;
}

int lsf_prepaid_cleanup_pid_preload(struct lsf_cleanup_task_source source,
    struct task_struct *task, const struct pid *pid, struct idr *idr)
{
    if (idr != &init_pid_ns.idr || !lsf_factory_cleanup_pid_constructing(source, task, pid))
        return -EOPNOTSUPP;
    /* The maintained preload/end extent uses this REAL local lock. Keep it;
     * do not borrow the per-CPU node cache or replace it by guessed preemption
     * semantics. Every node is born by the exact original-record allocator. */
    local_lock(&radix_tree_preloads.lock);
    return 0;
}
'''
    return geometry + '\n' + text + '\n' + extend + '\n' + free


def private_idr():
    text = replace(radix_definition('idr_alloc_u32'),
        'int idr_alloc_u32(struct idr *idr, void *ptr, u32 *nextid,',
        'static int lsf_cleanup_pid_idr_alloc_u32(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task, const struct pid *pid, struct idr *idr, void *ptr, u32 *nextid,')
    text = replace(text, 'idr_get_free(&idr->idr_rt, &iter, gfp, max - base)',
        'lsf_prepaid_cleanup_pid_idr_get_free(source, task, pid, &idr->idr_rt, &iter, gfp, max - base)')
    cyclic = replace(radix_definition('idr_alloc_cyclic'),
        'int idr_alloc_cyclic(struct idr *idr, void *ptr, int start, int end, gfp_t gfp)',
        'int lsf_prepaid_cleanup_pid_idr_alloc_cyclic(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task, const struct pid *pid, struct idr *idr, void *ptr, int start, int end, gfp_t gfp)')
    cyclic = replace(cyclic, '\tint err, max = end > 0 ? end - 1 : INT_MAX;\n',
        '\tint err, max = end > 0 ? end - 1 : INT_MAX;\n\n'
        '\tif (ptr || idr != &init_pid_ns.idr ||\n'
        '\t    !lsf_factory_cleanup_pid_constructing(source, task, pid))\n\t\treturn -EOPNOTSUPP;\n')
    require(cyclic.count('idr_alloc_u32(idr, ptr, &id, max, gfp)') == 2,
        'cleanup-pid-original-two-cyclic-attempts')
    cyclic = cyclic.replace('idr_alloc_u32(idr, ptr, &id, max, gfp)',
        'lsf_cleanup_pid_idr_alloc_u32(source, task, pid, idr, ptr, &id, max, gfp)')
    return text + '\n' + cyclic


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-pid-parent-preimage')
    outputs = dict(outputs)
    for name, raw in inputs.items():
        require(name not in outputs, 'cleanup-pid-new-whole-source')
        outputs[name] = raw
    name = 'include/net/lsf_stream_cleanup_descendants.h'
    outputs[name] = replace(outputs[name].decode(), '    LSF_CLEANUP_CHILD_KINDS\n',
        '    LSF_CLEANUP_PID,\n    LSF_CLEANUP_CHILD_KINDS\n').encode()
    name = 'net/device-prepaid.h'
    text = replace(outputs[name].decode(), '    LSF_DEVICE_CLEANUP_DELAY\n',
        '    LSF_DEVICE_CLEANUP_DELAY,\n    LSF_DEVICE_CLEANUP_PID,\n    LSF_DEVICE_CLEANUP_PID_RADIX\n')
    outputs[name] = replace(text, 'kind == LSF_DEVICE_CLEANUP_DELAY;',
        'kind == LSF_DEVICE_CLEANUP_DELAY || kind == LSF_DEVICE_CLEANUP_PID ||\n'
        '        kind == LSF_DEVICE_CLEANUP_PID_RADIX;').encode()
    name = 'net/factory-cleanup-descendants.c'
    outputs[name] = replace(outputs[name].decode(), '    case LSF_CLEANUP_DELAY: return LSF_DEVICE_CLEANUP_DELAY;\n',
        '    case LSF_CLEANUP_DELAY: return LSF_DEVICE_CLEANUP_DELAY;\n'
        '    case LSF_CLEANUP_PID: return LSF_DEVICE_CLEANUP_PID;\n').encode()
    name = 'kernel/lsf-cleanup-descendants.c'
    outputs[name] = replace(outputs[name].decode(), '    case LSF_CLEANUP_CRED:\n',
        '    case LSF_CLEANUP_PID:\n        return lsf_prepaid_cleanup_pid_geometry(bytes, alignment);\n'
        '    case LSF_CLEANUP_CRED:\n').encode()
    include = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_cleanup_pid.h>\n#endif\n'
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_descendants.h>\n',
        '#include <net/lsf_stream_cleanup_descendants.h>\n#include <net/lsf_stream_cleanup_pid.h>\n')
    outputs[name] = replace(text, '#include "factory-cleanup-descendants.c"\n',
        '#include "factory-cleanup-descendants.c"\n#include "factory-cleanup-pid.c"\n').encode()
    name = 'kernel/fork.c'
    outputs[name] = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_descendants.h>\n',
        '#include <net/lsf_stream_cleanup_descendants.h>\n#include <net/lsf_stream_cleanup_pid.h>\n').encode()
    name = 'kernel/pid.c'
    text = replace(outputs[name].decode(), '#include <uapi/linux/pidfd.h>\n',
        '#include <uapi/linux/pidfd.h>\n' + include)
    text = replace(text, definition('put_pid'),
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-cleanup-pid.c"\n#endif\n' +
        replace(replace(definition('put_pid'), '\tstruct pid_namespace *ns;\n',
            '\tstruct pid_namespace *ns;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tif (lsf_cleanup_pid_usable(pid) < 0)\n\t\treturn;\n#endif\n'),
            '\t\tkmem_cache_free(ns->pid_cachep, pid);\n',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\t\tif (!lsf_factory_cleanup_child_finish(pid, LSF_CLEANUP_PID))\n'
            '#endif\n\t\t\tkmem_cache_free(ns->pid_cachep, pid);\n'))
    old = definition('free_pid')
    text = replace(text, old, replace(old, '\tunsigned long flags;\n',
        '\tunsigned long flags;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tint lsf_owned = lsf_cleanup_pid_usable(pid);\n'
        '\tif (lsf_owned < 0 || (lsf_owned &&\n'
        '\t    lsf_factory_cleanup_child_defer(pid, LSF_CLEANUP_PID) != 1))\n\t\treturn;\n#endif\n'))
    outputs[name] = text.encode()
    name = 'lib/radix-tree.c'
    text = replace(outputs[name].decode(), '#include <linux/radix-tree.h>\n',
        '#include <linux/radix-tree.h>\n' + include + '#include <linux/pid_namespace.h>\n')
    text = replace(text, '\tstruct lsf_device_registration_source lsf_source;\n',
        '\tstruct lsf_cleanup_pid_radix_source lsf_cleanup_source;\n'
        '\tstruct lsf_device_registration_source lsf_source;\n'
        '\tint lsf_cleanup_owned = lsf_factory_cleanup_pid_radix_return_begin(node, &lsf_cleanup_source);\n'
        '\tint lsf_owned;\n'
        '\tif (lsf_cleanup_owned < 0)\n\t\treturn;\n')
    text = replace(text, '\tint lsf_owned = lsf_factory_device_registration_return_begin(node,\n',
        '\tlsf_owned = lsf_cleanup_owned ? 0 : lsf_factory_device_registration_return_begin(node,\n')
    text = replace(text, '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (lsf_owned) {\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_cleanup_owned) {\n'
        '\t\t(void)lsf_factory_cleanup_pid_radix_return_finish(lsf_cleanup_source);\n'
        '\t\treturn;\n\t}\n\tif (lsf_owned) {\n')
    outputs[name] = (text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-pid-radix.c"\n#endif\n').encode()
    name = 'lib/idr.c'
    text = replace(outputs[name].decode(), '#include <linux/xarray.h>\n',
        '#include <linux/xarray.h>\n' + include + '#include <linux/pid_namespace.h>\n')
    outputs[name] = (text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-pid-idr.c"\n#endif\n').encode()
    outputs['kernel/lsf-cleanup-pid.c'] = private_pid().encode()
    outputs['lib/lsf-cleanup-pid-radix.c'] = private_radix().encode()
    outputs['lib/lsf-cleanup-pid-idr.c'] = private_idr().encode()
    outputs['include/net/lsf_stream_cleanup_pid.h'] = (OWNED / 'cleanup-pid-private.h').read_bytes()
    outputs['net/factory-cleanup-pid.c'] = (OWNED / 'factory-cleanup-pid.c').read_bytes()
    return outputs
