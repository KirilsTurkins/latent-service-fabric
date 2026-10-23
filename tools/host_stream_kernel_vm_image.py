"""Bounded images for an isolated constructor VM; never install on the host.

These structural checks do not authenticate compiler output or qualify a kernel.
The owning programme must bind the actual source, tools, configuration and image.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct

MAX_INIT = 2 * 1024**2
MAX_INIT_LOAD = 4 * 1024**2
MAX_INITRAMFS = 4 * 1024**2
MAX_KERNEL = 32 * 1024**2
MAX_SERIAL = 64 * 1024
VM_SECONDS = 180
VM_MEMORY_MIB = 512
VM_CPUS = 2
REQUIRED_CONFIG = (
    'CONFIG_64BIT', 'CONFIG_X86_64', 'CONFIG_BLK_DEV_INITRD',
    'CONFIG_BINFMT_ELF', 'CONFIG_DEVTMPFS', 'CONFIG_PROC_FS', 'CONFIG_SYSFS',
    'CONFIG_SERIAL_8250', 'CONFIG_SERIAL_8250_CONSOLE', 'CONFIG_PCI',
    'CONFIG_ACPI', 'CONFIG_LSF_STREAM_FACTORY',
)
TERMINAL_FIELDS = (8, 5, 0, 2, 0, 1, 2, 0, 1, 1)
PHYSICAL_MARKER = b'LSFVM1 physical-return=constructor-root-bank-and-actor-refs'
ROOT_RELEASE_CHECK = b'LSFVM1 result=PASS stage=actual-child-retirement-root-release-check'


def require(condition, reason):
    if not condition:
        raise ValueError('kernel-constructor-vm-' + reason)


def init_elf(raw: bytes) -> dict:
    """Reject interpreters, dynamic dependencies, writable code and huge BSS."""
    require(type(raw) is bytes and 64 <= len(raw) <= MAX_INIT, 'init-byte-bound')
    require(raw[:7] == b'\x7fELF\x02\x01\x01', 'init-elf64-little-endian')
    kind, machine, version, entry, phoff = struct.unpack_from('<HHIQQ', raw, 16)
    ehsize, phsize, phcount = struct.unpack_from('<HHH', raw, 52)
    require((kind, machine, version, ehsize, phsize) == (2, 62, 1, 64, 56)
            and 0 < phcount <= 64 and phoff >= 64
            and phoff + phcount * phsize <= len(raw), 'init-executable-header')
    spans, executable_entry = [], False
    for index in range(phcount):
        ptype, flags, offset, address, _, files, memory, alignment = struct.unpack_from(
            '<IIQQQQQQ', raw, phoff + index * phsize)
        require(ptype not in (2, 3), 'init-static-only')
        require(not (ptype == 0x6474e551 and flags & 1), 'init-executable-stack')
        if ptype != 1:
            continue
        require(files <= memory <= MAX_INIT_LOAD and offset + files <= len(raw)
                and address + memory < 2**64, 'init-load-range')
        require(alignment in (0, 1) or 1 < alignment <= 2 * 1024**2
                and not alignment & (alignment - 1)
                and address % alignment == offset % alignment, 'init-load-alignment')
        require(not (flags & 1 and flags & 2), 'init-write-execute')
        if memory:
            spans.append((address, address + memory))
        executable_entry |= bool(flags & 1 and address <= entry < address + files)
    require(bool(spans) and executable_entry
            and max(end for _, end in spans) - min(start for start, _ in spans) <= MAX_INIT_LOAD,
            'init-finite-entry-image')
    require(all(a_end <= b_start for (_, a_end), (b_start, _) in
                zip(sorted(spans), sorted(spans)[1:])), 'init-overlapping-loads')
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'loadSegments': len(spans), 'staticX86_64': True}


def kernel_image(raw: bytes) -> dict:
    require(type(raw) is bytes and 4096 <= len(raw) <= MAX_KERNEL, 'kernel-byte-bound')
    require(raw[0x1fe:0x200] == b'\x55\xaa' and raw[0x202:0x206] == b'HdrS',
            'kernel-boot-header')
    protocol = struct.unpack_from('<H', raw, 0x206)[0]
    extended = struct.unpack_from('<H', raw, 0x236)[0]
    require(protocol >= 0x20c and extended & 1 and raw[0x211] & 1, 'kernel-64bit-bzimage')
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'bootProtocol': protocol, 'x86_64': True}


def serial_observation(raw: bytes) -> dict:
    """Require the real three snapshots in addition to successful VM exit."""
    require(type(raw) is bytes and 0 < len(raw) <= MAX_SERIAL, 'serial-bound')
    require(not any(marker in raw for marker in (b'Kernel panic', b'BUG:', b'Oops:')),
            'kernel-fault')
    rows = [line for line in raw.splitlines() if line.startswith(b'LSFVM1 ')]
    require(len(rows) == 5 and rows[0] ==
            b'LSFVM1 boot=constructor-only production-sockets=disabled' and rows[-1] ==
            b'LSFVM1 result=PASS stage=actual-child-retirement-root-final-free-unqualified',
            'complete-observation-sequence')
    snapshots = {}
    for name, row in zip(('opened', 'ready', 'child-retired-root-held'), rows[1:4]):
        pattern = (rb'LSFVM1 snapshot=' + name.encode() + rb' state=([0-9]{1,10}) error=([0-9]{1,10})'
                   + b''.join(rb' field' + str(index).encode() + rb'=([0-9]{1,20})'
                              for index in range(10)))
        match = re.fullmatch(pattern, row)
        require(match is not None, 'snapshot-fields')
        state, error, *fields = map(int, match.groups())
        require(all(value < 2**64 for value in fields), 'snapshot-integer-bound')
        snapshots[name] = dict(state=state, error=error, fields=fields)
    require(snapshots['opened']['state'] == 0 and snapshots['opened']['error'] == 0
            and snapshots['ready']['state'] == 2 and snapshots['ready']['error'] == 0,
            'actual-ready-transition')
    require(snapshots['opened']['fields'] == [0, 0, 0, 0, 0, 0, 2, 0, 0, 0],
            'only-original-backing-and-root-before-birth')
    active = snapshots['ready']['fields']
    require(active[0:2] == [3, 0] and active[2] in (0, 1) and active[3] == 1
            and 1 <= active[4] <= 256 and active[5] == 0
            and 6 <= active[6] <= 256 and active[7] <= active[6] and active[8:] == [0, 0],
            'actual-published-task-and-paid-registration')
    require(snapshots['child-retired-root-held'] ==
            dict(state=4, error=0, fields=list(TERMINAL_FIELDS)), 'actual-child-terminal-counters')
    return dict(snapshots=snapshots, rootFinalFree=False,
                bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def root_physical_serial_observation(raw: bytes) -> dict:
    """Require actual kernel return after the original Root-held observation.

    PID1 close success and logical record counters provide no physical proof.
    The fixed kernel marker is emitted only after the original pages/ref puts.
    This uses the unchanged historical child parser, preserving all its bounds
    and refusal checks; normalized bytes are never the recorded raw identity.
    """
    require(type(raw) is bytes and 0 < len(raw) <= MAX_SERIAL, 'serial-bound')
    lines = raw.splitlines()
    pattern = rb'(?:\[[ ]{0,10}[0-9]{1,10}\.[0-9]{6}\] )?' + re.escape(PHYSICAL_MARKER)
    matches = [index for index, line in enumerate(lines) if re.fullmatch(pattern, line)]
    require(len(matches) == 1 and raw.count(PHYSICAL_MARKER) == 1,
        'unique-actual-kernel-physical-return')
    child = [index for index, line in enumerate(lines)
        if line.startswith(b'LSFVM1 snapshot=child-retired-root-held ')]
    terminal = [index for index, line in enumerate(lines) if line == ROOT_RELEASE_CHECK]
    require(len(child) == len(terminal) == 1 and child[0] < matches[0] < terminal[0],
        'actual-physical-return-order')
    historical_terminal = b'LSFVM1 result=PASS stage=actual-child-retirement-root-final-free-unqualified'
    normalized = b'\n'.join(historical_terminal if line == ROOT_RELEASE_CHECK else line
        for index, line in enumerate(lines) if index != matches[0]) + b'\n'
    observation = serial_observation(normalized)
    return {**observation, 'rootFinalFree': True,
        'physicalReturn': {'marker':PHYSICAL_MARKER.decode(), 'kernelObservations':1,
            'afterChildRetirementRootHeld':True, 'beforePid1ReleaseCheck':True,
            'nativeQuotaRelease':False, 'productionInstallation':False},
        'pid1TerminalStage':'actual-child-retirement-root-release-check',
        'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}


def check_boot_configuration(raw: bytes, parse_config) -> dict:
    """Observe the real resolved config; do not silently add/disable options."""
    require(type(raw) is bytes and 0 < len(raw) <= 256 * 1024, 'configuration-bound')
    value = parse_config(raw)
    require(all(value.get(name) == 'y' for name in REQUIRED_CONFIG),
            'required-boot-option-missing')
    require(value.get('CONFIG_INITRAMFS_SOURCE') == '""', 'external-initramfs-required')
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'requiredOptions': list(REQUIRED_CONFIG), 'configurationMutated': False}


def initramfs_spec(init: Path) -> bytes:
    # Only a programme-owned absolute regular-file path reaches gen_init_cpio.
    require(init.is_absolute() and init.is_file() and not init.is_symlink(), 'init-owned-path')
    spelling = str(init)
    require(not any(character.isspace() or character in '\\#\0' for character in spelling),
            'init-spec-path')
    return ('dir /dev 755 0 0\n'
            'nod /dev/console 600 0 0 c 5 1\n'
            'dir /proc 555 0 0\n'
            'dir /sys 555 0 0\n'
            f'file /init {spelling} 755 0 0\n').encode('utf-8')


def boot_argv(qemu: Path, kernel: Path, initramfs: Path, firmware: Path) -> tuple[str, ...]:
    """No host disks, host network, KVM dependency, monitor or host installation."""
    require(all(path.is_absolute() for path in (qemu, kernel, initramfs, firmware)),
            'boot-absolute-inputs')
    return (str(qemu), '-machine', 'q35', '-accel', 'tcg,thread=multi',
            '-cpu', 'qemu64', '-smp', str(VM_CPUS), '-m', str(VM_MEMORY_MIB),
            '-nodefaults', '-no-user-config', '-display', 'none',
            '-serial', 'stdio', '-monitor', 'none',
            '-L', str(firmware), '-bios', str(firmware/'bios-256k.bin'),
            '-no-reboot', '-nic', 'none', '-kernel', str(kernel), '-initrd', str(initramfs),
            '-append', 'console=ttyS0 panic=1 rdinit=/init')


def build_init(commands, compiler: Path, source: bytes, output: Path, *, mode='fast') -> tuple[Path, dict]:
    """Compile one captured static PID1; retain real diagnostics on failure."""
    from tools.dev_workflow import paths
    require(type(source) is bytes and 0 < len(source) <= 64 * 1024, 'init-source-bound')
    require(compiler.is_absolute() and output.is_absolute(), 'init-build-absolute-inputs')
    require(mode in ('fast', 'late', 'no-begin'), 'init-closed-observation-mode')
    copied, target = output/'constructor-init.c', output/'constructor-init'
    paths.write_new(copied, source)
    require(not target.exists(), 'init-build-destination-exists')
    stage = {'fast':'compile-static-constructor-init', 'late':'compile-static-late-fd-init',
        'no-begin':'compile-static-no-begin-init'}[mode]
    commands.run(stage, compiler, '-std=c11', '-Os',
                 '-Wall', '-Wextra', '-Werror', '-static', '-no-pie', '-fno-ident',
                 '-ffile-prefix-map='+str(output)+'=.', '-Wl,--build-id=none',
                 '-Wl,-z,noexecstack', '-o', target, copied)
    require(paths.read(output, copied.name, 64 * 1024) == source, 'init-source-drift')
    raw = paths.read(output, target.name, MAX_INIT)
    return target, {**init_elf(raw), 'sourceSha256': hashlib.sha256(source).hexdigest()}


def build_initramfs(commands, generator: Path, init: Path, output: Path, *, mode='fast') -> tuple[Path, dict]:
    """Use the authenticated kernel's own generator, with no shell or CPIO tool."""
    from tools.dev_workflow import paths
    require(generator.is_absolute() and output.is_absolute(), 'initramfs-absolute-inputs')
    require(mode in ('fast', 'late', 'no-begin'), 'initramfs-closed-observation-mode')
    before = paths.read(init.parent, init.name, MAX_INIT)
    init_elf(before)
    spec = output/'constructor-initramfs.list'
    paths.write_new(spec, initramfs_spec(init))
    stage = {'fast':'create-constructor-initramfs', 'late':'create-late-fd-initramfs',
        'no-begin':'create-no-begin-initramfs'}[mode]
    raw = commands.run(stage, generator, '-t', '0', spec)
    require(0 < len(raw) <= MAX_INITRAMFS and raw.startswith(b'070701'), 'initramfs-newc-bound')
    require(paths.read(init.parent, init.name, MAX_INIT) == before, 'initramfs-init-drift')
    archive = output/'constructor-initramfs.cpio'
    paths.write_new(archive, raw)
    return archive, {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                     'initSha256': hashlib.sha256(before).hexdigest()}
