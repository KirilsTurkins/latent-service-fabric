"""One ordinary captured C project; no private threading intrinsics or grants."""
from __future__ import annotations

import json
from pathlib import Path

from tools import c_capsule_project
from tools.c_guest.threading import PROFILE
from tools.rust_capsule_project import read_file, snapshot

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = 'tools/fixtures/c-thread-runtime/'
WORLD = 'examples:c-thread-runtime/service@1.0.0'
API = 'examples:c-thread-runtime/api@1.0.0'
LIMITS = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
          'timers': 8, 'results': 8, 'nativeOwners': 8}
MODES = ('pthread', 'c11', 'mixed', 'invalid', 'pressure', 'root-return',
         'application-error', 'root-trap', 'callback-trap', 'cancel', 'deadline',
         'sync-pthread', 'sync-mixed')


def prepare(directory: Path) -> Path:
    project = c_capsule_project.create(directory, 'greeting', name='c-thread-runtime',
                                       threading_profile=PROFILE)
    (project / 'src/main.c').write_bytes(read_file(ROOT / (FIXTURE + 'main.c')))
    (project / 'src/synchronization.c').write_bytes(read_file(ROOT / (FIXTURE + 'synchronization.c')))
    (project / 'wit/world.wit').write_bytes(read_file(ROOT / (FIXTURE + 'world.wit')))
    config = json.loads(read_file(project / 'capsule-project.json'))
    config['world'] = WORLD
    # One declared envelope for every mode, including cancellation and pressure.
    # It must pay original linear memory AND all actual native stack mappings.
    config['limits'].update(cpuFuel=1_000_000_000, memoryBytes=32 * 1024 * 1024,
                             wallTimeLimitMillis=5000, logBytes=0)
    (project / 'capsule-project.json').write_bytes(
        (json.dumps(config, sort_keys=True, indent=2) + '\n').encode())
    c_capsule_project.validate(snapshot(project))
    return project


def observation(value: str, children: int, *, synchronized: bool = False) -> dict:
    """Consume real child-side observe output, never turn a model into proof."""
    if type(value) is not str or not value.startswith('joined:') or len(value) > 160:
        raise ValueError('c-thread-observed-result')
    parts = value.split(':')[1:]
    if len(parts) != 9 or any(not part.isascii() or not part.isdigit()
                              or len(part) > 20 or str(int(part)) != part for part in parts):
        raise ValueError('c-thread-observed-numeric-shape')
    count, entered, destructed, waits, parked, tasks, results, native, memory = map(int, parts)
    expected_waits = 2 if synchronized is True else 1
    if (type(synchronized) is not bool or synchronized and children != 2
            or type(children) is not int or not 1 <= children <= 3
            or (count, entered, destructed, waits, parked) != (children, children, children, expected_waits, expected_waits)
            or tasks != children + 1 or results != children or native != 2 + 2 * children
            or not 0 < memory <= 32 * 1024 * 1024):
        raise ValueError('c-thread-real-join-owner-witness')
    return {'children': count, 'entered': entered, 'destructed': destructed,
            'waits': waits, 'parkedTasks': parked, 'tasks': tasks, 'results': results,
            'nativeOwners': native, 'nativeMemoryBytes': memory,
            'positivePoint': 'generated activation.observe in child while original parent join is parked',
            'waitForPollPendingClaimed': False}
