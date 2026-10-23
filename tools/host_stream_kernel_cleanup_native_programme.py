"""Manifest-bound native FD source composition for the isolated VM owner.

This module runs no compiler/kernel/VM. Production consumer remains NULL.
"""
from pathlib import Path
import hashlib
from tools import host_stream_kernel_cleanup_constructor_programme as prior
from tools import host_stream_kernel_cleanup_native as change
from tools import host_stream_kernel_constructor_failure as failure_observation
from tools import host_stream_kernel_stack_alignment as stack_alignment
from tools import host_stream_kernel_vmap_extent as vmap_extent
from tools import host_stream_kernel_vmap_fit as vmap_fit
from tools import host_stream_kernel_task_identity_geometry as task_identity_geometry

ROOT = prior.ROOT
baseline = prior.baseline
require = prior.require
baseline_source = prior.baseline_source
source_names = prior.source_names
source_fixture_configuration = prior.source_fixture_configuration


def repair_sidcache(outputs):
    """Remove only the byte-identical application block cloned with Root drain.

    The historical cleanup transform copied from the first cache-size #if,
    including the original callbacks before the device-specific detach block.
    Keep frozen historical derivations intact; repair their exact final output
    here without changing the ordinary, PCI or Root retirement bodies.
    """
    name = 'security/selinux/ss/lsf_sidcache_private.c'
    raw = outputs[name]
    require(len(raw) == 7701 and hashlib.sha256(raw).hexdigest() ==
        'cf50d5c92b204410d2239b220873cf7df81f438f3953f4bf7f03cdce993d695f',
        'cleanup-native-sidcache-duplicate-preimage')
    text = raw.decode()
    ordinary = (change.OWNED/'sidcache-private.c').read_text()
    ordinary = ordinary[ordinary.index('#if CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE > 0\n'):]
    require(text.count(ordinary) == 2, 'cleanup-native-two-identical-sidcache-blocks')
    duplicate = text.rindex(ordinary)
    repaired = text[:duplicate] + text[duplicate+len(ordinary):]
    for symbol in ('lsf_prepaid_sidcache_callback', 'lsf_prepaid_sidcache_retire',
            'lsf_prepaid_sidcache_destroy'):
        require(repaired.count('static ' + ('bool ' if symbol.endswith('destroy') else 'void ') +
            symbol + '(') == 1, 'cleanup-native-single-sidcache-callback')
    for symbol in ('lsf_prepaid_sidcache_detach', 'lsf_prepaid_device_sidcache_detach',
            'lsf_prepaid_cleanup_sidcache_detach'):
        require(repaired.count('void ' + symbol + '(') == 2,
            'cleanup-native-both-sidcache-profile-branches')
    result = dict(outputs)
    result[name] = repaired.encode()
    return result


def initialize_observers(outputs):
    """Run the existing complete seal transaction before any backing birth.

    The frozen source helper used to be defined without an actual call site.
    Only never-born backing paths may undo these original subsystem seals;
    post-birth refusal/close retains them with the actual Root graph.
    """
    name = 'net/factory.c'
    raw = outputs[name]
    require(len(raw) == 34043 and hashlib.sha256(raw).hexdigest() ==
        '65847a51bff14b04664fba9db0b6d20ffb5c30708e2528f93bc1eb539f379d75',
        'cleanup-native-observer-open-preimage')
    text = change.replace(raw.decode(),
        '    error = lsf_factory_device_uevent_bank_enter();\n'
        '    if (error)\n        goto out;\n',
        '    error = lsf_cleanup_observers_prebank_enter();\n'
        '    if (error)\n        goto out;\n'
        '    error = lsf_factory_device_uevent_bank_enter();\n'
        '    if (error) {\n'
        '        if (lsf_cleanup_observers_prebank_rollback())\n'
        '            WRITE_ONCE(factory.uncertain, 1);\n'
        '        goto out;\n    }\n')
    text = change.replace(text,
        '        lsf_factory_device_uevent_bank_allocation_failed();\n'
        '        error = -ENOMEM;\n',
        '        lsf_factory_device_uevent_bank_allocation_failed();\n'
        '        if (lsf_cleanup_observers_prebank_rollback())\n'
        '            WRITE_ONCE(factory.uncertain, 1);\n'
        '        error = -ENOMEM;\n')
    result = dict(outputs)
    result[name] = text.encode()
    return result


