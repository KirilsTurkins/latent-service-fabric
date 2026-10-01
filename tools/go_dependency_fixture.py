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
from tools.go_application_dependencies import resolve, json_stream


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
    after = before.replace(b'import (', b'import (\n    developer "' + identity.encode() + b'"')
    after = after.replace(b'"Hello, " + name + "!"', b'developer.Prefix() + name + "!"')
    if after == before or b'"Hello, " + name + "!"' in after:
        raise ValueError('Go dependency qualification source hook changed')
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
        modules = json_stream(run_bounded([str(go), 'list', '-m', '-mod=mod', '-json', 'all'], project, environment,
                                         120, 4 * 1024 * 1024).stdout)
        run_bounded([str(go), 'mod', 'download', 'all'], project, environment, 120, 1024 * 1024)
    candidate = project / 'target/qualification.candidate.json'
    candidate.parent.mkdir()
    captured = resolve(project, candidate, go=go, selected={'tags': ['sdk_dependency_qualification']})
    (project / LOCK).write_bytes(canonical(captured) + b'\n')
    selected = {row['metadata'].get('module') for row in captured['artifacts']}
    if not {'github.com/mattn/go-runewidth', 'github.com/rivo/uniseg', identity} <= selected:
        raise ValueError('native Go qualification graph did not capture required transitive/local modules')
    if library.resolve(strict=True).parent != outside.resolve(strict=True):
        raise ValueError('qualification cleanup escaped its owned dependency directory')
    shutil.rmtree(library)
    return {'formatVersion': 1, 'thirdParty': 'github.com/mattn/go-runewidth/v0.0.16',
            'transitives': ['github.com/rivo/uniseg'], 'developerOwned': identity,
            'sourceDigest': digest(after), 'resourceDigest': digest(resource),
            'tags': ['sdk_dependency_qualification'], 'offlineOriginals': 'unavailable-after-capture',
            'nativeGraphDigest': digest((project / 'go-resolved.lock.json').read_bytes()), 'generators': 'never-executed'}
