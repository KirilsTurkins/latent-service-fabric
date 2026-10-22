"""One fixed finite hosted source/geometry/atomic programme; no installation."""
import hashlib
from pathlib import Path
from tools import qualify_host_stream_kernel_cleanup_stack as baseline
from tools import host_stream_kernel_cleanup_lifecycle as lifecycle
from tools import host_stream_kernel_cleanup_entry as entry
from tools import host_stream_kernel_cleanup_irq as irq
from tools import host_stream_kernel_cleanup_descendants as descendants
from tools import host_stream_kernel_cleanup_pid as pid
from tools import host_stream_kernel_cleanup_constructor as constructor
from tools import host_stream_kernel_cleanup_security as security
from tools import host_stream_kernel_cleanup_perf as perf
from tools import host_stream_kernel_cleanup_audit as audit
from tools import host_stream_kernel_cleanup_clone as clone
from tools import host_stream_kernel_cleanup_io as io
from tools import host_stream_kernel_cleanup_cgroup as cgroup
from tools import host_stream_kernel_cleanup_association as association
from tools import host_stream_kernel_cleanup_close as close
from tools import host_stream_kernel_cleanup_observer as observer
from tools import host_stream_kernel_cleanup_worker_operations as worker_operations
from tools import host_stream_kernel_cleanup_provider_operation as provider_operation
from tools import host_stream_kernel_cleanup_provider_executor as provider_executor
from tools import host_stream_kernel_cleanup_provider_birth as provider_birth
from tools import host_stream_kernel_cleanup_provider_initialize as provider_initialize
from tools import host_stream_kernel_cleanup_provider_retirement as provider_retirement
from tools import host_stream_kernel_cleanup_provider_queue as provider_queue
from tools import host_stream_kernel_cleanup_provider_nonfinal as provider_nonfinal
from tools import host_stream_kernel_cleanup_exit_observer as exit_observer

ROOT = Path(__file__).resolve().parents[1]
require = baseline.require
STAGES = (lifecycle, entry, irq, descendants, pid, constructor, security, perf,
    audit, clone, io, cgroup, association, close, observer, worker_operations,
    provider_operation, provider_executor, provider_birth, provider_initialize,
    provider_retirement, provider_queue, provider_nonfinal, exit_observer)


def source_names():
    return {name for stage in STAGES for name in stage.preimages()['source']}


def compose(base, originals, config):
    """Every stage consumes its exact whole originals and pinned parent bytes."""
    outputs = dict(base)
    require(len(outputs) == 208, 'cleanup-programme-original-stack-membership')
    for stage in STAGES:
        inputs = {name: config if name == 'selected.config' else originals[name]
            for name in stage.preimages()['source']}
        outputs = stage.transform(outputs, inputs)
    require(len(outputs) == 322, 'cleanup-programme-full-source-membership')
    return outputs


def baseline_source(tree, original):
    # Keep the old recipe byte-exact. Its fixed historical 138-source count
    # cannot describe this new checkout's additional C/H files, so this new
    # recipe uses the same validated old transforms with its own full freeze.
    derived, frozen, selected = baseline.objects.recipient_derive_frozen(tree, original)
    require(len(derived) == 189 and len(selected) == 161,
        'cleanup-programme-original-recipient-membership')
    modules = (baseline.retirement_source, baseline.task_source, baseline.source)
    members = {path for module in modules for path in
        (Path(module.__file__).resolve(), module.FIXTURE.resolve())}
    before = {path.relative_to(ROOT).as_posix(): baseline.objects.identity(path) for path in members}
    extras = baseline.task_source.EXTRAS | set(baseline.source.preimages()['source'])
    require(len(extras) == 12 and not extras & set(selected),
        'cleanup-programme-original-stack-extracted-membership')
    selected = dict(selected)
    for name in sorted(extras):
        selected[name] = baseline.paths.read(tree,name,baseline.maintained.MAX_FILE)
    derived = baseline.retirement_source.transform(derived)
    derived = baseline.task_source.transform(derived,
        {name:selected[name] for name in baseline.task_source.EXTRAS})
    derived = baseline.source.transform(derived,
        {name:selected[name] for name in baseline.source.preimages()['source']})
    require(len(derived) == 208 and len(selected) == 173 and all(
        baseline.objects.identity(ROOT/name) == bound for name,bound in before.items()),
        'cleanup-programme-original-stack-freeze')
    return derived,{**frozen,**before},selected


