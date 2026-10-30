"""Raw late-FD UART observations; never synthesize a child-terminal snapshot."""
import hashlib
import re

from tools import host_stream_kernel_vm_image as image

HANDOFF = b'LSFVM1 fd-handoff=original-root opened=2 request=LIVE pending=1'
OUTSIDE = b'LSFVM1 outside-collector=kthreadd-root-bank-and-actor-refs'
LATE_CHECK = b'LSFVM1 result=PASS stage=actual-pending-fd-retirement-root-release-check'
COMPILED_CONTROLS = b'KMSG_CONTROL PASS cases=22\n'
PRINTK = {'bytes':134075,
    'sha256':'9c4af5103450e7d42001e7d620ef707e3b1a5e6b518fcdd904de64c2295c8127'}
SELECTOR = b'#define LSF_VM_LATE_FD 1\n'
BOOT_SECONDS = image.VM_SECONDS // 2


def require(value, reason):
    if not value:
        raise ValueError('kernel-late-fd-' + reason)


def late_probe_source(raw):
    require(type(raw) is bytes and 0 < len(raw) <= 64*1024-len(SELECTOR) and
        raw.count(b'#ifndef LSF_VM_LATE_FD\n#define LSF_VM_LATE_FD 0\n#endif') == 1 and
        not raw.startswith(SELECTOR), 'compiletime-case-source')
    return SELECTOR + raw


def authenticate_printk(raw):
    require(type(raw) is bytes and len(raw) == PRINTK['bytes'] and
        hashlib.sha256(raw).hexdigest() == PRINTK['sha256'], 'actual-compiled-printk-source')
    return dict(PRINTK)


def _snapshot(name, row):
    pattern = (rb'LSFVM1 snapshot=' + name.encode() + rb' state=([0-9]{1,10}) error=([0-9]{1,10})'
        + b''.join(rb' field'+str(index).encode()+rb'=([0-9]{1,20})' for index in range(10)))
    match = re.fullmatch(pattern, row)
    require(match is not None, 'snapshot-fields')
    state, error, *fields = map(int, match.groups())
    require(all(value < 2**64 for value in fields), 'snapshot-integer-bound')
    return dict(state=state, error=error, fields=fields)


def serial_observation(raw):
    require(type(raw) is bytes and 0 < len(raw) <= image.MAX_SERIAL, 'serial-bound')
    require(not any(marker in raw for marker in (b'Kernel panic', b'BUG:', b'Oops:')), 'kernel-fault')
    lines, marker_positions = raw.splitlines(), {}
    for marker in (HANDOFF, image.PHYSICAL_MARKER, OUTSIDE):
        pattern = rb'(?:\[[ ]{0,10}[0-9]{1,10}\.[0-9]{6}\] )?' + re.escape(marker)
        positions = [i for i, line in enumerate(lines) if re.fullmatch(pattern, line)]
        require(len(positions) == 1 and raw.count(marker) == 1, 'unique-actual-kernel-transition')
        marker_positions[marker] = positions[0]
    excluded = set(marker_positions.values())
    rows = [(i, line) for i, line in enumerate(lines)
        if i not in excluded and line.startswith(b'LSFVM1 ')]
    require(len(rows) == 4 and rows[0][1] ==
        b'LSFVM1 boot=constructor-only production-sockets=disabled' and
        rows[-1][1] == LATE_CHECK, 'complete-late-sequence')
    opened, ready = _snapshot('opened', rows[1][1]), _snapshot('ready', rows[2][1])
    require(opened == dict(state=0,error=0,fields=[0,0,0,0,0,0,2,0,0,0]), 'original-prebirth')
    active = ready['fields']
    require(ready['state'] == 2 and ready['error'] == 0 and
        active[0:2] == [3,0] and active[2] in (0,1) and active[3] == 1 and
        1 <= active[4] <= 256 and active[5] == 0 and 6 <= active[6] <= 256 and
        active[7] <= active[6] and active[8:] == [0,0], 'actual-positive-ready')
    # /dev/kmsg observes ring commitment, not delivery to the UART console.
    # PID1 can print its terminal before another CPU delivers kernel records.
    # Its own four rows remain ordered above; all three actual kernel records
    # are independently mandatory, unique and ordered in their printk stream.
    positions = [marker_positions[HANDOFF],marker_positions[image.PHYSICAL_MARKER],
        marker_positions[OUTSIDE]]
    require(positions == sorted(positions) and len(set(positions)) == len(positions),
        'pending-physical-outside-kernel-order')
    return dict(snapshots={'opened':opened,'ready':ready}, rootFinalFree=True,
        lateFdCollection=True,
        pendingFdHandoff={'originalRequestLiveAtTransition':True,'requestReturned':False,
            'originalFdCustodyTransferred':True},
        physicalReturn={'outsideKthreaddCollector':True,'kernelObservations':3,
            'kernelMarkersOrdered':True,'independentPid1UartOrder':True,
            'sourceBoundTerminalGuardsAtTake':True,'nativeQuotaRelease':False,
            'productionInstallation':False},
        bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
