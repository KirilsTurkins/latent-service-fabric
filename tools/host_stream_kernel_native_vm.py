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


# Fresh, development-only q35 Node preparation image. No historical VM receipt
# is accepted here, and no positive NodeFunding/retirement/IRQ issuer exists.
NODE_BRANCH = 'feat/sdk-738-q35-node-boot-20261029'
NODE_ROOT = 'research/standard-outbound/linux-6.12-lineage/node-boot/'
NODE_PROJECTOR = NODE_ROOT+'projector.py'
NODE_MATERIALS = ('factory-node-boot.c','Kconfig.fragment','Makefile.fragment')
NODE_INIT = NODE_ROOT+'node-boot-init.c'
QEMU_PIN = {'url':'https://download.qemu.org/qemu-11.1.2.tar.xz',
    'bytes':141815216,'sha256':'731b5681e4bb18be313231579b8efd0296c5b015fa36dc533874b639ba838016'}
QEMU_SIGNATURE = {'url':QEMU_PIN['url']+'.sig','bytes':310,
    'sha256':'30c15b161e86a008eaa502bd3f0c31dc0d27371ded6c1a6e66c95c4e830113f9'}
QEMU_KEY = {'url':'https://keys.openpgp.org/vks/v1/by-fingerprint/CEACC9E15534EBABB82D3FA03353C9CEF108B584',
    'bytes':2780,'sha256':'05d6f38c5acd314bf22670393240f79d5fa199628ee8a46bdf565144083da3ab'}
QEMU_FINGERPRINT = 'CEACC9E15534EBABB82D3FA03353C9CEF108B584'
NODE_BOOT = b'LSFNODEBOOT1 boot=original-node-preparation-only'
NODE_END = b'LSFVM1 result=PASS stage=actual-node-preparation-and-retained-close'
NODE_HELD = (b'LSFNODEBOOT1 prepared=1 descriptorClosed=1 originalEscrowRetained=1 '
    b'nodeFunding=0 nodeRetired=0 irqEnabled=0 tcpEnabled=0')


def node_capture(root):
    import stat
    names = [NODE_PROJECTOR,NODE_INIT,*(NODE_ROOT+n for n in NODE_MATERIALS)]
    result = {}
    for name in names:
        path = root/name
        require(stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink(), 'node-source-kind')
        raw = read_file(path,4*1024**2)
        raw.decode('utf8','strict')
        require(b'\r' not in raw, 'node-source-LF')
        result[name] = raw
    require(sum(map(len,result.values())) <= 16*1024**2, 'node-source-bound')
    return result


def node_compose(values,build_files,captured):
    import importlib.abc
    import importlib.util
    from pathlib import Path
    path = str((ROOT/NODE_PROJECTOR).resolve())
    class Captured(importlib.abc.SourceLoader):
        def get_filename(self,fullname):
            require(fullname == '_lsf_q35_boot_projector','node-projector-name'); return path
        def get_data(self,name):
            require(name == path,'node-no-alternate-projector'); return captured[NODE_PROJECTOR]
        def path_stats(self,name):
            raise OSError('node-no-bytecode')
    spec = importlib.util.spec_from_file_location('_lsf_q35_boot_projector',path,loader=Captured())
    require(spec is not None and spec.loader is not None,'node-projector-spec')
    stage = importlib.util.module_from_spec(spec); spec.loader.exec_module(stage)
    require(Path(stage.__file__).resolve() == Path(path) and stage.ROOT == ROOT.resolve(),
        'node-projector-origin')
    materials = {n:captured[NODE_ROOT+n] for n in NODE_MATERIALS}
    require(stage.MATERIAL_PINS == {n:identity(raw) for n,raw in materials.items()},'node-material-pins')
    result,receipt = stage.transform(values,build_files,materials)
    require(len(result) == 488 and receipt['beforeCount'] == 485 and
        receipt['originalBodiesInverseExact'] is True and
        all(receipt[k] is False for k in ('nodeFundingQualified','nodeRetirementQualified',
            'irqEnabled','consumerInstalled','booted')),'node-projection-authority')
    return result,receipt


