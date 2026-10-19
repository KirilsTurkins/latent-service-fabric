"""Ordinary crypto/rand and WASI syscall calls in captured outside Go modules."""
from __future__ import annotations

from pathlib import Path
import shutil

from tools import go_native_authoring as native, go_dependency_authoring as review
from tools.go_application_dependencies import resolve
from tools.build_snapshot import digest
from tools.dev_workflow.common import require
from tools.rust_capsule_project import snapshot

PARENT = 'outside.example.test/standard-entropy-library'
CHILD = 'outside.example.test/standard-entropy-resource'
VERSION = 'v0.0.0'
PROFILE = 'go-component-async-v1'
CASES = ('baseline', 'read-one', 'read-wide', 'reader', 'text', 'empty', 'syscall', 'syscall-empty')
LIBRARY = r'''package entropy
import (
    "crypto/rand"
    "io"
    "strconv"
    "strings"
    "syscall"
    resource "outside.example.test/standard-entropy-resource"
)
var calls uint32
func Run(mode string) string {
    if calls != 0 || resource.Read() != "Gr\u00fc\u00dfe" { panic("entropy library/resource state leaked") }
    calls++
    count := 0
    switch mode {
    case "baseline":
    case "read-one", "read-wide", "reader", "empty":
        size := 0
        if mode == "read-one" { size = 1 }
        if mode == "read-wide" { size = 257 }
        if mode == "reader" { size = 32 }
        bytes := make([]byte, size)
        var err error
        if mode == "reader" { count, err = io.ReadFull(rand.Reader, bytes) } else { count, err = rand.Read(bytes) }
        if err != nil || count != size { panic("ordinary crypto/rand did not fill the requested buffer") }
    case "text":
        text := rand.Text()
        if len(text) != 26 || strings.IndexFunc(text, func(r rune) bool {
            return !('A' <= r && r <= 'Z' || '2' <= r && r <= '7')
        }) != -1 { panic("pinned crypto/rand.Text shape changed") }
        count = len(text)
    case "syscall", "syscall-empty":
        if mode == "syscall" { count = 4096 }
        if syscall.RandomGet(make([]byte, count)) != nil { panic("ordinary syscall.RandomGet failed") }
    case "budget":
        // 17 * 4096 bytes exceeds the unchanged 65536-byte provider allowance.
        // No retry, alternate Reader, seed or clock-derived fallback is used.
        for index := 0; index < 17; index++ {
            if syscall.RandomGet(make([]byte, 4096)) != nil { panic("bounded random source rejected request") }
        }
        return "entropy-budget-unexpected-success"
    case "trap":
        if _, err := rand.Read(make([]byte, 32)); err != nil { panic("entropy unavailable before trap") }
        panic("ordinary entropy library requested trap")
    case "fuel":
        if _, err := rand.Read(make([]byte, 32)); err != nil { panic("entropy unavailable before fuel loop") }
        for { calls++ }
    default: panic("unknown fixed entropy case")
    }
    return "ordinary-entropy:" + mode + "|count=" + strconv.Itoa(count) + "|resource=Gr\u00fc\u00dfe|fresh=1"
}
'''
COUNTS = dict(zip(CASES, (0, 1, 257, 32, 26, 0, 4096, 0)))


def expected(mode: str) -> str:
    return 'ordinary-entropy:' + mode + '|count=' + str(COUNTS[mode]) + '|resource=Gr\u00fc\u00dfe|fresh=1'


def install(project: Path, outside: Path, go: Path) -> dict:
    initial = snapshot(project)
    from tools.rust_capsule_project import decode_json
    descriptor = decode_json(initial['capsule-project.json'])
    require(descriptor.get('runtimeProfile', PROFILE) == PROFILE, 'go-entropy-default-profile-required')
    outside.mkdir(mode=0o700)
    parent, child = outside / 'library', outside / 'resource'
    parent.mkdir(); child.mkdir()
    (parent / 'go.mod').write_bytes(('module ' + PARENT + '\n\ngo 1.27.2\n\nrequire ' + CHILD + ' ' + VERSION + '\n').encode())
    (parent / 'library.go').write_bytes(LIBRARY.encode('utf-8'))
    (child / 'go.mod').write_bytes(('module ' + CHILD + '\n\ngo 1.27.2\n').encode())
    (child / 'resource.go').write_bytes(b'package resource\nimport _ "embed"\n//go:embed message.txt\nvar message string\nvar calls uint32\nfunc Read() string { calls++; if calls != 1 { panic("resource state leaked") }; return message }\n')
    resource = 'Gr\u00fc\u00dfe'.encode('utf-8')
    (child / 'message.txt').write_bytes(resource)
    originals = {name: digest(data) for name, data in snapshot(outside).items()}
    source = initial['src/main.go']
    marker = b'func Greet(name string) wit.Result[string, string] {'
    require(source.count(b'import (') == source.count(marker) == 1, 'go-entropy-original-greeting-shape')
    source = source.replace(b'import (', b'import (\n    entropy "' + PARENT.encode() + b'"', 1)
    source = source.replace(marker, marker + b'\n    if strings.HasPrefix(name, "entropy:") { return wit.Ok[string, string](entropy.Run(strings.TrimPrefix(name, "entropy:"))) }', 1)
    (project / 'src/main.go').write_bytes(source)
    for identity, directory in ((PARENT, parent), (CHILD, child)):
        native.edit(project, 'add', identity=identity, version=VERSION, local=directory, go=go)
    native.create_lock(project, go=go)
    candidate = project / 'target/entropy-candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    lock = resolve(project, candidate, go=go)
    require(lock['selection']['runtimeProfile'] == PROFILE and not lock['executableInputs'],
            'go-entropy-pure-default-capture')
    artifacts = {row['metadata'].get('module'): row for row in lock['artifacts']
                 if row['role'] == 'application' and row['metadata'].get('assetType') == 'local-module'}
    require({PARENT, CHILD} <= set(artifacts)
            and all(artifacts[name]['metadata'].get('version') == VERSION for name in (PARENT, CHILD))
            and artifacts[CHILD]['id'] in artifacts[PARENT]['dependencies'],
            'go-entropy-captured-transitive-modules')
    accepted = candidate.read_bytes()
    review.review(project, candidate, digest(accepted))
    require(review.status(project)['status'] == 'verified'
            and (project / 'latent.dependencies.lock.json').read_bytes() == accepted,
            'go-entropy-exact-capture-review')
    require((project / 'sdk-lock.json').read_bytes() == initial['sdk-lock.json'], 'go-entropy-SDK-lock-mutated')
    for path in (parent, child):
        require(path.resolve(strict=True).parent == outside.resolve(strict=True), 'go-entropy-owned-cleanup')
        shutil.rmtree(path)
    return {'formatVersion': 1, 'profile': PROFILE, 'modules': [PARENT, CHILD], 'version': VERSION,
        'sourceFiles': originals, 'resourceDigest': digest(resource), 'lockDigest': digest(accepted),
        'sdkLockDigest': digest(initial['sdk-lock.json']), 'originalsRemoved': True, 'cases': list(CASES),
        'ordinaryAPIs': ['crypto/rand.Read', 'crypto/rand.Reader', 'crypto/rand.Text', 'syscall.RandomGet'],
        'customReader': False, 'randomPayloadRetained': False, 'compilerExecutionDuringCapture': False}