def diagnose_task_reserve(raw):
    """Split only original short-circuit refusal edges; emit after unlock."""
    text = raw.decode()
    old = change.function(text, 'int lsf_factory_cleanup_task_reserve(')
    new = change.replace(old, '    unsigned int i, empty = 0;\n',
        '    unsigned int i, empty = 0, refusal = 0;\n')
    new = change.replace(new, '    if (!source || !request_address)\n        return result;\n',
        '    if (!source || !request_address)\n'
        '        return lsf_factory_cleanup_prebirth_refused(LSF_REFUSE_OUTPUT, task_bytes, alignment);\n')
    new = change.replace(new,
        '        request_bytes != actual_request_bytes ||\n'
        '        lsf_prepaid_cleanup_task_geometry(&actual_task_bytes, &actual_alignment) ||\n',
        '        request_bytes != actual_request_bytes)\n'
        '        return lsf_factory_cleanup_prebirth_refused(LSF_REFUSE_GEOMETRY_INPUT, task_bytes, alignment);\n'
        '    if (lsf_prepaid_cleanup_task_geometry(&actual_task_bytes, &actual_alignment))\n'
        '        return result; /* Geometry reports its sole refusal site. */\n    if (\n')
    new = change.replace(new,
        '        request_bytes > LSF_FACTORY_INFRA_BYTES || task_bytes > LSF_FACTORY_INFRA_BYTES)\n'
        '        return result;\n',
        '        request_bytes > LSF_FACTORY_INFRA_BYTES || task_bytes > LSF_FACTORY_INFRA_BYTES)\n'
        '        return lsf_factory_cleanup_prebirth_refused(LSF_REFUSE_GEOMETRY_INPUT, task_bytes, alignment);\n')
    new = change.replace(new,
        '        current->nsproxy->net_ns != factory.net ||\n'
        '        factory.device->cleanup_attempted || factory.device->pci_attempted ||\n'
        '        !lsf_device_record(&factory.pool, factory.device->key,\n'
        '            factory.device->root, LSF_DEVICE_ROOT))\n        goto out;\n',
        '        current->nsproxy->net_ns != factory.net) {\n'
        '        refusal = LSF_REFUSE_ACTOR;\n        goto out;\n    }\n'
        '    if (factory.device->cleanup_attempted || factory.device->pci_attempted) {\n'
        '        refusal = LSF_REFUSE_ONESHOT;\n        goto out;\n    }\n'
        '    if (!lsf_device_record(&factory.pool, factory.device->key,\n'
        '            factory.device->root, LSF_DEVICE_ROOT)) {\n'
        '        refusal = LSF_REFUSE_ROOT_RECORD;\n        goto out;\n    }\n')
    new = change.replace(new,
        '        factory.pool.next_generation >= (lsf_u64)-2)\n        goto out;\n',
        '        factory.pool.next_generation >= (lsf_u64)-2) {\n'
        '        refusal = LSF_REFUSE_CONTEXT;\n        goto out;\n    }\n')
    new = change.replace(new, '    if (empty < 2u)\n        goto out;\n',
        '    if (empty < 2u) {\n        refusal = LSF_REFUSE_RECORD_CAPACITY;\n        goto out;\n    }\n')
    new = change.replace(new, 'poison:\n', 'poison:\n    refusal = LSF_REFUSE_INVARIANT;\n')
    new = change.replace(new, '    spin_unlock_irqrestore(&pool_lock, flags);\n    return result;\n',
        '    spin_unlock_irqrestore(&pool_lock, flags);\n'
        '    if (refusal)\n        return lsf_factory_cleanup_prebirth_refused(refusal, task_bytes, alignment);\n'
        '    return result;\n')
    return change.replace(text, old, new).encode()


