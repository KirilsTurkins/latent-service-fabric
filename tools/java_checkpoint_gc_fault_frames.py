"""Bounded numeric observation from the explicitly rebuilt Java diagnostic node."""
import re

from tools.phase2_operator_process import require
from tools.rust_capsule_project import write_json

ROW = re.compile(
    rb'^LSF-JAVA-GC-FAULT:([0-9]{1}):([0-9]{1,10}):([0-9]{1,20}):([0-9]{1,20})\r?$',
    re.M,
)


def frames(stderr):
    require(len(stderr) <= 262144, 'java-checkpoint-gc-fault-stderr-bound')
    rows = []
    for match in ROW.finditer(stderr):
        require(len(rows) < 8, 'java-checkpoint-gc-fault-frame-bound')
        ordinal, function, module_offset, function_offset = map(int, match.groups())
        require(ordinal == len(rows) and function <= 0xffffffff
                and max(module_offset, function_offset) <= 0xffffffffffffffff,
                'java-checkpoint-gc-fault-frame-sequence-or-range')
        rows.append({'ordinal': ordinal, 'function': function,
            'moduleOffset': module_offset, 'functionOffset': function_offset})
    return rows


def capture(node, native, component, output):
    node.drain()
    rows = frames(node.buffers[1])
    require(rows, 'java-checkpoint-gc-numeric-fault-frames-required')
    write_json(output / 'numeric-fault-frames.json', {
        'schemaVersion': 'latent.java.checkpoint-gc-fault.diagnostic.v1',
        'node': native,
        'component': component,
        'frames': rows,
        'rawStderrRetained': False,
        'runtimeQualification': False,
        'diagnosticIoMayPerturbTimingAndTerminalObservation': True,
    })
