"""A finite repository-owned Buffer fixture; no published dependency claim."""
import json
from tools.rust_capsule_project import ROOT, digest, read_file, read_json, snapshot
from tools.typescript_guest.project import create, validate
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

FIXTURE = 'sdk/typescript-guest/probes/node-buffer'
WORLD = 'examples:typescript-buffer/service@1.0.0'
CASES = ('aliases', 'views-and-copy', 'utf8-boundaries', 'finite-codecs',
         'integer-ranges', 'fill-concat-compare', 'profile-ceilings', 'relative-fixture-only')


def project(directory):
    app = create(directory, 'greeting', 'my-greeting', runtime_profile=IMPORT_PROFILE)
    config = read_json(app/'capsule-project.json')
    config['world'] = WORLD
    (app/'capsule-project.json').write_bytes((json.dumps(config, indent=2)+'\n').encode())
    for name in ('main.ts', 'relative-fixture.ts'):
        (app/'src'/name).write_bytes(read_file(ROOT/FIXTURE/name))
    world = read_file(ROOT/FIXTURE/'world.wit')
    (app/'wit/world.wit').write_bytes(world)
    lock = read_json(app/'sdk-lock.json')
    lock['template'].update(sourceDigest=digest(read_file(app/'src/main.ts')), witDigest=digest(world))
    (app/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    validate(snapshot(app))
    return app
