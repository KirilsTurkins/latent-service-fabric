"""Closed numeric observation from the explicitly rebuilt diagnostic node only.

The prefix does not authenticate a host. The owning programme separately binds
the built node bytes, actual component and source; no qualification uses this
diagnostic. Never retain raw stderr or guest-controlled names/error strings.
"""
import re

from tools.phase2_operator_process import require
from tools.rust_capsule_project import write_json

ROW = re.compile(rb'^LSF-RUST40-FAULT:([0-9]{1}):([0-9]{1,10}):([0-9]{1,20}):([0-9]{1,20})\r?$', re.M)


def frames(stderr):
    require(len(stderr) <= 262144, 'rust-thread-fault-stderr-bound')
    rows = []
    for match in ROW.finditer(stderr):
        # Check before constructing/appending the next record.
        require(len(rows) < 8, 'rust-thread-fault-frame-bound')
        ordinal, function, module_offset, function_offset = map(int, match.groups())
        require(ordinal == len(rows) and function <= 0xffffffff
                and max(module_offset, function_offset) <= 0xffffffffffffffff,
                'rust-thread-fault-frame-sequence-or-range')
        rows.append({'ordinal': ordinal, 'function': function,
                     'moduleOffset': module_offset, 'functionOffset': function_offset})
    return rows


# Exactly the 50 original unit-enum ordinals in locked wasmtime-environ 48.0.7.
# Inspect the actual typed Trap separately from the optional original backtrace.
TRAP_ROW = re.compile(rb'^LSF-RUST40-TRAP([^\n]*)$', re.M)
TRAP_VALUE = re.compile(rb':(0|[1-9][0-9]?)\r?')


def trap_code(stderr):
    require(len(stderr) <= 262144, 'rust-thread-fault-stderr-bound')
    code = None
    for match in TRAP_ROW.finditer(stderr):
        require(code is None, 'rust-thread-fault-single-original-trap-code')
        # Bound the captured payload before copying it out of the match.
        require(match.end(1) - match.start(1) <= 4,
                'rust-thread-fault-original-trap-code-format')
        value = TRAP_VALUE.fullmatch(match.group(1))
        require(value is not None, 'rust-thread-fault-original-trap-code-format')
        code = int(value.group(1))
        require(code < 50, 'rust-thread-fault-original-trap-code-range')
    return code


# One fixed record from the existing authenticated, admitted native factory.
# Prefix counts are NEVER whole-store totals when the physical scan truncates.
SCHED_ROW = re.compile(rb'^LSF-RUST40-SCHED([^\n]*)$', re.M)
SCHED_VALUE = re.compile(rb':(0|[1-9][0-9]{0,4})' * 11 + rb'\r?')


def scheduler_snapshot(stderr):
    require(len(stderr) <= 262144, 'rust-thread-fault-stderr-bound')
    result = None
    for match in SCHED_ROW.finditer(stderr):
        require(result is None, 'rust-thread-fault-single-scheduler-snapshot')
        require(match.end(1) - match.start(1) <= 67,
                'rust-thread-fault-scheduler-format')
        value = SCHED_VALUE.fullmatch(match.group(1))
        require(value is not None, 'rust-thread-fault-scheduler-format')
        scanned, flags, *tail = map(int, value.groups())
        states, roots, root_flags, waiting = tail[:6], *tail[6:]
        require(scanned <= 64 and flags < 32 and flags & 8
                and sum(states) + roots <= scanned and root_flags <= 255
                and waiting <= 65535 and (not flags & 1 or scanned == 64)
                and (not flags & 16 or waiting == 65535)
                and (roots != 0 or root_flags == 0),
                'rust-thread-fault-scheduler-range')
        result = {'physicalSlotsScanned': scanned, 'physicalSlotLimit': 64,
                  'prefixTruncated': bool(flags & 1),
                  'highQueueEmptyAfterFinalRootPoll': bool(flags & 2),
                  'lowQueueEmptyAfterFinalRootPoll': bool(flags & 4),
                  'hostFutureStreamExhaustedBeforeFinalRootPoll': True,
                  'waitingCountOverflow': bool(flags & 16),
                  'prefixThreadStateCounts': dict(zip(
                      ('notStartedImplicit', 'notStartedExplicit', 'running',
                       'suspended', 'ready', 'completed'), states)),
                  'prefixHostRootCount': roots, 'prefixRootFlagsOr': root_flags,
                  'prefixWaitingThreadCount': waiting}
    return result


def capture(node, native, component, output):
    node.drain()
    code = trap_code(node.buffers[1])
    if code is not None:
        # Retain this independent non-qualifying observation even if the old
        # nonempty-frame assertion subsequently fails. Do not invent frames.
        write_json(output / 'numeric-original-trap-code.json', {
            'schemaVersion': 'latent.rust.thread-fault.original-trap-code.v1',
            'node': native, 'component': component, 'originalTrapCode': code,
            'codeProfile': 'wasmtime-environ-48.0.7-original-u8-v1',
            'frameObservationRequiredSeparately': True,
            'rawStderrRetained': False, 'runtimeQualification': False,
            'diagnosticIoMayPerturbTimingAndTerminalObservation': True})
    snapshot = scheduler_snapshot(node.buffers[1])
    if snapshot is not None:
        require(code == 22, 'rust-thread-fault-scheduler-original-async-deadlock')
        write_json(output / 'numeric-original-scheduler-snapshot.json', {
            'schemaVersion': 'latent.rust.thread-fault.scheduler-prefix.v1',
            'node': native, 'component': component, 'originalTrapCode': code,
            'snapshot': snapshot, 'frameObservationRequiredSeparately': True,
            'rawStderrRetained': False, 'runtimeQualification': False,
            'diagnosticIoMayPerturbTimingAndTerminalObservation': True})
    rows = frames(node.buffers[1])
    if rows:
        write_json(output / 'numeric-fault-frames.json', {
            'schemaVersion': 'latent.rust.thread-fault.diagnostic.v1',
            'node': native, 'component': component, 'frames': rows,
            'rawStderrRetained': False, 'runtimeQualification': False,
            'diagnosticIoMayPerturbTimingAndTerminalObservation': True})
