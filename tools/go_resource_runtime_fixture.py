"""Captured ordinary embedded readers held across managed Go callbacks.

File construction and normal dependency capture do not qualify component
execution. The fixture installs no logger, executor, transport or resource hook.
"""
from __future__ import annotations
import json
from pathlib import Path
import shutil

from tools.application_dependencies import LOCK, verify_inputs
from tools.go_capsule_project import create
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot

PROFILE = 'go-component-activation-v5'
PACKAGES = ('outside.example.test/resource-runtime-library', 'outside.example.test/resource-runtime-data')
DATA = {'text.txt':'Gr\u00fc\u00dfe\0\u96ea\n'.encode(), 'binary.bin':bytes((0,255,128,65,13,10)), 'empty.bin':b''}
LOG = 'latent:log/log@0.1.0'
DATA_SOURCE = b'''package data
import ("embed"; "io"; "io/fs")
//go:embed text.txt binary.bin empty.bin
var resources embed.FS
func Open() fs.File {
    input, err := resources.Open("binary.bin")
    if err != nil { panic("resource binary missing") }
    return input
}
func Check() {
    text, err := resources.ReadFile("text.txt")
    if err != nil || string(text) != "Gr\\u00fc\\u00dfe\\x00\\u96ea\\n" { panic("resource UTF8 changed") }
    input, err := resources.Open("empty.bin")
    if err != nil { panic("empty resource missing") }
    var one [1]byte
    n, err := input.Read(one[:])
    if n != 0 || err != io.EOF || input.Close() != nil { panic("empty resource stream changed") }
}
'''
LIBRARY_SOURCE = b'''package library
import (
    "crypto/rand"
    "encoding/hex"
    "io"
    "io/fs"
    "log"
    "sort"
    "strings"
    "sync/atomic"
    "time"
    data "outside.example.test/resource-runtime-data"
)
var calls atomic.Uint32
func logged(value string) {
    if err := log.Output(1, value); err != nil { panic("ordinary standard logger refused output") }
}
func read(input fs.File) string {
    value, err := io.ReadAll(input)
    if err != nil { panic("embedded stream read failed") }
    return hex.EncodeToString(value)
}
func Run(mode string) string {
    if calls.Add(1) != 1 { panic("resource callback state survived retirement") }
    data.Check()
    first, second := data.Open(), data.Open()
    defer first.Close(); defer second.Close()
    var prefix [2]byte
    if n, err := io.ReadFull(first, prefix[:]); n != 2 || err != nil || prefix != [2]byte{0,255} {
        panic("first independent reader position changed")
    }
    switch mode {
    case "parallel":
        gate, ready, completed := make(chan struct{}), make(chan struct{}, 2), make(chan string, 2)
        for _, item := range []struct{label string; input fs.File}{{"first",first},{"second",second}} {
            go func(label string, input fs.File) {
                ready <- struct{}{}
                <-gate
                <-time.After(time.Millisecond)
                value := read(input)
                var entropy [8]byte
                if n, err := rand.Read(entropy[:]); n != 8 || err != nil { panic("approved callback entropy failed") }
                if time.Now().UnixMilli() <= 1<<32 { panic("callback wall clock lost full width") }
                logged("resource-go:callback:"+label+":entropy=8:wall64=1")
                completed <- label+":"+value
            }(item.label,item.input)
        }
        <-ready; <-ready
        if len(completed) != 0 { panic("resource callbacks completed before their genuine gate") }
        close(gate)
        values := []string{<-completed,<-completed}; sort.Strings(values)
        if values[0] != "first:80410d0a" || values[1] != "second:00ff80410d0a" {
            panic("concurrent embedded readers shared position or bytes")
        }
        return "resource-go|parallel="+strings.Join(values,"+")+"|entropy=16|wall64=1|fresh=1"
    case "pending":
        completed := make(chan string)
        go func() {
            timer := time.NewTimer(time.Hour)
            defer timer.Stop()
            logged("resource-go:pending:timer-accepted")
            <-timer.C
            logged("resource-go:late-callback-must-not-run")
            completed <- read(second)
        }()
        return <-completed
    case "trap":
        time.AfterFunc(time.Hour,func(){ logged("resource-go:late-trap-callback"); _ = read(second) })
        panic("resource-go:requested-root-trap")
    case "callback-error":
        time.AfterFunc(time.Millisecond,func(){
            logged("resource-go:callback-error:"+read(second))
            panic("resource-go:requested-callback-error")
        })
        select {}
    case "clear":
        var fired atomic.Bool
        timer := time.AfterFunc(time.Hour,func(){ fired.Store(true); logged(read(second)) })
        if !timer.Stop() { panic("resource callback timer was not stopped") }
        <-time.After(time.Millisecond)
        if fired.Load() { panic("cleared resource callback ran") }
    case "fresh":
    default: panic("unknown resource callback mode")
    }
    if value := read(second); value != "00ff80410d0a" { panic("second reader position leaked") }
    logged("resource-go:fresh:ordinary")
    return "resource-go|"+mode+"=00ff80410d0a|empty=0|fresh=1"
}
'''
EXPECTED = {'parallel':'resource-go|parallel=first:80410d0a+second:00ff80410d0a|entropy=16|wall64=1|fresh=1',
            'fresh':'resource-go|fresh=00ff80410d0a|empty=0|fresh=1',
            'clear':'resource-go|clear=00ff80410d0a|empty=0|fresh=1'}


