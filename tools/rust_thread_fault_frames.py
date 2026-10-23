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


def capture(node, native, component, output):
    node.drain()
    rows = frames(node.buffers[1])
    if rows:
        write_json(output / 'numeric-fault-frames.json', {
            'schemaVersion': 'latent.rust.thread-fault.diagnostic.v1',
            'node': native, 'component': component, 'frames': rows,
            'rawStderrRetained': False, 'runtimeQualification': False,
            'diagnosticIoMayPerturbTimingAndTerminalObservation': True})
