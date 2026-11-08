"""Bounded trace setup and explicit loss control for the selected q35 owner."""
from pathlib import Path
from types import SimpleNamespace
import os
import stat
import time

from tools import build_process

EVENTS = ('pci_cfg_read', 'pci_cfg_write', 'pci_route_irq', 'x86_gsi_interrupt')
BAR3_EVENTS = ('pci_update_mappings_add', 'pci_update_mappings_del')
MAX_LOG = 4 * 1024**2


def require(value, reason):
    if not value:
        raise ValueError('q35-intx-owner-' + reason)


def events(bar3=False):
    require(type(bar3) is bool, 'bar3-selection')
    return EVENTS + (BAR3_EVENTS if bar3 else ())


def trace_argv(boot, *, bar3=False):
    require(type(boot) is tuple and boot and all(type(part) is str for part in boot), 'boot-argv')
    require('-trace' not in boot and '-D' not in boot, 'unmodified-trace-argv')
    return boot + tuple(part for event in events(bar3) for part in ('-trace', 'enable='+event))


def probe_loss(commands, argv):
    """Expect fail-stop on /dev/full; the real observation is a separate boot."""
    device = Path('/dev/full')
    st = device.lstat()
    require(stat.S_ISCHR(st.st_mode) and os.major(st.st_rdev) == 1 and os.minor(st.st_rdev) == 7,
        'linux-full-device-identity')
    require(len(commands.records) < 128 and '-D' not in argv, 'probe-original-command-bounds')
    timeout = min(60, commands.deadline-time.monotonic())
    require(timeout > 0, 'probe-original-deadline')
    label = f'{len(commands.records):02d}-qemu-trace-loss-refusal'
    started = time.monotonic()
    result = build_process.run_bounded_result([*argv, '-D', str(device)], commands.root,
        commands.environment, timeout_seconds=timeout, max_output_bytes=MAX_LOG)
    commands.retain(label, SimpleNamespace(output=result.stdout, stderr=result.stderr))
    commands.records.append({'stage':'qemu-trace-loss-refusal', 'exitCode':result.returncode,
        'expectedNonzero':True, 'completed':True, 'descendantsCleaned':True,
        'elapsedMillis':int((time.monotonic()-started)*1000)})
    require(result.returncode == 74, 'trace-sink-did-not-fail-stop')
    return {'sink':'/dev/full', 'deviceMajor':1, 'deviceMinor':7, 'expectedExit':74,
        'actualExit':result.returncode, 'allDescendantsCleaned':True,
        'partialGuestMayHaveBooted':True, 'guestResultQualified':False}
