"""Closed userspace image and actual native/physical UART reader; no refund."""
import hashlib
import re
import struct

from tools import host_stream_kernel_vm_image as image
from tools.host_stream_kernel_late_fd_vm import HANDOFF, OUTSIDE
from tools.diagnose_host_stream_kernel_vm import replace_init
from tools.rust_capsule_project import ROOT, read_file

EXAMPLE = 'crates/latent-streams/examples/kernel_constructor_vm.rs'
SUPERVISOR = 'research/standard-outbound/linux-6.12-lineage/native-constructor-vm-init.c'
ORIGINAL = 'research/standard-outbound/linux-6.12-lineage/constructor-vm-init.c'
MAX_NATIVE_INIT = 3 * 1024**2  # Fixed new child partition, not the PID1 limit.
COMPILED_CONTROLS = b'LSFNATIVE1 kmsg-controls=PASS cases=12\n'
BOOT = b'LSFVM1 boot=native-constructor-only production-sockets=disabled'
TERMINAL = b'LSFVM1 result=PASS stage=actual-native-constructor-and-kernel-return'
NATIVE_PASS = (b'LSFNATIVE1 result=PASS constructorReady=1 closeRequestAccepted=1 descriptorClosed=1 '
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


# Same pure grammar as the immutable PID1 validator, except this fixed child
# byte partition. A focused inverse control binds every other grammar byte.
def native_elf(raw: bytes) -> dict:
    """Reject interpreters, dynamic dependencies, writable code and huge BSS."""
    image.require(type(raw) is bytes and 64 <= len(raw) <= MAX_NATIVE_INIT, 'init-byte-bound')
    image.require(raw[:7] == b'\x7fELF\x02\x01\x01', 'init-elf64-little-endian')
    kind, machine, version, entry, phoff = struct.unpack_from('<HHIQQ', raw, 16)
    ehsize, phsize, phcount = struct.unpack_from('<HHH', raw, 52)
    image.require((kind, machine, version, ehsize, phsize) == (2, 62, 1, 64, 56)
            and 0 < phcount <= 64 and phoff >= 64
            and phoff + phcount * phsize <= len(raw), 'init-executable-header')
    spans, executable_entry = [], False
    for index in range(phcount):
        ptype, flags, offset, address, _, files, memory, alignment = struct.unpack_from(
            '<IIQQQQQQ', raw, phoff + index * phsize)
        image.require(ptype not in (2, 3), 'init-static-only')
        image.require(not (ptype == 0x6474e551 and flags & 1), 'init-executable-stack')
        if ptype != 1:
            continue
        image.require(files <= memory <= image.MAX_INIT_LOAD and offset + files <= len(raw)
                and address + memory < 2**64, 'init-load-range')
        image.require(alignment in (0, 1) or 1 < alignment <= 2 * 1024**2
                and not alignment & (alignment - 1)
                and address % alignment == offset % alignment, 'init-load-alignment')
        image.require(not (flags & 1 and flags & 2), 'init-write-execute')
        if memory:
            spans.append((address, address + memory))
        executable_entry |= bool(flags & 1 and address <= entry < address + files)
    image.require(bool(spans) and executable_entry
            and max(end for _, end in spans) - min(start for start, _ in spans) <= image.MAX_INIT_LOAD,
            'init-finite-entry-image')
    image.require(all(a_end <= b_start for (_, a_end), (b_start, _) in
                zip(sorted(spans), sorted(spans)[1:])), 'init-overlapping-loads')
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'loadSegments': len(spans), 'staticX86_64': True}


def executable_partition(supervisor, native):
    """Validate both fixed roles, then bound their combined loaded spans."""
    image.init_elf(supervisor)
    native_elf(native)

    def span(raw):
        # Only validated headers enter here: <=64 nonoverlapping finite loads.
        phoff = struct.unpack_from('<Q', raw, 32)[0]
        phcount = struct.unpack_from('<H', raw, 56)[0]
        loads = [struct.unpack_from('<IIQQQQQQ', raw, phoff+index*56)
                 for index in range(phcount)]
        ranges = [(row[3],row[3]+row[6]) for row in loads if row[0] == 1 and row[6]]
        return max(end for _,end in ranges)-min(start for start,_ in ranges)

    pid1_span, native_span = span(supervisor), span(native)
    aggregate = pid1_span+native_span
    require(aggregate <= image.MAX_INIT_LOAD, 'aggregate-executable-load-span')
    return {'pid1MaximumFileBytes':image.MAX_INIT,'nativeMaximumFileBytes':MAX_NATIVE_INIT,
        'pid1LoadSpanBytes':pid1_span,'nativeLoadSpanBytes':native_span,
        'aggregateLoadSpanBytes':aggregate,'maximumAggregateLoadSpanBytes':image.MAX_INIT_LOAD}


def native_initramfs(original, old_init, supervisor, native):
    """Preserve qualified newc entries; replace init and add only two fixed names.

    Reuses the maintained pure replacement reader, never its diagnostic campaign.
    No filesystem extractor or new general-purpose archive writer is exposed.
    """
    executable_partition(supervisor,native)
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
    require(len(rows) == 7 and rows[0] == BOOT and rows[-1] == TERMINAL
        and rows[-2] == NATIVE_PASS, 'complete-native-pid1-protocol')
    snapshots = {}
    fields = ('connections','failedCleanup','cleanupJobs','pending','running','workers',
              'metadataBytes','controlFailed','descriptors')
    for name,row in zip(('baseline','ready','close-request-accepted-held','quarantined'),rows[1:5]):
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
    before,ready,held,after = (snapshots[name] for name in
        ('baseline','ready','close-request-accepted-held','quarantined'))
    require(before['connections'] == before['failedCleanup'] == before['descriptors'] == 0,
        'actual-native-baseline')
    require(ready['connections'] == ready['descriptors'] == 1 and ready['failedCleanup'] == 0
        and ready['cleanupJobs'] == before['cleanupJobs']+1
        and ready['metadataBytes'] >= before['metadataBytes']+1024**2, 'actual-ready-original-owner')
    require(held['connections'] == held['failedCleanup'] == 1 and held['descriptors'] == 0
        and held['cleanupJobs'] == ready['cleanupJobs']+1
        and held['pending'] == held['running'] == held['workers'] == 0
        and held['metadataBytes'] >= before['metadataBytes']+1024**2,
        'actual-close-accepted-receipt-charge-held')
    require(after['connections'] == after['failedCleanup'] == 1 and after['descriptors'] == 0
        and after['cleanupJobs'] == ready['cleanupJobs']
        and after['pending'] == after['running'] == after['workers'] == 0
        and before['metadataBytes']+1024**2 <= after['metadataBytes'] < held['metadataBytes'],
        'original-backing-still-quarantined')
    return {'snapshots':snapshots,'actualNativeConstructorReady':True,'actualDescriptorClosed':True,
        'actualKernelRootReturn':True,'kernelPostReturnObservations':1,
        'observedPendingFdHandoff':HANDOFF in positions,'observedOutsideCollector':OUTSIDE in positions,
        'actualNativeCloseRequestAccepted':True,'originalReceiptChargeObserved':True,
        'independentUartOrders':True,'originalNodeCapacityQuarantined':True,'nativeQuotaReleased':False,
        'productionInstallation':False,'completeAllocationClosure':False,**identity(raw)}
