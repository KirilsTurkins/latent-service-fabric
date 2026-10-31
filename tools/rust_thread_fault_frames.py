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


# Last original root suspension, independent of the original fault-frame gate.
# Every matching prefix is parsed/refused; unknown private strings are not saved.
SUSP_ROW = re.compile(rb'^LSF-RUST40-SUSP(?!-FRAME)([^\n]*)$', re.M)
SUSP_VALUE = re.compile(rb':(0|[1-9][0-9]{0,2})' * 4 + rb'\r?')
SUSP_FRAME_ROW = re.compile(rb'^LSF-RUST40-SUSP-FRAME([^\n]*)$', re.M)
SUSP_FRAME_VALUE = re.compile(rb':(0|[1-9][0-9]{0,9})' * 5 + rb'\r?')


def root_suspension(stderr):
    require(len(stderr) <= 262144, 'rust-thread-fault-stderr-bound')
    header = None
    for match in SUSP_ROW.finditer(stderr):
        require(header is None and match.end(1) - match.start(1) <= 17,
                'rust-thread-fault-single-root-suspension-header')
        value = SUSP_VALUE.fullmatch(match.group(1))
        require(value is not None, 'rust-thread-fault-root-suspension-format')
        flags, steps, visited, count = map(int, value.groups())
        require(flags < 128 and steps <= 64 and count <= visited <= 8
                and (not flags & 1 or steps == 64)
                and (not flags & 2 or visited == 8)
                and (not flags & 96 or flags in (32, 64) and steps == visited == count == 0),
                'rust-thread-fault-root-suspension-range')
        header = flags, steps, visited, count
    rows = []
    modules = set()
    for match in SUSP_FRAME_ROW.finditer(stderr):
        require(header is not None and len(rows) < header[3]
                and match.end(1) - match.start(1) <= 56,
                'rust-thread-fault-root-suspension-frame-bound')
        value = SUSP_FRAME_VALUE.fullmatch(match.group(1))
        require(value is not None, 'rust-thread-fault-root-suspension-frame-format')
        ordinal, module, function, instruction, offset = map(int, value.groups())
        require(ordinal == len(rows) and module <= 7
                and module <= len(modules)
                and max(function, instruction, offset) <= 0xffffffff,
                'rust-thread-fault-root-suspension-frame-range')
        modules.add(module)
        rows.append({'ordinal': ordinal, 'module': module, 'function': function,
                     'moduleOffset': instruction, 'functionOffset': offset})
    if header is None:
        return None
    flags, steps, visited, count = header
    require(len(rows) == count and bool(flags & 8) == (visited > count)
            and bool(flags & 4) == any(row['moduleOffset'] == 0xffffffff
                                      or row['functionOffset'] == 0xffffffff for row in rows),
            'rust-thread-fault-root-suspension-complete-record')
    return {'rawTraversalSteps': steps, 'traversalStepLimit': 64,
            'rawFrameVisits': visited, 'frameVisitLimit': 8,
            'traversalMayBeTruncated': bool(flags & 1),
            'framesMayBeTruncated': bool(flags & 2),
            'missingSourceCoordinates': bool(flags & 4),
            'unmappedFrames': bool(flags & 8),
            'traceUnavailable': bool(flags & 16),
            'lastTransferUnavailable': bool(flags & 32),
            'noCaptureSaved': bool(flags & 64), 'frames': rows}


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
    suspension = root_suspension(node.buffers[1])
    if suspension is not None:
        require(code == 22, 'rust-thread-fault-root-suspension-original-async-deadlock')
        write_json(output / 'numeric-original-root-suspension.json', {
            'schemaVersion': 'latent.rust.thread-fault.root-suspension.v1',
            'node': native, 'component': component, 'originalTrapCode': code,
            'suspension': suspension, 'frameObservationRequiredSeparately': True,
            'rawStderrRetained': False, 'runtimeQualification': False,
            'diagnosticIoMayPerturbTimingAndTerminalObservation': True})
    rows = frames(node.buffers[1])
    if rows:
        write_json(output / 'numeric-fault-frames.json', {
            'schemaVersion': 'latent.rust.thread-fault.diagnostic.v1',
            'node': native, 'component': component, 'frames': rows,
            'rawStderrRetained': False, 'runtimeQualification': False,
            'diagnosticIoMayPerturbTimingAndTerminalObservation': True})
