"""Capture an ordinary default HttpClient fixture with an async component root."""
from pathlib import Path
import json
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dotnet_guest.project import create
from tools.rust_capsule_project import ROOT, digest, read_file, snapshot


def project(directory: Path) -> Path:
    app = create(directory, 'greeting', 'dotnet-standard-http')
    source = ROOT/'examples/dotnet-standard-http'
    managed, wit = read_file(source/'Main.cs'), read_file(source/'world.wit')
    (app/'src/Main.cs').write_bytes(managed)
    (app/'wit/world.wit').write_bytes(wit)
    for package in ('activation-runtime', 'http-v3', 'random'):
        for name, body in snapshot(ROOT/'wit/platform'/package).items():
            target = app/'wit/deps'/package/name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                output.write(body)
    descriptor = json.loads(read_file(app/'capsule-project.json'))
    descriptor['world'] = 'examples:dotnet-standard-http/service@1.0.0'
    descriptor['limits']['outboundRequests'] = 8
    (app/'capsule-project.json').write_text(json.dumps(descriptor, indent=2)+'\n', encoding='utf-8')
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template'] = {'name': 'dotnet-standard-http', 'sourceDigest': digest(managed), 'witDigest': digest(wit)}
    (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf-8')
    return app
