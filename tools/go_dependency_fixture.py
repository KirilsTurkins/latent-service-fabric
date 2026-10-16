"""Real Go module/resource fixture, independent of application dispatch."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from tools.build_observation import build_environment
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.go_application_dependencies import resolve
from tools import go_native_authoring as native_authoring


def direct_libraries(declaration: dict, native: dict, artifacts: list[dict], required: dict) -> list[dict]:
    """Attribute fixture calls to native direct application selections."""
    root = declaration.get('Module', {}).get('Path')
    main = [row for row in native.get('nodes', []) if row.get('main')]
    if not root or native.get('module') != root or len(main) != 1 or main[0].get('path') != root:
        raise ValueError('Go qualification root association changed')
    requirements = declaration.get('Require', [])
    if len({row['Path'] for row in requirements}) != len(requirements):
        raise ValueError('Go qualification direct requirement is ambiguous')
    rows = []
    for module, (version, api) in required.items():
        selected = [row for row in requirements if row['Path'] == module]
        nodes = [row for row in native['nodes'] if row.get('path') == module]
        captured = [row for row in artifacts if row['metadata'].get('module') == module
                    and row['metadata'].get('assetType') in {'local-module', 'selected-module-source'}]
        if len(selected) != 1 or selected[0].get('Version') != version or selected[0].get('Indirect', False) is not False:
            raise ValueError('Go qualification library is not an independent direct application requirement')
        if len(nodes) != 1 or nodes[0].get('version') != version or nodes[0].get('indirect') is not False:
            raise ValueError('Go qualification native selection is not direct')
        if len(captured) != 1 or captured[0]['role'] != 'application' or captured[0]['id'] != nodes[0]['id'] \
                or captured[0]['metadata'].get('version') != version:
            raise ValueError('Go qualification direct library capture changed')
        if not any(edge['owner'] == root and edge.get('selected') == captured[0]['id']
                   for edge in native.get('edges', [])):
            raise ValueError('Go qualification direct root edge is missing')
        rows.append({'artifact': captured[0]['id'], 'module': module, 'version': version,
                     'ordinaryApi': api, 'selection': 'application-root-direct'})
    return rows


def install(project: Path, outside: Path, go: Path) -> dict:
    outside.mkdir(mode=0o700)
    library = outside / 'developer-owned-library'
    library.mkdir()
    identity = 'outside.example.test/developer-owned-module'
    (library / 'go.mod').write_text('module ' + identity + '\n\ngo 1.27.2\n\nrequire github.com/mattn/go-runewidth v0.0.16\n', encoding='ascii')
    resource = b'Hello, '
    (library / 'greeting.txt').write_bytes(resource)
    (library / 'message.txt').write_text('Gr\u00fc\u00dfe', encoding='utf-8')
    (library / 'data.bin').write_bytes(bytes((0, 255, 65, 128)))
    (library / 'prefix.go').write_text('''//go:build sdk_dependency_qualification

package developer

import (
    _ "embed"
    "runtime"
    "github.com/mattn/go-runewidth"
)

//go:embed greeting.txt
var greeting string

//go:embed message.txt
var message string

//go:embed data.bin
var data []byte

var calls uint32
var retained [][]byte

func deferred() bool {
    value := 0
    func() { defer func() { value++ }() }()
    return value == 1
}

func recovered() (ok bool) {
    defer func() { ok = recover() == "ordinary library panic" }()
    panic("ordinary library panic")
}

func Exercise(mode string) {
    if calls != 0 || message != "Gr\\u00fc\\u00dfe" || len(data) != 4 ||
        data[0] != 0 || data[1] != 255 || data[2] != 65 || data[3] != 128 ||
        !deferred() || !recovered() {
        panic("captured Go resources, defer/recover or fresh activation state changed")
    }
    calls++
    switch mode {
    case "panic":
        panic("captured library requested trap")
    case "memory":
        for {
            retained = append(retained, make([]byte, 1024*1024))
            runtime.KeepAlive(retained)
        }
    case "spin":
        for { calls++ }
    }
}

//go:generate false

func Prefix() string {
    if runewidth.StringWidth("\u00c5") != 1 || runewidth.StringWidth("\u4e16\u754c") != 4 {
        panic("captured third-party Unicode module produced a wrong result")
    }
    return greeting
}
''', encoding='utf-8')
    source = project / 'src/main.go'
    before = source.read_bytes()
    after = before.replace(b'import (', b'import (\n    "github.com/mattn/go-runewidth"\n    developer "' + identity.encode() + b'"')
    after = after.replace(b'"Hello, " + name + "!"', b'applicationPrefix(name) + name + "!"')
    if after == before or b'"Hello, " + name + "!"' in after:
        raise ValueError('Go dependency qualification source hook changed')
    after += b'''
func applicationPrefix(name string) string {
    developer.Exercise(name)
    prefix := developer.Prefix()
    if runewidth.StringWidth("Hello, ") != 7 || runewidth.StringWidth("\xe4\xb8\x96\xe7\x95\x8c") != 4 {
        panic("direct application Unicode module produced a wrong result")
    }
    return prefix
}
'''
    source.write_bytes(after)
    added = native_authoring.edit(project, 'add', identity=identity, version='v0.0.0', local=library, go=go)
    native_authoring.edit(project, 'add', identity='github.com/mattn/go-runewidth', version='v0.0.16', go=go)
    locked = native_authoring.create_lock(project, go=go, tags=['sdk_dependency_qualification'])
    with tempfile.TemporaryDirectory(prefix='lsf-go-fixture-declaration-') as temporary:
        owned = Path(temporary)
        environment = build_environment(owned)
        environment.update(GOTOOLCHAIN='local', GOWORK='off', GOENV='off', CGO_ENABLED='0',
            GOOS='wasip1', GOARCH='wasm', GOCACHE=str(owned / 'cache'), GOMODCACHE=str(owned / 'modules'),
            HOME=str(owned / 'home'), USERPROFILE=str(owned / 'home'), GOPROXY='off',
            GOSUMDB='off', GONOPROXY='none', GOFLAGS='-mod=readonly')
        declaration = json.loads(run_bounded([str(go), 'mod', 'edit', '-json'], project, environment,
                                             10, 1024 * 1024).stdout)
    candidate = project / 'target/qualification.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    captured = resolve(project, candidate, go=go, selected={'tags': ['sdk_dependency_qualification']})
    from tools.go_dependency_authoring import review, status
    from tools.application_dependency_store import DependencyError
    review(project, candidate, digest(candidate.read_bytes()))
    reviewed_mod = (project / 'go.mod').read_bytes()
    accepted_lock = (project / 'latent.dependencies.lock.json').read_bytes()
    stale_controls = []
    for operation in ('update', 'remove'):
        native_authoring.edit(project, operation, identity=identity, version='v0.0.1' if operation == 'update' else None,
                              local=library if operation == 'update' else None, go=go)
        try:
            status(project)
        except DependencyError:
            stale_controls.append(operation)
        else:
            raise ValueError('Go authoring edit retained stale accepted capture')
        if (project / 'latent.dependencies.lock.json').read_bytes() != accepted_lock:
            raise ValueError('Go authoring edit changed accepted capture')
        (project / 'go.mod').write_bytes(reviewed_mod)
        if status(project)['status'] != 'verified':
            raise ValueError('Go exact reviewed declaration restoration failed')
    selected = {row['metadata'].get('module') for row in captured['artifacts']}
    if not {'github.com/mattn/go-runewidth', 'github.com/rivo/uniseg', identity} <= selected:
        raise ValueError('native Go qualification graph did not capture required transitive/local modules')
    application_libraries = direct_libraries(declaration,
        json.loads((project / 'go-resolved.lock.json').read_bytes()), captured['artifacts'],
        {'github.com/mattn/go-runewidth': ('v0.0.16', 'runewidth.StringWidth'),
         identity: ('v0.0.0', 'developer.Prefix')})
    if library.resolve(strict=True).parent != outside.resolve(strict=True):
        raise ValueError('qualification cleanup escaped its owned dependency directory')
    shutil.rmtree(library)
    return {'formatVersion': 1, 'thirdParty': 'github.com/mattn/go-runewidth/v0.0.16',
            'transitives': ['github.com/rivo/uniseg'], 'developerOwned': identity,
            'sourceDigest': digest(after), 'resourceDigest': digest(resource),
            'recoveryCases': ['panic', 'memory', 'spin', 'normal-defer-recover', 'fresh-state'],
            'resourceDigests': {'message.txt': digest('Gr\u00fc\u00dfe'.encode()),
                                'data.bin': digest(bytes((0, 255, 65, 128)))},
            'applicationLibraries': application_libraries, 'nativeDeclarationDigest': digest(canonical(declaration)),
            'authoringWorkflow': {'add': added, 'nativeLock': locked, 'staleCaptureRejected': stale_controls,
                                 'exactReviewedDeclarationRestored': True},
            'tags': ['sdk_dependency_qualification'], 'offlineOriginals': 'unavailable-after-capture',
            'nativeGraphDigest': digest((project / 'go-resolved.lock.json').read_bytes()), 'generators': 'never-executed'}
