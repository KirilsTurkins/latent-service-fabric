"""Strict NEW observation-channel UART oracle; original readers stay unchanged.

The child obtains KernelRootReturned ONLY from the authenticated fixed observer
FD. Host UART additionally requires a genuine kernel physical-return row. The
two streams have independent delivery order; both remain mandatory.
"""
import re
from tools import host_stream_kernel_native_vm as native
from tools import host_stream_kernel_vm_image as image
from tools.host_stream_kernel_late_fd_vm import HANDOFF, OUTSIDE

EXAMPLE = 'crates/latent-streams/examples/kernel_return_observation_vm.rs'
TARGET_NAME = 'kernel_return_observation_vm'
BOOT, TERMINAL = native.BOOT, native.TERMINAL
NATIVE_PASS = (b'LSFRETURN1 result=PASS constructorReady=1 kernelRootReturned=1 descriptorClosed=1 '
               b'observerClosed=1 backingQuarantined=1 nativeQuotaReleased=0 productionInstalled=0')
identity, require = native.identity, native.require


def serial_observation(raw):
    require(type(raw) is bytes and 0 < len(raw) <= image.MAX_SERIAL, 'raw-serial-bound')
    require(not any(marker in raw for marker in (b'Kernel panic',b'BUG:',b'Oops:',b'LSFRETURN1 result=FAIL')),
        'kernel-or-native-failure')
    lines, positions = raw.splitlines(), {}
    for marker in (HANDOFF,image.PHYSICAL_MARKER,OUTSIDE):
        pattern = rb'(?:\[[ ]{0,10}[0-9]{1,10}\.[0-9]{6}\] )?'+re.escape(marker)
        found = [i for i,line in enumerate(lines) if re.fullmatch(pattern,line)]
        require(len(found) <= 1 and raw.count(marker) == len(found), 'unique-real-kernel-record')
        if marker == image.PHYSICAL_MARKER:
            require(len(found) == 1, 'actual-kernel-return-required')
        if found: positions[marker] = found[0]
    if HANDOFF in positions:
        require(OUTSIDE in positions and positions[HANDOFF] < positions[image.PHYSICAL_MARKER],
            'pending-handoff-needs-outside-collector')
    if OUTSIDE in positions:
        require(positions[image.PHYSICAL_MARKER] < positions[OUTSIDE], 'physical-before-outside')
    # printk ring commitment does not fence cross-CPU UART delivery. Preserve
    # both mandatory evidence streams without imposing an invented UART fence.
    excluded = set(positions.values())
    rows = [line for i,line in enumerate(lines) if i not in excluded
        and line.startswith((b'LSFVM1 ',b'LSFRETURN1 ',b'LSFNATIVE1 '))]
    require(len(rows) == 7 and rows[0] == BOOT and rows[-1] == TERMINAL
        and rows[-2] == NATIVE_PASS, 'complete-native-pid1-protocol')
    snapshots = {}
    fields = ('connections','failedCleanup','cleanupJobs','pending','running','workers',
              'metadataBytes','controlFailed','descriptors','observerDescriptors')
    for name,row in zip(('baseline','ready','root-return-observed-held','quarantined'),rows[1:5]):
        pattern = rb'LSFRETURN1 state='+name.encode()+b''.join(
            b' '+field.encode()+rb'=([0-9]{1,20})' for field in fields)
        match = re.fullmatch(pattern,row)
        require(match is not None, 'exact-native-snapshot')
        value = dict(zip(fields,map(int,match.groups())))
        require(all(item < 2**64 for item in value.values())
            and value['metadataBytes'] <= 8*1024**2 and value['connections'] <= 256
            and value['cleanupJobs'] <= 8 and value['pending'] <= 128
            and value['running'] <= 64 and value['workers'] <= 16
            and value['controlFailed'] == 0, 'original-native-counter-bounds')
        snapshots[name] = value
    before,ready,held,after = (snapshots[name] for name in
        ('baseline','ready','root-return-observed-held','quarantined'))
    require(before['connections'] == before['failedCleanup'] == before['descriptors'] == before['observerDescriptors'] == 0,
        'actual-native-baseline')
    require(ready['connections'] == ready['descriptors'] == ready['observerDescriptors'] == 1 and ready['failedCleanup'] == 0
        and ready['cleanupJobs'] == before['cleanupJobs']+1
        and ready['metadataBytes'] >= before['metadataBytes']+1024**2+4096, 'actual-ready-original-owner')
    require(held['connections'] == held['failedCleanup'] == 1 and held['descriptors'] == held['observerDescriptors'] == 0
        and held['cleanupJobs'] == ready['cleanupJobs']+1
        and held['pending'] == held['running'] == held['workers'] == 0
        and held['metadataBytes'] >= before['metadataBytes']+1024**2+4096,
        'actual-authenticated-root-return-receipt-charge-held')
    require(after['connections'] == after['failedCleanup'] == 1 and after['descriptors'] == after['observerDescriptors'] == 0
        and after['cleanupJobs'] == ready['cleanupJobs']
        and after['pending'] == after['running'] == after['workers'] == 0
        and before['metadataBytes']+1024**2+4096 <= after['metadataBytes'] < held['metadataBytes'],
        'original-backing-still-quarantined')
    return {'snapshots':snapshots,'actualNativeConstructorReady':True,'actualDescriptorClosed':True,
        'actualKernelRootReturn':True,'kernelPostReturnObservations':1,
        'observedPendingFdHandoff':HANDOFF in positions,'observedOutsideCollector':OUTSIDE in positions,
        'actualNativeKernelRootReturned':True,'originalObserverChargeQuarantined':True,'originalReceiptChargeObserved':True,
        'independentUartOrders':True,'originalNodeCapacityQuarantined':True,'nativeQuotaReleased':False,
        'productionInstallation':False,'completeAllocationClosure':False,**identity(raw)}
