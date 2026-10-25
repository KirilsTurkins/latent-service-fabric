"""Four fixed ordinary-global cases; source fixtures, never published packages."""
import json
from tools.rust_capsule_project import ROOT, digest, read_file, read_json, snapshot
from tools.typescript_guest.project import create, validate
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

FIXTURE = 'sdk/typescript-guest/probes/buffer-globals'
WORLD = 'examples:typescript-buffer-globals/service@1.0.0'
SOURCES = ('main.ts', 'transitive.ts', 'dependency.ts')
CASES = ('initializer-aliases', 'timer-global', 'caught-ceiling', 'fresh-after-refusal')
LIMITS = {'cpuFuel': 1000000000, 'memoryBytes': 134217728, 'wallTimeLimitMillis': 120000,
          'logBytes': 0, 'outboundRequests': 0, 'childCalls': 0, 'effectCount': 0,
          'blobReadBytes': 0, 'blobWriteBytes': 0, 'stateReadBytes': 0, 'stateWriteBytes': 0}
REFERENCE = {'tasks': 32, 'executors': 2, 'queuedWork': 32, 'waits': 8,
             'timers': 8, 'results': 8, 'nativeOwners': 128}


def project(directory):
    app = create(directory, 'greeting', 'my-greeting', runtime_profile=IMPORT_PROFILE)
    config = read_json(app/'capsule-project.json')
    config.update(world=WORLD, limits=dict(LIMITS))
    (app/'capsule-project.json').write_bytes((json.dumps(config, indent=2)+'\n').encode())
    for name in SOURCES:
        (app/'src'/name).write_bytes(read_file(ROOT/FIXTURE/name))
    world = read_file(ROOT/FIXTURE/'world.wit')
    (app/'wit/world.wit').write_bytes(world)
    lock = read_json(app/'sdk-lock.json')
    lock['template'].update(sourceDigest=digest(read_file(app/'src/main.ts')), witDigest=digest(world))
    (app/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    verify(app)
    return app


def verify(app):
    files = snapshot(app)
    config, _lock, _pins = validate(files)
    if (config['world'] != WORLD or config['runtimeProfile'] != IMPORT_PROFILE or config['limits'] != LIMITS
            or config['name'] != 'my-greeting' or config['service'] != 'examples/my-greeting'
            or config['tenant'] != 'examples'):
        raise ValueError('buffer-globals-closed-project')
    for name in SOURCES:
        if files['src/'+name] != read_file(ROOT/FIXTURE/name):
            raise ValueError('buffer-globals-probe-drift')
    if files['wit/world.wit'] != read_file(ROOT/FIXTURE/'world.wit'):
        raise ValueError('buffer-globals-world-drift')
    if set(name for name in files if name.startswith('wit/')) != {'wit/world.wit'}:
        raise ValueError('buffer-globals-world-closure')
    if set(name for name in files if name.startswith('src/')) != {'src/'+name for name in SOURCES}:
        raise ValueError('buffer-globals-probe-closure')
    return files
