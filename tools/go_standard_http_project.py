"""Capture the exact ordinary net/http fixture under the explicit v4 profile."""
import json
from pathlib import Path

from tools.go_capsule_project import create
from tools.go_guest.activation import INITIALIZER_PROFILE
from tools.rust_capsule_project import ROOT, digest, read_file, snapshot
from tools.standard_http.values import SOURCE as VALUE_SOURCE


def project(directory: Path) -> Path:
    app = create(directory,'greeting','go-standard-http',runtime_profile=INITIALIZER_PROFILE)
    fixture = ROOT/'sdk/go-guest/runtime/standard-http-conformance'
    source, wit = read_file(fixture/'main.go'), read_file(fixture/'world.wit')
    (app/'src/main.go').write_bytes(source)
    (app/'src/values.json').write_bytes(read_file(VALUE_SOURCE, 8192))
    (app/'wit/world.wit').write_bytes(wit)
    for name, raw in snapshot(ROOT/'wit/platform/http-v3').items():
        target = app/'wit/deps/http-v3'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as output: output.write(raw)
    descriptor = json.loads(read_file(app/'capsule-project.json'))
    descriptor['world'] = 'examples:go-standard-http/service@1.0.0'
    descriptor['limits']['outboundRequests'] = 8
    (app/'capsule-project.json').write_text(json.dumps(descriptor,indent=2)+'\n',encoding='utf-8')
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template'] = {'name':'go-standard-http','sourceDigest':digest(source),'witDigest':digest(wit)}
    (app/'sdk-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
    return app
