"""Strict raw observation of fixed bank credit, never full native retirement."""
import re
from tools import host_stream_kernel_native_vm as native
from tools import host_stream_kernel_vm_image as image
from tools.host_stream_kernel_late_fd_vm import HANDOFF, OUTSIDE

EXAMPLE = 'crates/latent-streams/examples/kernel_bank_reclamation_vm.rs'
TARGET_NAME = 'kernel_bank_reclamation_vm'
BOOT, TERMINAL = native.BOOT, native.TERMINAL
BANK_BYTES = 512 * 1024
PASS = (b'LSFBANK1 result=PASS constructorReady=1 kernelRootReturned=1 descriptorClosed=1 '
        b'observerClosed=1 bankReservationBytes=524288 overheadReservationBytes=524288 '
        b'bankCapacityReused=1 connectionQuarantined=1 fullNativeQuotaReleased=0 productionInstalled=0')
require, identity = native.require, native.identity


def serial_observation(raw):
    require(type(raw) is bytes and 0 < len(raw) <= image.MAX_SERIAL,'bank-raw-serial-bound')
    require(not any(mark in raw for mark in (b'Kernel panic',b'BUG:',b'Oops:',b'LSFBANK1 result=FAIL')),
        'bank-kernel-or-native-failure')
    lines, positions = raw.splitlines(), {}
    for marker in (HANDOFF,image.PHYSICAL_MARKER,OUTSIDE):
        pattern = rb'(?:\[[ ]{0,10}[0-9]{1,10}\.[0-9]{6}\] )?'+re.escape(marker)
        found = [i for i,line in enumerate(lines) if re.fullmatch(pattern,line)]
        require(len(found) <= 1 and raw.count(marker) == len(found),'bank-unique-kernel-record')
        if marker == image.PHYSICAL_MARKER:require(len(found) == 1,'bank-physical-return-required')
        if found:positions[marker] = found[0]
    if HANDOFF in positions:
        require(OUTSIDE in positions and positions[HANDOFF] < positions[image.PHYSICAL_MARKER],
            'bank-pending-needs-original-outside-collector')
    if OUTSIDE in positions:
        require(positions[image.PHYSICAL_MARKER] < positions[OUTSIDE],'bank-physical-before-outside')
    rows = [line for i,line in enumerate(lines) if i not in positions.values()
        and line.startswith((b'LSFVM1 ',b'LSFBANK1 ',b'LSFRETURN1 ',b'LSFNATIVE1 '))]
    require(len(rows) == 9 and rows[0] == BOOT and rows[-2:] == [PASS,TERMINAL],
        'bank-complete-native-protocol')
    fields = ('connections','failedCleanup','cleanupJobs','pending','running','workers',
              'metadataBytes','controlFailed','descriptors','observerDescriptors')
    labels = ('baseline','ready','root-return-observed-held','quarantined',
              'bank-capacity-reused','bank-capacity-returned')
    snapshots = {}
    for name,row in zip(labels,rows[1:7]):
        pattern = rb'LSFBANK1 state='+name.encode()+b''.join(
            b' '+key.encode()+rb'=([0-9]{1,20})' for key in fields)
        match = re.fullmatch(pattern,row)
        require(match is not None,'bank-exact-native-snapshot')
        value = dict(zip(fields,map(int,match.groups())))
        require(all(number < 2**64 for number in value.values())
            and value['metadataBytes'] <= 8*1024**2 and value['connections'] <= 256
            and value['cleanupJobs'] <= 8 and value['pending'] <= 128
            and value['running'] <= 64 and value['workers'] <= 16
            and value['controlFailed'] == 0,'bank-original-counter-limits')
        snapshots[name] = value
    before,ready,held,after,reused,returned = (snapshots[name] for name in labels)
    require(before['connections'] == before['failedCleanup'] == before['descriptors']
        == before['observerDescriptors'] == 0,'bank-empty-baseline')
    require(ready['connections'] == ready['descriptors'] == ready['observerDescriptors'] == 1
        and ready['failedCleanup'] == 0 and ready['workers'] == 0
        and ready['cleanupJobs'] == before['cleanupJobs']+1
        and ready['metadataBytes'] >= before['metadataBytes']+2*BANK_BYTES+4096,
        'bank-original-total-prepaid')
    for value,jobs in ((held,ready['cleanupJobs']+1),(after,ready['cleanupJobs'])):
        require(value['connections'] == value['failedCleanup'] == 1
            and value['descriptors'] == value['observerDescriptors'] == 0
            and value['pending'] == value['running'] == value['workers'] == 0
            and value['cleanupJobs'] == jobs
            and before['metadataBytes']+BANK_BYTES+4096 <= value['metadataBytes']
                < before['metadataBytes']+2*BANK_BYTES+4096,'bank-only-partial-return')
    require(after['metadataBytes'] < held['metadataBytes'],'bank-paid-receipt-drop-observed')
    require({**reused,'metadataBytes':after['metadataBytes']} == after
        and reused['metadataBytes'] == after['metadataBytes']+BANK_BYTES
        and returned == after,'bank-original-quota-reuse-and-return')
    return {'snapshots':snapshots,'actualKernelRootReturned':True,
        'bankReservationReturnedBytes':BANK_BYTES,'bootstrapOverheadReservationRetainedBytes':BANK_BYTES,
        'originalObserverReservationRetained':True,'originalConnectionQuarantined':True,
        'originalReceiptChargeObserved':True,'actualBankCapacityReused':True,
        'observedPendingFdHandoff':HANDOFF in positions,'observedOutsideCollector':OUTSIDE in positions,
        'fullNativeQuotaReleased':False,'connectionQuotaReleased':False,
        'productionInstallation':False,'completeAllocationClosure':False,**identity(raw)}
