"""Two closed ordinary-Go sources, captured by the normal public v7 builder."""
import json
from pathlib import Path

from tools.go_capsule_project import create as create_project, validate
from tools.go_guest.stacks import PROFILE
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot

FIXTURE = 'sdk/go-guest/runtime/stack-ceiling-conformance'
VARIANTS = ('ordinary', 'initializer-cap')
FUEL = 1_000_000_000
MEMORY = 64 * 1024 * 1024
WALL_MILLIS = 120_000
LIMITS = {'cpuFuel':FUEL,'memoryBytes':MEMORY,'wallTimeLimitMillis':WALL_MILLIS,
    'childCalls':0,'outboundRequests':0,'stateReadBytes':0,'stateWriteBytes':0,
    'blobReadBytes':0,'blobWriteBytes':0,'logBytes':0,'effectCount':0}


def source(variant):
    if variant not in VARIANTS:
        raise ValueError('Go-stack-closed-source-variant')
    raw = read_file(ROOT/FIXTURE/'main.go')
    old = b'const initializerDepth uint32 = 2\n'
    if raw.count(old) != 1:
        raise ValueError('Go-stack-initializer-source-contract')
    return raw if variant == 'ordinary' else raw.replace(old,b'const initializerDepth uint32 = 96\n',1)


def create(path: Path, variant: str):
    raw = source(variant)
    app = create_project(path,'greeting',name='go-stack-'+variant,runtime_profile=PROFILE)
    project = json.loads((app/'capsule-project.json').read_bytes())
    project.update(tenant='tenant-a',service='caller',world='tests:caller/service@1.0.0',limits=LIMITS)
    (app/'capsule-project.json').write_text(json.dumps(project,indent=2)+'\n',encoding='utf-8',newline='\n')
    (app/'src/main.go').write_bytes(raw)
    (app/'wit/world.wit').write_bytes(read_file(ROOT/FIXTURE/'world.wit'))
    verify(app,variant)
    return app


def verify(app: Path, variant: str):
    files = snapshot(app)
    project,_,_ = validate(files)
    if (files['src/main.go'] != source(variant) or files['wit/world.wit'] != read_file(ROOT/FIXTURE/'world.wit')
            or project['runtimeProfile'] != PROFILE or project['world'] != 'tests:caller/service@1.0.0'
            or project['tenant'] != 'tenant-a' or project['service'] != 'caller'
            or project['name'] != 'go-stack-'+variant or project['version'] != '1.0.0'
            or {name for name in files if name.startswith('src/')} != {'src/main.go'}
            or json.dumps(project['limits'],sort_keys=True,separators=(',',':')) != json.dumps(LIMITS,sort_keys=True,separators=(',',':'))):
        raise ValueError('Go-stack-detached-probe-world-profile-or-limits')
    for name,raw in files.items():
        if name.startswith('vendor/lsf/') and raw != read_file(ROOT/name.removeprefix('vendor/lsf/')):
            raise ValueError('Go-stack-probe-maintained-SDK-source-drift')
    return {'variant':variant,'sourceDigest':digest(files['src/main.go']),
        'sourceInputsDigest':digest(inventory(files)),'sourceInputs':len(files),'limits':LIMITS}


def reference_source():
    raw = source('ordinary')
    start = raw.index(b'// stack-frame-start\n') + len(b'// stack-frame-start\n')
    end = raw.index(b'// stack-frame-end\n',start)
    return (b'package main\nimport ("runtime"; "time")\nvar liveStack uint64\nvar liveGC uint32\n'
        + raw[start:end] + b'\nfunc main() {}\n')
