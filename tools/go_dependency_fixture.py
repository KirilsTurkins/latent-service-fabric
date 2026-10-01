"""Real Go module/resource fixture, independent of application dispatch."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from tools.application_dependencies import LOCK
from tools.build_observation import build_environment
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.go_application_dependencies import resolve


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
    (library / 'go.mod').write_text('module ' + identity + '\n\ngo 1.27.1\n\nrequire github.com/mattn/go-runewidth v0.0.16\n', encoding='ascii')
    resource = b'Hello, '
    (library / 'greeting.txt').write_bytes(resource)
    (library / 'prefix.go').write_text('''//go:build sdk_dependency_qualification

package developer

import (
    _ "embed"
    "github.com/mattn/go-runewidth"
)

//go:embed greeting.txt
var greeting string

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
    after = after.replace(b'"Hello, " + name + "!"', b'applicationPrefix() + name + "!"')
    if after == before or b'"Hello, " + name + "!"' in after:
        raise ValueError('Go dependency qualification source hook changed')
    after += b'''
func applicationPrefix() string {
    prefix := developer.Prefix()
    if runewidth.StringWidth("Hello, ") != 7 || runewidth.StringWidth("\xe4\xb8\x96\xe7\x95\x8c") != 4 {
        panic("direct application Unicode module produced a wrong result")
    }
    return prefix
}
'''
    source.write_bytes(after)
    with tempfile.TemporaryDirectory(prefix='lsf-go-fixture-lock-') as temporary:
        owned = Path(temporary)
        environment = build_environment(owned)
        environment.update(GOTOOLCHAIN='local', GOWORK='off', GOENV='off', CGO_ENABLED='0',
            GOOS='wasip1', GOARCH='wasm', GOCACHE=str(owned / 'cache'), GOMODCACHE=str(owned / 'modules'),
            HOME=str(owned / 'home'), USERPROFILE=str(owned / 'home'), GOPROXY='https://proxy.golang.org',
            GOSUMDB='sum.golang.org', GONOPROXY='none', GOFLAGS='-tags=sdk_dependency_qualification')
        run_bounded([str(go), 'mod', 'edit', '-require=' + identity + '@v0.0.0', '-replace=' + identity + '=' + str(library)],
                    project, environment, 10, 16384)
        # The explicit native lock stage may add actual MVS requirements/sums.
        # These metadata/download commands never execute go generate or code.
        run_bounded([str(go), 'mod', 'tidy'], project, environment, 120, 4 * 1024 * 1024)
        declaration = json.loads(run_bounded([str(go), 'mod', 'edit', '-json'], project, environment,
                                             10, 1024 * 1024).stdout)
        run_bounded([str(go), 'mod', 'download', 'all'], project, environment, 120, 1024 * 1024)
    candidate = project / 'target/qualification.candidate.json'
    candidate.parent.mkdir()
    captured = resolve(project, candidate, go=go, selected={'tags': ['sdk_dependency_qualification']})
    (project / LOCK).write_bytes(canonical(captured) + b'\n')
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
            'applicationLibraries': application_libraries, 'nativeDeclarationDigest': digest(canonical(declaration)),
            'tags': ['sdk_dependency_qualification'], 'offlineOriginals': 'unavailable-after-capture',
            'nativeGraphDigest': digest((project / 'go-resolved.lock.json').read_bytes()), 'generators': 'never-executed'}