def local_freeze():
    # Explicit source families, bounded by the reviewed selected Linux lineage.
    # The resulting full path/hash map is frozen before derivation and checked
    # after the entire finite job. It is provenance, not allocation authority.
    names = {ROOT/'tools/host_stream_kernel_cleanup_programme.py',
        ROOT/'tools/host_stream_kernel_cleanup_atomic_control.py'}
    for stage in STAGES:
        names.update((Path(stage.__file__).resolve(), stage.FIXTURE.resolve()))
    owned = ROOT/'research/standard-outbound/linux-6.12-lineage'
    names.update(path for path in owned.iterdir() if path.suffix in ('.c','.h'))
    require(len(names) <= 512 and all(ROOT in name.parents for name in names),
        'cleanup-programme-local-source-boundary')
    return {name.relative_to(ROOT).as_posix(): baseline.objects.identity(name) for name in sorted(names)}


GEOMETRY = {key: (name, tuple(fields)) for key,(name,fields) in baseline.GEOMETRY.items()}
GEOMETRY['net/factory.o'] = ('lsf_cleanup_geometry_factory', (
    *GEOMETRY['net/factory.o'][1],
    ('firmwareBytes','sizeof(struct lsf_factory_device_firmware)'),
    ('factoryFixedBytes','sizeof(factory) + sizeof(lsf_device_uevent_taps) + 2u * sizeof(void *)')))
GEOMETRY['kernel/fork.o'] = ('lsf_cleanup_geometry_task', (
    *GEOMETRY['kernel/fork.o'][1],
    ('sighandBytes','sizeof(struct lsf_cleanup_sighand)'),
    ('signalBytes','sizeof(struct signal_struct)'),
    ('delayBytes','sizeof(struct task_delay_info)')))
GEOMETRY.update({
    'kernel/workqueue.o': ('lsf_cleanup_geometry_provider', (
        ('poolBytes','sizeof(struct worker_pool)'), ('poolAlignment','__alignof__(struct worker_pool)'),
        ('workerBytes','sizeof(struct worker)'), ('workerAlignment','__alignof__(struct worker)'),
        ('pwqBytes','sizeof(struct pool_workqueue)'), ('pwqAlignment','__alignof__(struct pool_workqueue)'),
        ('attrsBytes','sizeof(struct workqueue_attrs)'), ('attrsAlignment','__alignof__(struct workqueue_attrs)'),
        ('controlBytes','sizeof(struct lsf_cleanup_provider_control)'),
        ('controlAlignment','__alignof__(struct lsf_cleanup_provider_control)'),
        ('contextMaximumBytes','struct_size((struct apply_wqattrs_ctx *)NULL, pwq_tbl, NR_CPUS)'),
        ('contextAlignment','__alignof__(struct apply_wqattrs_ctx)'), ('cpuMaximum','NR_CPUS'))),
    'kernel/cred.o': ('lsf_cleanup_geometry_cred', (('credBytes','sizeof(struct cred)'),)),
    'kernel/pid.o': ('lsf_cleanup_geometry_pid', (('pidBytes','struct_size_t(struct pid, numbers, 1)'),)),
    'lib/radix-tree.o': ('lsf_cleanup_geometry_radix', (('nodeBytes','sizeof(struct radix_tree_node)'),)),
    'kernel/auditsc.o': ('lsf_cleanup_geometry_audit', (
        ('auditContextBytes','sizeof(struct audit_context)'), ('auditKeyBytes','AUDIT_MAX_KEY_LEN + 1u'))),
    'block/blk-ioc.o': ('lsf_cleanup_geometry_io', (('ioBytes','sizeof(struct io_context)'),)),
    'mm/mempolicy.o': ('lsf_cleanup_geometry_mpol', (('mpolBytes','sizeof(struct mempolicy)'),)),
    'drivers/acpi/osl.o': ('lsf_cleanup_geometry_acpi', (
        ('lifetimeMutexBytes','sizeof(lsf_acpi_provider_lifetime_mutex)'),
        ('registrationBytes','sizeof(lsf_acpi_provider_registration)'),
        ('adapterLockBytes','sizeof(lsf_acpi_reference_queue_lock)'),
        ('adapterLiveBytes','sizeof(lsf_acpi_reference_queue_live)'))),
    'kernel/kthread.o': ('lsf_cleanup_geometry_request', (
        *GEOMETRY['kernel/kthread.o'][1], ('irqHintBytes','sizeof(lsf_cleanup_irq_hint)'))),
    'kernel/tracepoint.o': ('lsf_cleanup_geometry_trace_seal', (
        ('tracepointSealBytes','sizeof(lsf_cleanup_tracepoint_state)'),)),
    'kernel/kprobes.o': ('lsf_cleanup_geometry_probe_seal', (
        ('kprobeSealBytes','sizeof(lsf_cleanup_kprobe_observers)'),)),
    'drivers/connector/cn_proc.o': ('lsf_cleanup_geometry_connector_seal', (
        ('connectorSealBytes','sizeof(lsf_cleanup_connector_state)'),)),
    'kernel/taskstats.o': ('lsf_cleanup_geometry_taskstats_seal', (
        ('taskstatsSealBytes','sizeof(lsf_cleanup_taskstats_state)'),)),
    'kernel/acct.o': ('lsf_cleanup_geometry_acct_seal', (
        ('acctSealBytes','sizeof(lsf_cleanup_acct_state)'),)),
})


