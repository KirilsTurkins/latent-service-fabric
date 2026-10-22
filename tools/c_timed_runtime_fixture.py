"""One normal captured C project with explicit standard-clock selection."""
import json
from pathlib import Path

from tools import c_thread_runtime_fixture as original
from tools.c_guest import standard_facilities
from tools.c_guest.threading import IMPORTS as THREAD_IMPORTS
from tools.rust_capsule_project import read_file, snapshot
from tools import c_capsule_project

ROOT = original.ROOT
FIXTURE = original.FIXTURE
IMPORTS = (*THREAD_IMPORTS, *standard_facilities.IMPORTS)
MODES = tuple('timed-' + name + suffix for name in (
    'sleep', 'mutex-timeout', 'mutex-notify', 'condition-notify', 'condition-timeout', 'condition-broadcast')
    for suffix in ('', '-c11'))


def prepare(directory: Path) -> Path:
    project = original.prepare(directory)
    (project / 'src/timing.h').write_bytes(read_file(ROOT / (FIXTURE + 'timing.h')))
    config = json.loads(read_file(project / 'capsule-project.json'))
    config['runtimeProfile'] = standard_facilities.PROFILE
    (project / 'capsule-project.json').write_text(json.dumps(config, sort_keys=True, indent=2) + '\n')
    c_capsule_project.validate(snapshot(project))
    return project


def observation(value, mode):
    if type(mode) is not str or mode not in MODES or type(value) is not str or len(value) > 160:
        raise ValueError('c-timed-observation-mode')
    prefix = 'timed:' + mode + ':'
    if not value.startswith(prefix):
        raise ValueError('c-timed-observation-mode')
    parts = value[len(prefix):].split(':')
    if len(parts) != 4 or any(not p.isascii() or not p.isdigit() or len(p) > 20
            or str(int(p)) != p for p in parts):
        raise ValueError('c-timed-observation-shape')
    timers, waits, parked, memory = map(int, parts)
    minimum = 2 if 'broadcast' in mode else 1
    if not (minimum <= timers <= original.LIMITS['timers'] and 2 <= waits <= original.LIMITS['waits']
            and 2 <= parked <= 3 and 0 < memory <= 32 * 1024 * 1024):
        raise ValueError('c-timed-real-owner-witness')
    return {'timers': timers, 'waits': waits, 'parkedTasks': parked, 'nativeMemoryBytes': memory,
        'sourceAssertions': 'two ordinary children with TLS/errno/destructors; real timer and sibling progress; original mutex ownership/reacquisition; lazy zero/invalid sleep',
        'waitForPollPendingClaimed': False}