def project(directory: Path, outside: Path, *, late_completion=False, runtime_profile=PROFILE):
    require(type(late_completion) is bool, 'resource-Go-closed-late-selector')
    from tools.go_guest.queues import PROFILE as QUEUE_PROFILE
    require(runtime_profile in (PROFILE, QUEUE_PROFILE) and (not late_completion or runtime_profile == PROFILE),
            'resource-Go-closed-runtime-profile')
    require(directory.parent.resolve(strict=True) == outside.parent.resolve(strict=True)
            and ROOT not in outside.parents and outside.parent.resolve(strict=True) != ROOT,
            'resource-Go-independent-originals')
    app = create(directory,'greeting',runtime_profile=runtime_profile);before=snapshot(app)
    outside.mkdir(mode=0o700)
    for name,identity in zip(('library','data'),PACKAGES,strict=True):
        target=outside/name;target.mkdir()
        manifest='module '+identity+'\n\ngo 1.27.3\n'
        if name=='library':manifest+='require '+PACKAGES[1]+' v0.0.0\n'
        (target/'go.mod').write_bytes(manifest.encode())
    library = LIBRARY_SOURCE
    if late_completion:
        from tools.go_resource_late import library_source
        library = library_source(library)
    (outside/'library/library.go').write_bytes(library)
    (outside/'data/data.go').write_bytes(DATA_SOURCE)
    for name,raw in DATA.items():(outside/'data'/name).write_bytes(raw)
    source=before['src/main.go'];marker=b'func Greet(name string) wit.Result[string, string] {'
    require(source.count(marker)==source.count(b'import (')==1,'resource-Go-original-template')
    source=source.replace(b'import (',b'import (\n    resource "'+PACKAGES[0].encode()+b'"',1)
    source=source.replace(marker,marker+b'\n    if strings.HasPrefix(name, "resource-runtime:") { return wit.Ok[string, string](resource.Run(strings.TrimPrefix(name, "resource-runtime:"))) }',1)
    (app/'src/main.go').write_bytes(source)
    wit=before['wit/world.wit'];require(wit.count(b'world service {')==1,'resource-Go-original-world')
    wit=wit.replace(b'world service {',b'world service {\n    import '+LOG.encode()+b';',1)
    (app/'wit/world.wit').write_bytes(wit)
    for name,raw in snapshot(ROOT/'wit/platform/log').items():
        target=app/'wit/deps/log'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    descriptor=json.loads(before['capsule-project.json']);descriptor['limits']['logBytes']=16384
    (app/'capsule-project.json').write_bytes((json.dumps(descriptor,indent=2)+'\n').encode())
    sdk=json.loads(before['sdk-lock.json']);sdk['template'].update(sourceDigest=digest(source),witDigest=digest(wit))
    (app/'sdk-lock.json').write_bytes((json.dumps(sdk,indent=2)+'\n').encode())
    return app,{'profile':runtime_profile,'source':digest(inventory(snapshot(app))),'outside':digest(inventory(snapshot(outside))),
                'sdkLock':digest(read_file(app/'sdk-lock.json')),'applicationLoggerOrExecutorHook':False,
                'nativeThreadsQualified':False,'compilerExecuted':False,'signedExecution':'pending'}


def capture(app: Path, outside: Path, go: Path, *, runtime_profile=PROFILE):
    from tools.go_guest.queues import PROFILE as QUEUE_PROFILE
    require(runtime_profile in (PROFILE, QUEUE_PROFILE), 'resource-Go-closed-capture-profile')
    descriptor=json.loads(read_file(app/'capsule-project.json'))
    require(descriptor.get('runtimeProfile')==runtime_profile,'resource-Go-capture-project-profile')
    from tools import go_native_authoring as native, go_dependency_authoring as review
    from tools.go_application_dependencies import resolve
    sdk=read_file(app/'sdk-lock.json')
    for identity,path in zip(PACKAGES,(outside/'library',outside/'data'),strict=True):
        native.edit(app,'add',identity=identity,version='v0.0.0',local=path,go=go)
    native.create_lock(app,go=go)
    candidate=app/'target/resource-runtime-candidate.json';candidate.parent.mkdir(exist_ok=True)
    lock=resolve(app,candidate,go=go)
    selected=[r for r in lock['artifacts'] if r['metadata'].get('module') in PACKAGES]
    by_name={r['metadata']['module']:r for r in selected}
    require(len(selected)==2 and set(by_name)==set(PACKAGES)
            and by_name[PACKAGES[1]]['id'] in by_name[PACKAGES[0]]['dependencies']
            and all(r['metadata']['version']=='v0.0.0' and r['role']=='application' for r in selected)
            and not lock['executableInputs'],'resource-Go-exact-pure-transitive-graph')
    review.review(app,candidate,digest(read_file(candidate)))
    verified=verify_inputs(app,'go')
    require(verified is not None and verified.lock['selection']['runtimeProfile']==runtime_profile
            and read_file(app/'sdk-lock.json')==sdk,'resource-Go-exact-reviewed-profile')
    root=outside.resolve(strict=True)
    require(not outside.is_symlink() and all(not p.is_symlink() and p.resolve(strict=True).parent==root
            for p in (outside/'library',outside/'data')),'resource-Go-owned-originals')
    for path in (outside/'library',outside/'data'):shutil.rmtree(path)
    require(verify_inputs(app,'go').identity==verified.identity,'resource-Go-offline-captured-closure')
    return {'acceptedLock':digest(read_file(app/LOCK)),'outsideOriginalsRemoved':True,
            'applicationResourceBridge':False,'catalogueRegistration':False,'signedExecution':'pending'}
