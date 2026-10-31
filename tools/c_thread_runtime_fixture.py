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
    (project / 'src/synchronization.h').write_bytes(read_file(ROOT / (FIXTURE + 'synchronization.h')))
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


HTTP_FIXTURE = 'sdk/c-guest/runtime-fixtures/libfetch/'
HTTP_WORLD = 'examples:libfetch/probe@0.1.0'
HTTP_API = 'examples:libfetch/api@0.1.0'
HTTP_CASES = ('normal', 'not-found', 'denied', 'early-close', 'sibling')


def prepare_http(directory: Path) -> Path:
    from tools.c_guest.standard_facilities import FETCH_PROFILE
    project = c_capsule_project.create(directory, 'greeting', name='c-thread-runtime',
                                       threading_profile=PROFILE)
    for target, original in (('src/main.c', 'probe.c'), ('wit/world.wit', 'world.wit')):
        (project / target).write_bytes(read_file(ROOT / (HTTP_FIXTURE + original)))
    config = json.loads(read_file(project / 'capsule-project.json'))
    config.update(world=HTTP_WORLD, runtimeProfile=FETCH_PROFILE)
    # Three ordinary GETs in the sibling cell; node/provider ceilings are unchanged.
    config['limits'].update(cpuFuel=1_000_000_000, memoryBytes=32 * 1024 * 1024,
                            wallTimeLimitMillis=5000, logBytes=0, outboundRequests=3)
    (project / 'capsule-project.json').write_bytes(
        (json.dumps(config, sort_keys=True, indent=2) + '\n').encode())
    c_capsule_project.validate(snapshot(project))
    return project


def http_result(row: dict, case: str) -> None:
    from tools.standard_http.vectors import DOMAIN, PARTIAL, json_bytes
    def checksum(data):
        value = 0
        for byte in data:
            value = (value * 33 + byte) & 0xffffffff
        return str(len(data)) + ':' + str(value)
    expected = {
        'normal': (0, [{'ok': checksum(json_bytes(DOMAIN))}]),
        'not-found': (3, [{'err': 'unavailable'}]),
        'denied': (3, [{'err': 'permission-denied'}]),
        'early-close': (0, [{'ok': 'closed'}]),
        'sibling': (0, [{'ok': checksum(PARTIAL) + ':' + checksum(json_bytes(DOMAIN)) + ':1:1:1'}]),
    }
    if type(row.get('exitCode')) is not int or case not in expected or (row['exitCode'], row['decoded']) != expected[case]:
        raise ValueError('c-libfetch-exact-ordinary-result')


LIBUCL_FIXTURE = 'sdk/c-guest/runtime-fixtures/libucl/'
LIBUCL_CASES = ('normal', 'not-found', 'denied', 'file', 'glob')


def prepare_libucl(directory: Path, outside: Path) -> Path:
    """Normal captured dependency recipe; no configure subprocess or backend glue."""
    from tools.application_dependencies import MANIFEST, LOCK, capture
    from tools.build_snapshot import canonical, digest
    from tools.c_guest.standard_facilities import FETCH_STANDARD_PROFILE
    declaration = json.loads(read_file(ROOT / (LIBUCL_FIXTURE + 'UPSTREAM.json'), 65536))
    originals = snapshot(ROOT / (LIBUCL_FIXTURE + 'upstream'))
    expected = {row['path']: row for row in declaration['files']}
    if (len(originals) != 25 or set(originals) != set(expected)
            or sum(map(len, originals.values())) > 2 * 1024 * 1024
            or any(len(data) != expected[name]['bytes'] or digest(data) != expected[name]['sha256']
                   for name, data in originals.items())):
        raise ValueError('c-libucl-original-source-closure')
    outside.mkdir(mode=0o700)
    for name, data in originals.items():
        target = outside / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    project = c_capsule_project.create(directory, 'greeting', name='c-thread-runtime',
                                       threading_profile=PROFILE)
    for target, original in (('src/main.c', 'probe.c'), ('wit/world.wit', 'world.wit')):
        (project / target).write_bytes(read_file(ROOT / (LIBUCL_FIXTURE + original)))
    config = json.loads(read_file(project / 'capsule-project.json'))
    config.update(world=HTTP_WORLD, runtimeProfile=FETCH_STANDARD_PROFILE)
    config['limits'].update(cpuFuel=1_000_000_000, memoryBytes=32 * 1024 * 1024,
                            wallTimeLimitMillis=5000, logBytes=0, outboundRequests=3)
    (project / 'capsule-project.json').write_bytes(canonical(config) + b'\n')
    dependency = {'formatVersion': 1, 'language': 'c',
        'selection': {'target': 'wasm32-wasi', 'runtimeProfile': FETCH_STANDARD_PROFILE},
        'nativeLocks': [], 'artifacts': [{
            'id': 'vstakhov/libucl/' + declaration['commit'], 'role': 'application',
            'format': 'directory', 'mount': 'dependencies/libucl', 'source': {'path': str(outside)},
            'dependencies': [], 'metadata': {
                'cSources': declaration['cSources'],
                'includeDirectories': declaration['includeDirectories'],
                'defines': declaration['defines'],
                'license': 'BSD-2-Clause AND MIT AND BSD-1-Clause'}}], 'transformations': []}
    (project / MANIFEST).write_bytes(canonical(dependency) + b'\n')
    (project / LOCK).write_bytes(canonical(capture(project)) + b'\n')
    c_capsule_project.validate(snapshot(project))
    return project


def libucl_result(row: dict, case: str) -> None:
    expected = {'normal': (0, [{'ok': 'ucl:7:caf\u00e9:first:\u03bb:0'}]),
                **{name: (3, [{'err': 'include-rejected'}])
                   for name in ('not-found', 'denied', 'file', 'glob')}}
    if type(row.get('exitCode')) is not int or case not in expected or (
            row['exitCode'], row['decoded']) != expected[case]:
        raise ValueError('c-libucl-exact-ordinary-result')


def prepare_http_standard(directory: Path) -> Path:
    """The unchanged current libfetch probe under the expanded normal profile."""
    from tools.c_guest.standard_facilities import FETCH_STANDARD_PROFILE
    project = prepare_http(directory)
    config = json.loads(read_file(project / 'capsule-project.json'))
    config['runtimeProfile'] = FETCH_STANDARD_PROFILE
    (project / 'capsule-project.json').write_bytes(
        (json.dumps(config, sort_keys=True, indent=2) + '\n').encode())
    c_capsule_project.validate(snapshot(project))
    return project