def node_supervisor(captured,original):
    raw = captured[NODE_INIT]
    anchor = b'#include "constructor-vm-init.c"\n'
    require(raw.count(anchor) == 1 and 0 < len(raw)+len(original) <= 64*1024,
        'node-supervisor-composition')
    return raw.replace(anchor,original)


def node_serial(raw):
    require(type(raw) is bytes and 0 < len(raw) <= image.MAX_SERIAL,'node-serial-bound')
    require(not any(marker in raw for marker in (b'Kernel panic',b'BUG:',b'Oops:',b'result=FAIL')),
        'node-native-failure')
    rows = [line for line in raw.splitlines() if line.startswith((b'LSFNODEBOOT1 ',b'LSFVM1 '))]
    require(len(rows) == 5 and rows[0] == NODE_BOOT and rows[-3:] ==
        [NODE_HELD,b'LSFNODEBOOT1 childExit=0',NODE_END], 'node-complete-actual-protocol')
    pattern = rb'LSFNODEBOOT1 facts=\[([0-9, ]+)\] cpu=\[([0-9, ]+)\] accounting=\[([0-9, ]+)\] vectors=\[([0-9, ]+)\]'
    match = re.fullmatch(pattern,rows[1]); require(match is not None,'node-facts-grammar')
    groups = [[int(x) for x in re.fullmatch(rb'[0-9]{1,20}(?:, [0-9]{1,20})*',r)[0].split(b', ')]
        if re.fullmatch(rb'[0-9]{1,20}(?:, [0-9]{1,20})*',r) else [] for r in match.groups()]
    require(list(map(len,groups)) == [6,9,8,8] and
        all(x < 2**64 for row in groups for x in row),'node-facts-exact-fields')
    layout,cpu,accounting,vectors = groups
    require(cpu[:3] == [1,1,1] and 0 < accounting[1] <= accounting[2] and
        len(set(vectors)) == 8 and all(32 <= x < 256 for x in vectors),'node-actual-capacity')
    return {'raw':identity(raw),'nodeLayout':layout,'cpuGeometry':cpu,'accounting':accounting,
        'vectors':vectors,'descriptorClosed':True,'originalEscrowRetained':True,
        'nodeFunding':False,'nodeRetired':False,'irqEnabled':False,'tcpEnabled':False}


def node_boot_argv(qemu,kernel,initramfs,firmware):
    require(all(p.is_absolute() for p in (qemu,kernel,initramfs,firmware)), 'node-absolute-images')
    return (str(qemu),'-machine','pc-q35-11.1','-accel','kvm','-cpu','host',
        '-smp','1,maxcpus=1','-m',str(image.VM_MEMORY_MIB),'-nodefaults','-no-user-config',
        '-display','none','-serial','stdio','-monitor','none','-no-reboot','-nic','none',
        '-device','virtio-net-pci,id=net0,mac=52:54:00:12:34:56,vectors=3,romfile=',
        '-L',str(firmware),'-bios',str(firmware/'bios-256k.bin'),'-kernel',str(kernel),
        '-initrd',str(initramfs),'-append','console=ttyS0 panic=1 rdinit=/init maxcpus=1 nr_cpus=1')


def node_qemu_source_name(raw):
    name = raw.rstrip('/')
    parts = name.split('/')
    require(name and '\\' not in name and ':' not in name and
        all(p not in ('', '..', '.') for p in parts) and parts[0] == 'qemu-11.1.2',
        'node-qemu-safe-member')
    return name


def node_qemu_link_target(name,kind,target):
    require(target and not target.startswith('/') and '\\' not in target and ':' not in target,
        'node-qemu-relative-link')
    base = name.split('/')[:-1] if kind == '2' else []
    for part in target.split('/'):
        if part == '..':
            require(len(base) > 1,'node-qemu-contained-link'); base.pop()
        elif part not in ('', '.'):
            base.append(part)
    return node_qemu_source_name('/'.join(base))