def geometry_suffix(target):
    name, fields = GEOMETRY[target]
    return ('\n/* Compile-only actual TU layout, never installation evidence. */\n'
        'const unsigned long long ' + name + '[]\n'
        '__attribute__((used, aligned(8), section("' + baseline.GEOMETRY_SECTION + '"))) = {\n'
        '    0x4c534647454f4d31ULL, ' + str(len(fields)) + 'ULL,\n' +
        ''.join('    (unsigned long long)(' + expression + '),\n' for _,expression in fields) + '};\n').encode()


def fitting(values):
    """Exact constant subgraphs; runtime arch/LSM/cache charges remain unknown."""
    wq = values['kernel/workqueue.o']
    require(wq['cpuMaximum'] == 64, 'cleanup-programme-original-cpu-bound')
    parts = ('pool','worker','pwq','attrs','control','context')
    charged = {}
    for part in parts:
        size = wq['contextMaximumBytes' if part == 'context' else part+'Bytes']
        alignment = wq[part+'Alignment']
        require(size > 0 and 0 < alignment <= 4096 and not alignment & (alignment-1),
            'cleanup-programme-actual-provider-geometry')
        charged[part] = (size + alignment - 1 + 63) & ~63
    factory = values['net/factory.o']
    static = factory['backingBytes'] + factory['factoryFixedBytes']
    static += values['kernel/kthread.o']['irqHintBytes']
    static += sum(values['drivers/acpi/osl.o'].values())
    for target,field in (('kernel/tracepoint.o','tracepointSealBytes'),
        ('kernel/kprobes.o','kprobeSealBytes'),('drivers/connector/cn_proc.o','connectorSealBytes'),
        ('kernel/taskstats.o','taskstatsSealBytes'),('kernel/acct.o','acctSealBytes')):
        static += values[target][field]
    require((factory['backingBytes'],factory['infrastructureBytes'],factory['bootstrapCeiling'],
        factory['allocationSlots']) == (524288,196608,1048576,256), 'cleanup-programme-original-caps')
    require(sum(charged.values()) <= factory['infrastructureBytes'] and
        static <= factory['bootstrapCeiling'], 'cleanup-programme-fixed-subgraph-fit')
    return dict(providerRecordBytes=charged, providerRecordTotal=sum(charged.values()),
        providerRecords=6, maximumProviderCpuSlots=64, bootstrapBytesIncludingBank=static,
        fixedSubgraphsFit=True, runtimeArchTaskBytesKnown=False, runtimeLsmCompositeBytesKnown=False,
        wholeInfrastructureFitQualified=False, actualRuntimeGeometryExecuted=False,
        actualNativeLedger=False, consumerSelected=False, productionInstallation=False)
