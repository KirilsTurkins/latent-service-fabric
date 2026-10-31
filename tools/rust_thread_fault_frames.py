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
    rows = frames(node.buffers[1])
    if rows:
        write_json(output / 'numeric-fault-frames.json', {
            'schemaVersion': 'latent.rust.thread-fault.diagnostic.v1',
            'node': native, 'component': component, 'frames': rows,
            'rawStderrRetained': False, 'runtimeQualification': False,
            'diagnosticIoMayPerturbTimingAndTerminalObservation': True})
