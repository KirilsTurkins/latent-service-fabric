"""Read unchanged native timer hooks for the explicit TypeScript HTTP profile."""
from __future__ import annotations

import re

ENVIRONMENT = 'LSF_GO_NODE_STOP_TIMER_OBSERVER'
PREFIX = b'LSF-GO-NODE-STOP-TIMER-V1'
MAXIMUM_STDERR = 262144
MAXIMUM_RECORDS = 16
MAXIMUM_EVENTS = 15
MODES = {'pending', 'drain'}
EVENTS = {'start-accepted', 'next-entered', 'root-close'}


def observe(stderr):
    result = {'formatVersion': 1, 'qualification': False, 'records': [],
        'status': 'not-observed', 'invalidMarkerCount': 0, 'overflow': False,
        'scope': 'two-public-native-hook-ids-explicit-typescript-64-8-8-profile'}
    if type(stderr) is not bytes or len(stderr) > MAXIMUM_STDERR:
        return {**result, 'status': 'invalid-source'}
    markers, seen, counts = 0, set(), {'pending': 0, 'drain': 0}
    for line in stderr.splitlines():
        if not line.startswith(PREFIX):
            continue
        markers += 1
        if markers > MAXIMUM_RECORDS or len(line) > 128:
            result['invalidMarkerCount'] += 1
            continue
        if line == PREFIX + b'|overflow':
            if result['overflow']:
                result['invalidMarkerCount'] += 1
            result['overflow'] = True
            continue
        fields = line.split(b'|')
        if (len(fields) != 7 or fields[0] != PREFIX or fields[1] not in {b'pending', b'drain'}
                or fields[2] not in {b'start-accepted', b'next-entered', b'root-close'}
                or any(re.fullmatch(rb'0|[1-9][0-9]{0,1}', value) is None for value in fields[3:])):
            result['invalidMarkerCount'] += 1
            continue
        sequence, tasks, waits, timers = map(int, fields[3:])
        mode = fields[1].decode('ascii')
        if not (1 <= sequence <= MAXIMUM_EVENTS and sequence not in seen and counts[mode] < 8
                and tasks <= 64 and waits <= 8 and timers <= 8):
            result['invalidMarkerCount'] += 1
            continue
        seen.add(sequence)
        counts[mode] += 1
        result['records'].append({'mode': mode,
            'event': fields[2].decode('ascii'), 'sequence': sequence,
            'tasks': tasks, 'waits': waits, 'timers': timers})
    result['records'].sort(key=lambda row: row['sequence'])
    if result['invalidMarkerCount']:
        result['status'] = 'invalid-marker'
    elif result['overflow']:
        result['status'] = 'overflow'
    elif result['records']:
        result['status'] = 'observed'
    return result
