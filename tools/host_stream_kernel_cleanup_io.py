"""Actual selected non-ICQ I/O-context births, permission path and final put."""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_clone as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_io.json'
FIXTURE_SHA = 'f9c12d5161d3e635a5989ae5cb33263387a32be339a2972d8220ea1f945c9b6c'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 32 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-io-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-io-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        value['sourceProtocol'] == 'exact-official-upstream-git-blobs-plus-actual-selected-config' and
        len(value['source']) == 3 and len(value['sections']) == 4 and len(value['parentDerived']) == 6 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'runtimeIoExecution', 'bootstrapQualified', 'fullConstructorClosure',
            'completeAllocationClosure', 'productionInstallation')),
        'cleanup-io-source-origin')
    return value


def definition(name):
    return preimages()['sections'][name]['text']


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-io-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-io-whole-source')
        if 'gitBlob' in expected:
            require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() ==
                expected['gitBlob'], 'cleanup-io-upstream-git-blob')
    config = inputs['selected.config'].decode()
    require('CONFIG_BLOCK=y\n' in config and 'CONFIG_MQ_IOSCHED_DEADLINE=y\n' in config and
        'CONFIG_MQ_IOSCHED_KYBER=y\n' in config and '# CONFIG_IOSCHED_BFQ is not set\n' in config and
        not any(line.startswith('CONFIG_BLK_ICQ=') for line in config.splitlines()),
        'cleanup-io-actual-selected-non-icq-profile')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-io-definition-preimage')


