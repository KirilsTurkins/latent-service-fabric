"""Capture ordinary published HTTP clients and a private transitive worker.

Fixture coordinates select evidence only. No runtime/compiler dispatch or
catalogue data is consulted; normal native module resolution owns the closure.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import sys

if __package__ in {None,''}: sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process import run_bounded
from tools.go_application_dependencies import resolve
from tools.go_dependency_authoring import review
from tools.go_dependency_fixture import direct_libraries
from tools.go_native_authoring import create_lock
from tools.go_standard_http_project import project
from tools.rust_capsule_project import ROOT, digest, read_file

LIBRARIES = {
    'github.com/dghubble/sling':('v1.4.0','sling.New/Request/Do with its default http.Client'),
    'github.com/carlmjohnson/requests':('v0.24.3','requests.URL/ToJSON/Fetch with its default http.Client'),
}


def capture_source(directory: Path, outside: Path, identity: str) -> tuple[Path,Path]:
    if (not isinstance(identity,str) or not re.fullmatch(r'outside\.example\.test/http-library/[a-z][a-z0-9-]{0,31}',identity)):
        raise ValueError('go-http-private-module-identity')
    directory, outside = directory.resolve(), outside.resolve()
    if (outside == ROOT or ROOT in outside.parents or directory == outside
            or directory in outside.parents or outside in directory.parents):
        raise ValueError('go-http-private-source-independent-outside-checkout-required')
    outside.mkdir(mode=0o700)
    library = outside/'source'; library.mkdir()
    (library/'go.mod').write_text('module '+identity+'\n\ngo 1.27.2\n',encoding='ascii',newline='\n')
    (library/'marker.txt').write_text('captured-private-worker',encoding='ascii')
    (library/'marker.go').write_text('''package private

import (
    _ "embed"
    "sync"
    "time"
)

//go:embed marker.txt
var marker string

func Marker() string {
    var completed sync.WaitGroup
    result := make(chan string,1)
    completed.Add(1)
    go func(){ time.Sleep(time.Millisecond); result <- marker; completed.Done() }()
    completed.Wait()
    return <-result
}
''',encoding='utf-8')
    app = project(directory)
    source = read_file(ROOT/'sdk/go-guest/runtime/http-library-conformance/main.go')
    if source.count(b'@private-module@') != 1:
        raise ValueError('go-http-library-source-template-drift')
    source = source.replace(b'@private-module@',identity.encode('ascii'))
    (app/'src/main.go').write_bytes(source)
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
    return app,library


def install(app: Path, library: Path, identity: str, go: Path) -> dict:
    source_before = read_file(app/'src/main.go')
    with tempfile.TemporaryDirectory(prefix='lsf-go-http-library-lock-') as temporary:
        owned = Path(temporary)
        environment = build_environment(owned)
        environment.update(GOTOOLCHAIN='local',GOWORK='off',GOENV='off',CGO_ENABLED='0',
            GOOS='wasip1',GOARCH='wasm',GOCACHE=str(owned/'cache'),GOMODCACHE=str(owned/'modules'),
            GOPROXY='https://proxy.golang.org',GOSUMDB='sum.golang.org',GONOPROXY='none',GOFLAGS='')
        for module,(version,_api) in {**LIBRARIES,identity:('v0.0.0','private.Marker')}.items():
            run_bounded([str(go),'mod','edit','-require='+module+'@'+version],app,environment,10,65536)
        run_bounded([str(go),'mod','edit','-replace='+identity+'='+str(library)],app,environment,10,65536)
    locked = create_lock(app,go=go)
    with tempfile.TemporaryDirectory(prefix='lsf-go-http-library-declaration-') as temporary:
        environment = build_environment(Path(temporary))
        environment.update(GOTOOLCHAIN='local',GOWORK='off',GOENV='off',GOPROXY='off',GOSUMDB='off',GOFLAGS='')
        declaration = json.loads(run_bounded([str(go),'mod','edit','-json'],app,environment,10,1024**2).stdout)
    candidate = app/'target/http-libraries.candidate.json'; candidate.parent.mkdir()
    captured = resolve(app,candidate,go=go)
    review(app,candidate,digest(read_file(candidate)))
    selected = direct_libraries(declaration,json.loads(read_file(app/'go-resolved.lock.json')),
        captured['artifacts'],{**LIBRARIES,identity:('v0.0.0','private.Marker ordinary goroutine/WaitGroup/time.Sleep/embed')})
    if read_file(app/'src/main.go') != source_before:
        raise ValueError('go-http-library-application-source-changed')
    # Preserve the original private dependency but make its declared replace
    # location unavailable. Subsequent builds must consume reviewed CAS bytes.
    sealed = library.with_name('retained-original-source')
    if (not library.resolve(strict=True).is_relative_to(app.parent.resolve(strict=True))
            or library.parent.resolve() != sealed.parent.resolve() or sealed.exists()
            or read_file(library/'go.mod') != ('module '+identity+'\n\ngo 1.27.2\n').encode('ascii')):
        raise ValueError('go-http-library-original-source-retention-boundary')
    library.rename(sealed)
    return {'schemaVersion':'latent.go.http-library.capture.v1','libraries':selected,
        'nativeLock':locked,
        'privateModule':identity,'privateOriginUnavailable':not library.exists(),
        'originalPrivateSource':'retained-at-owned-sibling-path','originalLibrarySourcesChanged':False,
        'sourceDigest':digest(source_before),'nativeGraphDigest':digest(read_file(app/'go-resolved.lock.json')),
        'selection':captured['selection'],'transportInjection':False,'catalogueDispatch':False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--private-source',type=Path,required=True)
    parser.add_argument('--identity',required=True)
    parser.add_argument('--go',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    record = install(args.project,args.private_source,args.identity,args.go)
    with args.output.open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record))