def diagnose_prebirth_refusals(outputs):
    """Candidate-only numeric observations; original errno/admission unchanged."""
    preimages = {
        'net/factory.c': (34335, '458dd6bfecac0a3cd5aa3b6c11ee474b106d94bfb7ead050c7b45bddc9f23dd1'),
        'net/factory-cleanup-task.c': (8092, '770a58e837a41a01f9c3e89c4641ad9cd8cc6e2ae14ff3527556c865bfc55928'),
        'net/factory-cleanup-native-bootstrap.c': (10695, '788bfb774cf56030ddd42dcb4dbdea4c4ab8337c5f6538aa4285a0a6b345a8f9'),
        'kernel/lsf-cleanup-provider-queue.c': (2698, 'e32e8124f41628cbe29153e64d1a8afa80f9657b5fc9d05db1f733cafa5cf5f4'),
        'kernel/lsf-cleanup-task.c': (1503, 'a6fac2509d394ec7baaa8ebb221743b96b86ad93a417f0c95200815ee8b59f69'),
        'include/net/lsf_stream_cleanup_task.h': (1202, '9d0a29823fa68352654f790b03f07aa6bac1b7848812d02433cd58b8e0abc9a5'),
    }
    for name, (size, checksum) in preimages.items():
        require(len(outputs[name]) == size and hashlib.sha256(outputs[name]).hexdigest() == checksum,
            'cleanup-native-prebirth-diagnostic-preimage')
    result = dict(outputs)
    name = 'include/net/lsf_stream_cleanup_task.h'
    result[name] = change.replace(result[name].decode(),
        'int lsf_prepaid_cleanup_worker_create(void);\n#endif\n',
        '''int lsf_prepaid_cleanup_worker_create(void);
enum lsf_cleanup_prebirth_refusal {
    LSF_REFUSE_DEBUG_LOCK = 1, LSF_REFUSE_PROFILE, LSF_REFUSE_QUEUE,
    LSF_REFUSE_TASK_GEOMETRY, LSF_REFUSE_OUTPUT, LSF_REFUSE_GEOMETRY_INPUT,
    LSF_REFUSE_ACTOR, LSF_REFUSE_ONESHOT, LSF_REFUSE_ROOT_RECORD,
    LSF_REFUSE_CONTEXT, LSF_REFUSE_RECORD_CAPACITY, LSF_REFUSE_INVARIANT
};
int lsf_factory_cleanup_prebirth_refused(unsigned int, unsigned long, unsigned long);
#endif
''').encode()
    name = 'net/factory.c'
    result[name] = change.replace(result[name].decode(), '#include <linux/init.h>\n',
        '#include <linux/init.h>\n#include <linux/printk.h>\n').encode()
    name = 'net/factory-cleanup-native-bootstrap.c'
    result[name] += b'''
/* No addresses, payload, paths or new authority. The ordinary committed
 * constructor predicate remains zero; only the exact isolated image enables it. */
int lsf_factory_cleanup_prebirth_refused(unsigned int site, unsigned long bytes,
    unsigned long alignment)
{
    if (lsf_factory_constructor_qualification())
        pr_info("LSFVM1 constructor-refusal site=%u task-bytes=%lu alignment=%lu\\n",
            site, bytes, alignment);
    return -EOPNOTSUPP;
}
'''
    name = 'kernel/lsf-cleanup-provider-queue.c'
    result[name] = change.replace(result[name].decode(),
        '    if (IS_ENABLED(CONFIG_DEBUG_LOCK_ALLOC) || !lsf_factory_cleanup_provider_profile_ready() ||\n'
        '        !lsf_prepaid_cleanup_provider_queue_available())\n        return -EOPNOTSUPP;\n',
        '    if (IS_ENABLED(CONFIG_DEBUG_LOCK_ALLOC))\n'
        '        return lsf_factory_cleanup_prebirth_refused(LSF_REFUSE_DEBUG_LOCK, 0, 0);\n'
        '    if (!lsf_factory_cleanup_provider_profile_ready())\n'
        '        return lsf_factory_cleanup_prebirth_refused(LSF_REFUSE_PROFILE, 0, 0);\n'
        '    if (!lsf_prepaid_cleanup_provider_queue_available())\n'
        '        return lsf_factory_cleanup_prebirth_refused(LSF_REFUSE_QUEUE, 0, 0);\n').encode()
    name = 'kernel/lsf-cleanup-task.c'
    text = result[name].decode()
    old = change.function(text, 'int lsf_prepaid_cleanup_task_geometry(')
    new = change.replace(old, '        return -EOPNOTSUPP;\n',
        '        return lsf_factory_cleanup_prebirth_refused(LSF_REFUSE_TASK_GEOMETRY,\n'
        '            actual_bytes, actual_alignment);\n')
    result[name] = change.replace(text, old, new).encode()
    result['net/factory-cleanup-task.c'] = diagnose_task_reserve(result['net/factory-cleanup-task.c'])
    return result