def private_io():
    allocation = replace(definition('alloc_io_context'),
        'static struct io_context *alloc_io_context(gfp_t gfp_flags, int node)\n',
        'static struct io_context *lsf_cleanup_alloc_io_context(struct task_struct *target,\n'
        '    gfp_t gfp_flags, int node)\n')
    allocation = replace(allocation, '\tstruct io_context *ioc;\n',
        '\tstruct io_context *ioc;\n\tvoid *address;\n\tint origin;\n')
    allocation = replace(allocation,
        '\tioc = kmem_cache_alloc_node(iocontext_cachep, gfp_flags | __GFP_ZERO,\n'
        '\t\t\t\t    node);\n',
        '\torigin = lsf_factory_cleanup_io_reserve(target, sizeof(*ioc), __alignof__(*ioc), &address);\n'
        '\tif (!origin)\n\t\treturn alloc_io_context(gfp_flags, node);\n'
        '\tif (origin < 0)\n\t\treturn NULL;\n\tioc = address;\n')
    copy = replace(definition('copy_io'),
        'int __copy_io(unsigned long clone_flags, struct task_struct *tsk)\n',
        'int lsf_prepaid_cleanup_copy_io(struct lsf_cleanup_task_source source,\n'
        '    unsigned long clone_flags, struct task_struct *tsk)\n')
    copy = replace(copy, '\tstruct io_context *ioc = current->io_context;\n',
        '\tstruct io_context *ioc;\n\tunsigned short ioprio = 0;\n\n'
        '\tif (clone_flags != LSF_CLEANUP_CLONE_FLAGS || IS_ENABLED(CONFIG_BLK_ICQ) ||\n'
        '\t    !lsf_factory_cleanup_constructor_current(source, tsk))\n\t\treturn -EOPNOTSUPP;\n'
        '\t/* Actual source alloc_lock serializes external set_task_ioprio.\n'
        '\t * Copy the scalar while held; retain no borrowed IOC pointer use. */\n'
        '\ttask_lock(current);\n\tioc = current->io_context;\n'
        '\tif (ioc)\n\t\tioprio = ioc->ioprio;\n\ttask_unlock(current);\n'
        '\tif (!ioc)\n\t\treturn 0;\n')
    copy = replace(copy, 'ioprio_valid(ioc->ioprio)', 'ioprio_valid(ioprio)')
    copy = replace(copy, 'alloc_io_context(GFP_KERNEL, NUMA_NO_NODE)',
        'lsf_cleanup_alloc_io_context(tsk, GFP_KERNEL, NUMA_NO_NODE)')
    copy = replace(copy, '\t\ttsk->io_context->ioprio = ioc->ioprio;\n',
        '\t\ttsk->io_context->ioprio = ioprio;\n')
    geometry = '''int lsf_prepaid_cleanup_io_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || IS_ENABLED(CONFIG_BLK_ICQ))
        return -EOPNOTSUPP;
    *bytes = sizeof(struct io_context);
    *alignment = __alignof__(struct io_context);
    return 0;
}
'''
    return geometry + '\n' + allocation + '\n' + copy


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-io-parent-preimage')
    outputs = dict(outputs)
    include = '#include <net/lsf_stream_cleanup_io.h>\n'
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_clone.h>\n',
        '#include <net/lsf_stream_cleanup_clone.h>\n' + include)
    outputs[name] = replace(text, '#include "factory-cleanup-clone.c"\n',
        '#include "factory-cleanup-clone.c"\n#include "factory-cleanup-io.c"\n').encode()
    name = 'include/net/lsf_stream_cleanup_descendants.h'
    outputs[name] = replace(outputs[name].decode(), '    LSF_CLEANUP_CHILD_KINDS\n',
        '    LSF_CLEANUP_IO_CONTEXT,\n    LSF_CLEANUP_CHILD_KINDS\n').encode()
    name = 'net/device-prepaid.h'
    text = replace(outputs[name].decode(), '    LSF_DEVICE_CLEANUP_AUDIT_KEY,\n',
        '    LSF_DEVICE_CLEANUP_AUDIT_KEY,\n    LSF_DEVICE_CLEANUP_IO_CONTEXT,\n')
    outputs[name] = replace(text,
        '        kind == LSF_DEVICE_CLEANUP_AUDIT_CONTEXT || kind == LSF_DEVICE_CLEANUP_AUDIT_KEY ||\n',
        '        kind == LSF_DEVICE_CLEANUP_AUDIT_CONTEXT || kind == LSF_DEVICE_CLEANUP_AUDIT_KEY ||\n'
        '        kind == LSF_DEVICE_CLEANUP_IO_CONTEXT ||\n').encode()
    name = 'net/factory-cleanup-descendants.c'
    outputs[name] = replace(outputs[name].decode(),
        '    case LSF_CLEANUP_AUDIT_KEY: return LSF_DEVICE_CLEANUP_AUDIT_KEY;\n',
        '    case LSF_CLEANUP_AUDIT_KEY: return LSF_DEVICE_CLEANUP_AUDIT_KEY;\n'
        '    case LSF_CLEANUP_IO_CONTEXT: return LSF_DEVICE_CLEANUP_IO_CONTEXT;\n').encode()
    name = 'kernel/lsf-cleanup-descendants.c'
    text = replace(outputs[name].decode(), '    case LSF_CLEANUP_PID:\n',
        '    case LSF_CLEANUP_IO_CONTEXT:\n#ifdef CONFIG_BLOCK\n'
        '        return lsf_prepaid_cleanup_io_geometry(bytes, alignment);\n'
        '#else\n        return -EOPNOTSUPP;\n#endif\n'
        '    case LSF_CLEANUP_PID:\n')
    outputs[name] = (include + text).encode()
    name = 'kernel/lsf-cleanup-constructor.c'
    text = replace(outputs[name].decode(), '\tretval = copy_io(clone_flags, p);\n',
        '#ifdef CONFIG_BLOCK\n\tretval = lsf_prepaid_cleanup_copy_io(source, clone_flags, p);\n'
        '#else\n\tretval = copy_io(clone_flags, p);\n#endif\n')
    outputs[name] = (include + text).encode()
    name = 'block/blk-ioc.c'
    text = inputs[name].decode()
    original = definition('put_io_context')
    updated = replace(original, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_cleanup_child_live(ioc, LSF_CLEANUP_IO_CONTEXT) < 0)\n\t\treturn;\n#endif\n')
    updated = replace(updated,
        '\tif (atomic_long_dec_and_test(&ioc->refcount) && !ioc_delay_free(ioc))\n'
        '\t\tkmem_cache_free(iocontext_cachep, ioc);\n',
        '\tif (atomic_long_dec_and_test(&ioc->refcount) && !ioc_delay_free(ioc)) {\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (lsf_factory_cleanup_child_finish(ioc, LSF_CLEANUP_IO_CONTEXT))\n\t\t\treturn;\n#endif\n'
        '\t\tkmem_cache_free(iocontext_cachep, ioc);\n\t}\n')
    text = replace(text, original, updated)
    original = definition('set_task_ioprio')
    updated = replace(original, '\t\tioc = alloc_io_context(GFP_ATOMIC, NUMA_NO_NODE);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tioc = lsf_cleanup_alloc_io_context(task, GFP_ATOMIC, NUMA_NO_NODE);\n'
        '#else\n\t\tioc = alloc_io_context(GFP_ATOMIC, NUMA_NO_NODE);\n#endif\n')
    updated = replace(updated,
        '\t\tif (task->io_context)\n\t\t\tkmem_cache_free(iocontext_cachep, ioc);\n\t\telse\n',
        '\t\tif (task->io_context) {\n\t\t\tkmem_cache_free(iocontext_cachep, ioc);\n\t\t} else\n')
    # Original raced/exit allocations use their real physical cache boundary.
    updated = replace(updated, '\t\t\tkmem_cache_free(iocontext_cachep, ioc);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\t\tif (!lsf_factory_cleanup_child_finish(ioc, LSF_CLEANUP_IO_CONTEXT))\n#endif\n'
        '\t\t\t\tkmem_cache_free(iocontext_cachep, ioc);\n', 2)
    text = replace(text, original, updated)
    # The actual set-ioprio body precedes the private implementation.
    text = replace(text, 'int set_task_ioprio(struct task_struct *task, int ioprio)\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'static struct io_context *lsf_cleanup_alloc_io_context(struct task_struct *, gfp_t, int);\n'
        '#endif\nint set_task_ioprio(struct task_struct *task, int ioprio)\n')
    outputs[name] = (include + text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-io.c"\n#endif\n').encode()
    outputs['include/linux/iocontext.h'] = inputs['include/linux/iocontext.h']
    outputs['block/lsf-cleanup-io.c'] = private_io().encode()
    outputs['net/factory-cleanup-io.c'] = (OWNED / 'factory-cleanup-io.c').read_bytes()
    outputs['include/net/lsf_stream_cleanup_io.h'] = (OWNED / 'cleanup-io-private.h').read_bytes()
    return outputs