def node_qemu_link_targets(rows,deadline):
    import time
    require(type(rows) is dict and len(rows) <= 65536,'node-qemu-source-entry-bound')
    targets = {}
    for name,row in rows.items():
        require(time.monotonic() < deadline,'node-qemu-preflight-deadline')
        require(node_qemu_source_name(name) == name and row['type'] in ('0','5','1','2'),
            'node-qemu-safe-member')
        parts = name.split('/')
        require(not any(rows.get('/'.join(parts[:i]),{}).get('type') in ('1','2')
            for i in range(1,len(parts))), 'node-qemu-no-link-ancestor')
        if row['type'] not in ('1','2'):
            continue
        current,seen = name,set()
        for _ in range(17):  # At most sixteen links and one terminal member.
            require(time.monotonic() < deadline,'node-qemu-preflight-deadline')
            require(current in rows,'node-qemu-known-link-target')
            require(current not in seen,'node-qemu-link-cycle'); seen.add(current)
            selected = rows[current]
            if selected['type'] in ('0','5'):
                require(row['type'] != '1' or selected['type'] == '0','node-qemu-hardlink-file')
                targets[name] = current
                break
            require(selected['type'] in ('1','2') and
                (row['type'] != '1' or selected['type'] == '1'),'node-qemu-link-type')
            current = node_qemu_link_target(current,selected['type'],selected['link'])
        else:
            require(False,'node-qemu-link-depth')
    return targets


def node_qemu_extract(archive,directory,deadline):
    import tarfile
    import time
    require(not directory.exists(),'node-qemu-fresh-extract')
    # This signed release has85084 headers. Only the separately built edk2
    # firmware-SOURCE subtree is excluded; pc-bios signed blobs stay selected.
    # Its absolute macOS X11 link is never materialized or followed.
    excluded_root = 'qemu-11.1.2/roms/edk2'
    rows,total,headers,excluded,excluded_bytes = {},0,0,0,0
    # CPython3.13.5 stream=True disables TarFile's otherwise unbounded member
    # cache. Retain ONLY selected TarInfo entries under the existing65536 cap.
    with tarfile.open(archive,'r:xz',stream=True) as bundle:
        members = []
        for member in bundle:
            require(time.monotonic() < deadline,'node-qemu-preflight-deadline')
            headers += 1
            require(headers <= 85084,'node-qemu-signed-header-count')
            name = node_qemu_source_name(member.name)  # BEFORE exclusion/PAX names.
            require(not member.mode & 0o7000 and
                (member.isfile() or member.isdir() or member.issym() or member.islnk()),
                'node-qemu-safe-member')
            require(0 <= member.size <= 128*1024**2,'node-qemu-source-entry-bound')
            total += member.size
            require(total <= 2*1024**3,'node-qemu-source-byte-bound')
            if name == excluded_root or name.startswith(excluded_root+'/'):
                excluded += 1; excluded_bytes += member.size
                require(excluded <= 41834,'node-qemu-excluded-header-count')
                continue
            require(len(rows) < 65536 and name not in rows,'node-qemu-source-entry-bound')
            rows[name] = {'bytes':member.size,'type':member.type.decode('ascii'),
                'link':member.linkname,'mode':member.mode}
            members.append(member)
        require(headers == 85084 and excluded == 41834,'node-qemu-signed-projection-counts')
        links = node_qemu_link_targets(rows,deadline)
        require(time.monotonic() < deadline,'node-qemu-extract-deadline')
        directory.mkdir(mode=0o700)
        # Real files/directories precede links. Hardlink chains can reference
        # only an already extracted selected regular file, with no cache lookup.
        for linked in (False,True):
            for member in members:
                require(time.monotonic() < deadline,'node-qemu-extract-deadline')
                if (member.issym() or member.islnk()) != linked:
                    continue
                if member.islnk():
                    member = member.replace(linkname=links[member.name.rstrip('/')],deep=False)
                bundle.extract(member,directory,filter='data')
    require(time.monotonic() < deadline,'node-qemu-extract-deadline')
    return directory/'qemu-11.1.2',{'members':rows,'expandedBytes':total,
        'observedArchiveHeaders':headers,'excludedSubtree':excluded_root,
        'excludedHeaders':excluded,'excludedExpandedBytes':excluded_bytes,
        'materializedEntries':len(rows),'materializedExpandedBytes':total-excluded_bytes,
        'maximumMaterializedEntries':65536,'maximumBytes':2*1024**3,
        'maximumFileBytes':128*1024**2,'selectedLinks':links,'maximumLinkDepth':16}
