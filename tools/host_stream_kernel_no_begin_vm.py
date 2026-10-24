"""Fresh initial-only Root observation and one shared three-boot VM budget."""
from contextlib import contextmanager
import hashlib
import re
import time

from tools import host_stream_kernel_late_fd_vm as late
from tools import host_stream_kernel_vm_image as image

SELECTOR = b'#define LSF_VM_NO_BEGIN 1\n'
NO_BEGIN_CHECK = b'LSFVM1 result=PASS stage=actual-no-begin-descriptor-close-returned'


def require(value, reason):
    if not value:
        raise ValueError('kernel-no-begin-' + reason)


def no_begin_probe_source(raw):
    require(type(raw) is bytes and 0 < len(raw) <= 64*1024-len(SELECTOR) and
        raw.count(b'#ifndef LSF_VM_NO_BEGIN\n#define LSF_VM_NO_BEGIN 0\n#endif') == 1 and
        not raw.startswith((SELECTOR, late.SELECTOR)), 'compiletime-case-source')
    return SELECTOR + raw


def serial_observation(raw):
    require(type(raw) is bytes and 0 < len(raw) <= image.MAX_SERIAL, 'serial-bound')
    require(not any(marker in raw for marker in (b'Kernel panic', b'BUG:', b'Oops:')), 'kernel-fault')
    require(late.HANDOFF not in raw and late.OUTSIDE not in raw, 'unexpected-child-kernel-transition')
    lines = raw.splitlines()
    pattern = rb'(?:\[[ ]{0,10}[0-9]{1,10}\.[0-9]{6}\] )?' + re.escape(image.PHYSICAL_MARKER)
    positions = [i for i, line in enumerate(lines) if re.fullmatch(pattern, line)]
    require(len(positions) == 1 and raw.count(image.PHYSICAL_MARKER) == 1,
        'unique-actual-kernel-physical-return')
    require(all(i == positions[0] or b'LSFVM1 ' not in line or line.startswith(b'LSFVM1 ')
        for i, line in enumerate(lines)), 'unexpected-kernel-observation')
    rows = [line for i, line in enumerate(lines) if i != positions[0] and line.startswith(b'LSFVM1 ')]
    require(len(rows) == 3 and rows[0] ==
        b'LSFVM1 boot=constructor-only production-sockets=disabled' and rows[-1] == NO_BEGIN_CHECK,
        'complete-no-begin-sequence')
    opened = late._snapshot('opened', rows[1])
    require(opened == dict(state=0,error=0,fields=[0,0,0,0,0,0,2,0,0,0]), 'original-prebirth')
    # Ring commitment and PID1 writes do not establish cross-stream UART
    # delivery order. The physical marker is mandatory independently of the
    # three ordered PID1 rows; close success itself proves no physical return.
    return dict(snapshots={'opened':opened}, rootFinalFree=True, noBeginCollection=True,
        childConstructorStarted=False, pid1TerminalStage='actual-no-begin-descriptor-close-returned',
        physicalReturn=dict(kernelObservations=1, marker=image.PHYSICAL_MARKER.decode(),
            sourceBoundInitialMetadataAtTake=True, independentPid1UartOrder=True,
            nativeQuotaRelease=False, productionInstallation=False),
        bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


@contextmanager
def shared_vm_budget(commands):
    """Use the original runner's remaining-deadline cap for all three boots."""
    old_seconds, old_deadline = commands.command_seconds, commands.deadline
    started = time.monotonic()
    commands.command_seconds = min(old_seconds, late.BOOT_SECONDS)
    commands.deadline = min(old_deadline, started + image.VM_SECONDS)
    observation = dict(perCommandMaximumSeconds=late.BOOT_SECONDS,
        aggregateMaximumSeconds=image.VM_SECONDS, sharedMonotonicDeadline=True,
        perCommandMaximaAreNotAdditive=True)
    try:
        require(commands.command_seconds > 0 and commands.deadline > started, 'aggregate-vm-deadline')
        yield observation
        finished = time.monotonic()
        require(finished <= commands.deadline, 'aggregate-vm-deadline')
        observation['elapsedMillis'] = int((finished - started) * 1000)
    finally:
        commands.command_seconds, commands.deadline = old_seconds, old_deadline
