"""Closed userspace image and actual native/physical UART reader; no refund."""
import hashlib
import re

from tools import host_stream_kernel_vm_image as image
from tools.host_stream_kernel_late_fd_vm import HANDOFF, OUTSIDE
from tools.diagnose_host_stream_kernel_vm import replace_init
from tools.rust_capsule_project import ROOT, read_file

EXAMPLE = 'crates/latent-streams/examples/kernel_constructor_vm.rs'
SUPERVISOR = 'research/standard-outbound/linux-6.12-lineage/native-constructor-vm-init.c'
ORIGINAL = 'research/standard-outbound/linux-6.12-lineage/constructor-vm-init.c'
COMPILED_CONTROLS = b'LSFNATIVE1 kmsg-controls=PASS cases=12\n'
BOOT = b'LSFVM1 boot=native-constructor-only production-sockets=disabled'
TERMINAL = b'LSFVM1 result=PASS stage=actual-native-constructor-and-kernel-return'
NATIVE_PASS = (b'LSFNATIVE1 result=PASS constructorReady=1 descriptorClosed=1 '
               b'backingQuarantined=1 nativeQuotaReleased=0 productionInstalled=0')


def require(value, reason):
    if not value:
        raise ValueError('native-constructor-vm-'+reason)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def supervisor_source(wrapper=None, original=None):
    wrapper = read_file(ROOT/SUPERVISOR, 64*1024) if wrapper is None else wrapper
    original = read_file(ROOT/ORIGINAL, 64*1024) if original is None else original
    anchor = b'#include "constructor-vm-init.c"\n'
    require(type(wrapper) is bytes and type(original) is bytes and wrapper.count(anchor) == 1
        and 0 < len(wrapper)+len(original) <= 64*1024, 'exact-supervisor-composition')
    return wrapper.replace(anchor, original)


def native_initramfs(original, old_init, supervisor, native):
    """Preserve qualified newc entries; replace init and add only two fixed names.

    Reuses the maintained pure replacement reader, never its diagnostic campaign.
    No filesystem extractor or new general-purpose archive writer is exposed.
    """
    image.init_elf(supervisor)
    image.init_elf(native)
    changed = replace_init(original, old_init, supervisor)
    position, headers, inodes = 0, {}, []
    for name in ('dev','dev/console','proc','sys','init','TRAILER!!!'):
        start = position
        header = changed[position:position+110]
        fields = [int(header[6+i*8:14+i*8],16) for i in range(13)]
        position += 110
        require(changed[position:position+fields[11]] == name.encode()+b'\0', 'fixed-newc-name')
        position = (position+fields[11]+3)&~3
        position = (position+fields[6]+3)&~3
        headers[name] = header
        inodes.append(fields[0])
        if name == 'TRAILER!!!':
            trailer = changed[start:position]
            result = bytearray(changed[:start])
    next_inode = max(inodes)+1
    require(next_inode+1 < 2**32, 'fixed-newc-inode-range')
    for index, (name, payload, template, mode) in enumerate((
            ('tmp', b'', 'sys', 0o41777),
            ('native-init', native, 'init', 0o100755))):
        header = bytearray(headers[template])
        for offset, value in ((6,next_inode+index),(14,mode),(54,len(payload)),(94,len(name)+1)):
            header[offset:offset+8] = f'{value:08X}'.encode()
        result.extend(header)
        result.extend(name.encode()+b'\0'); result.extend(bytes((-len(result))%4))
        result.extend(payload); result.extend(bytes((-len(result))%4))
    result.extend(trailer); result.extend(bytes((-len(result))%512))
    require(0 < len(result) <= image.MAX_INITRAMFS, 'unchanged-initramfs-byte-bound')
    return bytes(result)


def serial_observation(raw):
    require(type(raw) is bytes and 0 < len(raw) <= image.MAX_SERIAL, 'raw-serial-bound')
    require(not any(marker in raw for marker in (b'Kernel panic',b'BUG:',b'Oops:',b'LSFNATIVE1 result=FAIL')),
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
        and line.startswith((b'LSFVM1 ',b'LSFNATIVE1 '))]
    require(len(rows) == 6 and rows[0] == BOOT and rows[-1] == TERMINAL
        and rows[-2] == NATIVE_PASS, 'complete-native-pid1-protocol')
    snapshots = {}
    fields = ('connections','failedCleanup','cleanupJobs','pending','running','workers',
              'metadataBytes','controlFailed','descriptors')
    for name,row in zip(('baseline','ready','quarantined'),rows[1:4]):
        pattern = rb'LSFNATIVE1 state='+name.encode()+b''.join(
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
    before,ready,after = (snapshots[name] for name in ('baseline','ready','quarantined'))
    require(before['connections'] == before['failedCleanup'] == before['descriptors'] == 0,
        'actual-native-baseline')
    require(ready['connections'] == ready['descriptors'] == 1 and ready['failedCleanup'] == 0
        and ready['cleanupJobs'] == before['cleanupJobs']+1
        and ready['metadataBytes'] >= before['metadataBytes']+1024**2, 'actual-ready-original-owner')
    require(after['connections'] == after['failedCleanup'] == 1 and after['descriptors'] == 0
        and after['cleanupJobs'] == ready['cleanupJobs']
        and after['pending'] == after['running'] == after['workers'] == 0
        and after['metadataBytes'] >= before['metadataBytes']+1024**2, 'original-backing-still-quarantined')
    return {'snapshots':snapshots,'actualNativeConstructorReady':True,'actualDescriptorClosed':True,
        'actualKernelRootReturn':True,'kernelPostReturnObservations':1,
        'observedPendingFdHandoff':HANDOFF in positions,'observedOutsideCollector':OUTSIDE in positions,
        'independentUartOrders':True,'originalNodeCapacityQuarantined':True,'nativeQuotaReleased':False,
        'productionInstallation':False,'completeAllocationClosure':False,**identity(raw)}