def repair_task_geometry(outputs):
    """Use the original x86 boot-selected FPU tail, not its static maximum.

    Linux6.12.113 fpu__init_task_struct_size subtracts the static register
    storage and adds fpu_kernel_cfg.default_size. The ordinary task slab and
    arch_dup_task_struct use that exact arch_task_struct_size, which can be
    smaller than sizeof(task_struct). Retain an exact equality check here.
    """
    name = 'kernel/lsf-cleanup-task.c'
    text = outputs[name].decode()
    old = change.function(text, 'int lsf_prepaid_cleanup_task_geometry(')
    expected = '''int lsf_prepaid_cleanup_task_geometry(unsigned long *bytes, unsigned long *alignment)
{
    unsigned long actual_bytes = arch_task_struct_size;
    unsigned long actual_alignment = max_t(int, L1_CACHE_BYTES, ARCH_MIN_TASKALIGN);
    if (!bytes || !alignment || actual_bytes < sizeof(struct task_struct) ||
        actual_bytes > LSF_FACTORY_INFRA_BYTES || !actual_alignment ||
        actual_alignment > 64u || (actual_alignment & (actual_alignment - 1u)))
        return lsf_factory_cleanup_prebirth_refused(LSF_REFUSE_TASK_GEOMETRY,
            actual_bytes, actual_alignment);
    *bytes = actual_bytes;
    *alignment = actual_alignment;
    return 0;
}
'''
    require(old == expected, 'cleanup-native-dynamic-task-geometry-preimage')
    new = change.replace(old,
        '    unsigned long actual_bytes = arch_task_struct_size;\n',
        '    unsigned long actual_bytes = arch_task_struct_size;\n'
        '    unsigned long expected_bytes = sizeof(struct task_struct) -\n'
        '        sizeof(current->thread.fpu.__fpstate.regs) + fpu_kernel_cfg.default_size;\n')
    new = change.replace(new,
        '    if (!bytes || !alignment || actual_bytes < sizeof(struct task_struct) ||\n',
        '    if (!bytes || !alignment || !fpu_kernel_cfg.default_size ||\n'
        '        actual_bytes != expected_bytes ||\n')
    result = dict(outputs)
    result[name] = ('#include <asm/fpu/types.h>\n' + change.replace(text, old, new)).encode()
    require([key for key in result if result[key] != outputs[key]] == [name],
        'cleanup-native-only-dynamic-task-geometry-delta')
    return result


def compose(base, originals, config):
    parent = prior.compose(base, originals, config)
    result = change.transform(parent, {})
    require(len(parent) == 322 and len(result) == 323 and
        sum(parent.get(name) != raw for name, raw in result.items()) == 6,
        'cleanup-native-exact-six-source-delta')
    repaired = repair_task_geometry(diagnose_prebirth_refusals(initialize_observers(repair_sidcache(result))))
    return task_identity_geometry.transform(vmap_fit.transform(vmap_extent.transform(
        stack_alignment.transform(failure_observation.transform(repaired)))))


def qualification_projection(outputs, config):
    # Preserve the complete selected config byte-for-byte here. A VM owner may
    # need additional boot options only as a separately reviewed explicit diff.
    require(type(config) is bytes and b'CONFIG_HZ=1000\n' in config and
        b'CONFIG_X86_64=y\n' in config and b'CONFIG_NR_CPUS=64\n' in config,
        'cleanup-native-selected-configuration')
    projected = change.qualification_projection(outputs)
    def identity(raw):
        return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    name = 'net/factory-private.h'
    proof = dict(schemaVersion='lsf.kernel-cleanup-native-candidate-projection.v1',
        sourceDifference={name:dict(preimage=identity(outputs[name]), postimage=identity(projected[name]))},
        configuration=identity(config), configurationDifference={},
        normalConstructorPredicate=0, candidateConstructorPredicate=1,
        productionSocketConsumerSelected=False, finalFreeCertificate=False,
        completeAllocationClosure=False, productionInstallation=False)
    return projected, proof


def local_freeze():
    result = prior.local_freeze()
    for path in (Path(__file__), Path(change.__file__), Path(failure_observation.__file__),
            Path(stack_alignment.__file__), Path(vmap_extent.__file__), Path(vmap_fit.__file__),
            Path(task_identity_geometry.__file__), change.FIXTURE,
            change.OWNED/'factory-cleanup-native-bootstrap.c'):
        result[path.relative_to(ROOT).as_posix()] = baseline.objects.identity(path)
    return result
