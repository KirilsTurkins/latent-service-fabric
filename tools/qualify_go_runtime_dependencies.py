#!/usr/bin/env python3
"""Capture and compile one reviewed published worker/timer workload, without admission."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.application_dependencies import prepare
from tools.build_observation import build_environment
from tools.build_process import run_bounded
from tools.go_application_dependencies import resolve
from tools.go_capsule_project import create, validate
from tools.go_dependency_authoring import review
from tools.go_dependency_fixture import direct_libraries
from tools.go_guest.activation import INITIALIZER_PROFILE
from tools.go_guest.compiler import Compiler
from tools.guest_dependency_inputs import capture_source
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, inventory, snapshot, write_json
from tools.stage_runtime_wit import stage

LIBRARIES = {'github.com/reactivex/rxgo/v2': ('v2.5.0', 'rxgo.Defer/BackOffRetry/Observe'),
             'github.com/cenkalti/backoff/v4': ('v4.0.0', 'backoff.NewConstantBackOff/WithMaxRetries/WithContext')}
RUNTIME_SOURCES = {'github.com/reactivex/rxgo/v2': ('observable_operator.go', 'iterable_defer.go'),
                   'github.com/cenkalti/backoff/v4': ('retry.go', 'timer.go')}


def library_evidence(declaration: dict, native: dict, artifacts: list[dict]) -> dict:
    libraries = direct_libraries(declaration, native, artifacts, LIBRARIES)
    rxgo, backoff = (next(row for row in libraries if row['module'] == name) for name in LIBRARIES)
    edges = [edge for edge in native['edges'] if edge['owner'] == rxgo['module'] + '@' + rxgo['version']
             and edge['dependency'] == backoff['module'] + '@' + backoff['version']
             and edge['selected'] == backoff['artifact']]
    if len(edges) != 1:
        raise ValueError('Go-published-runtime-library-edge-missing')
    sources = []
    for library in libraries:
        captured = next(row for row in artifacts if row['id'] == library['artifact'])
        native_row = next(row for row in native['nodes'] if row['id'] == library['artifact'])
        if (captured['metadata']['assetType'] != 'selected-module-source' or native_row.get('replacement')
                or captured['metadata'].get('effectiveModule') != library['module']
                or captured['metadata'].get('effectiveVersion') != library['version']):
            raise ValueError('Go-published-runtime-requires-original-module-zip')
        for name in RUNTIME_SOURCES[library['module']]:
            rows = [row for row in captured['files'] if row['path'] == name]
            if len(rows) != 1:
                raise ValueError('Go-published-runtime-source-not-captured')
            sources.append({'module': library['module'], 'version': library['version'], **rows[0]})
    return {'applicationLibraries': libraries, 'libraryEdge': edges[0], 'runtimeSources': sources,
            'runtimeCallPath': ['rxgo.BackOffRetry', 'backoff.Retry', 'backoff.defaultTimer',
                                'time.NewTimer/Reset/Stop'],
            'selectionNote': 'Both API imports are native direct requirements; RxGo also calls backoff internally.'}


def capture(project: Path, go: Path) -> dict:
    # Only native metadata/download commands run at acquisition. No application,
    # test, generator, package hook or guest executes in this stage.
    with tempfile.TemporaryDirectory(prefix='lsf-go-published-lock-') as temporary:
        owned = Path(temporary)
        environment = build_environment(owned)
        environment.update(GOTOOLCHAIN='local', GOWORK='off', GOENV='off', CGO_ENABLED='0',
            GOOS='wasip1', GOARCH='wasm', GOCACHE=str(owned / 'cache'), GOMODCACHE=str(owned / 'modules'),
            HOME=str(owned / 'home'), USERPROFILE=str(owned / 'home'), GOPROXY='https://proxy.golang.org',
            GOSUMDB='sum.golang.org', GONOPROXY='none', GOFLAGS='')
        run_bounded([str(go), 'mod', 'edit', *['-require=' + name + '@' + value[0]
                    for name, value in LIBRARIES.items()]], project, environment, 10, 16384)
        run_bounded([str(go), 'mod', 'tidy'], project, environment, 120, 4 * 1024 * 1024)
        # Generated bindings consume the pinned SDK runtime even though the
        # business source itself imports no Component Model or LSF APIs.
        run_bounded([str(go), 'mod', 'edit', '-require=go.bytecodealliance.org/pkg@v0.2.3'],
                    project, environment, 10, 16384)
        run_bounded([str(go), 'mod', 'download', 'all'], project, environment, 120, 1024 * 1024)
        declaration = json.loads(run_bounded([str(go), 'mod', 'edit', '-json'], project,
                                             environment, 10, 1024 * 1024).stdout)
    candidate = project / 'target/published-runtime.candidate.json'
    candidate.parent.mkdir()
    captured = resolve(project, candidate, go=go)
    review(project, candidate, digest(candidate.read_bytes()))
    native_bytes = (project / 'go-resolved.lock.json').read_bytes()
    return {**library_evidence(declaration, json.loads(native_bytes), captured['artifacts']),
            'nativeGraphDigest': digest(native_bytes), 'nativeDeclarationDigest': digest(
                json.dumps(declaration, sort_keys=True, separators=(',', ':')).encode()),
            'generators': 'never-executed', 'acquisition': 'native-MVS-zip-h1-and-reviewed-lock'}


def native_reference(output: Path, commands: Commands, compiler: Compiler, source: bytes, work: Path) -> dict:
    reference = output / 'native-reference'
    reference.mkdir()
    (reference / 'ordinary.go').write_bytes(source.replace(b'package export_tests_caller_api\n', b'package main\n', 1))
    (reference / 'main.go').write_text('package main\nimport("fmt";"os";"strconv")\n'
        'func main(){n,e:=strconv.ParseUint(os.Args[1],10,32);if e!=nil{panic(e)};fmt.Println(Run(uint32(n)))}\n')
    for name in ('go.mod', 'go.sum'):
        (reference / name).write_bytes((work / name).read_bytes())
    binary = reference / 'reference'
    previous, previous_root = dict(commands.environment), commands.root
    commands.environment.update(GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOFLAGS='-mod=readonly',
                                 GOPROXY='off', GOSUMDB='off')
    commands.root = reference
    try:
        commands.run('published-native-build', compiler.paths['go'], 'build', '-o', binary, '.')
        # The reviewed source and these fixed published versions alone execute
        # on the reference host. Arbitrary captured applications never run here.
        for mode in [0, 2, 3]:
            if commands.run('published-native-' + str(mode), binary, str(mode)).strip() != b'42':
                raise ValueError('Go-published-native-reference-output')
    finally:
        commands.environment.clear()
        commands.environment.update(previous)
        commands.root = previous_root
    return {'qualification': 'reviewed-fixture-only', 'fixture': 'published', 'modes': [0, 2, 3],
            'output': 42, 'freshProcessPerMode': True, 'sourceDigest': digest(source),
            'binaryDigest': digest(binary.read_bytes()), 'runtimeOverlay': False,
            'dependencies': 'same-reviewed-graph-offline'}


def qualify(output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        original = ROOT / 'sdk/go-guest/runtime/published-conformance'
        source = (original / 'main.go').read_bytes()
        project = create(output / 'project', 'greeting', runtime_profile=INITIALIZER_PROFILE)
        (project / 'src/main.go').write_bytes(source)
        (project / 'wit/world.wit').write_bytes((original / 'world.wit').read_bytes())
        document = json.loads((project / 'capsule-project.json').read_bytes())
        document['world'] = 'tests:caller/service@1.0.0'
        write_json(project / 'capsule-project.json', document)
        go = shutil.which('go')
        if go is None:
            raise ValueError('missing-pinned-go-compiler-tool:go')
        evidence = capture(project, Path(go).resolve(strict=True))
        observed = capture_source(project, 'go')
        validate(observed.files)
        work = output / 'work'
        for name, raw in observed.files.items():
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        environment = output / 'environment'
        environment.mkdir()
        commands = Commands(work, output, build_environment(environment))
        closure = prepare(project, work, output, 'go')
        if closure is None or closure.lock['selection']['runtimeProfile'] != INITIALIZER_PROFILE:
            raise ValueError('Go-published-captured-runtime-profile-disagrees')
        compiler = Compiler(output / 'compiler', work / 'vendor/lsf/sdk/go-guest', commands,
            source_root=project / 'src', application_closure=closure, runtime_profile=INITIALIZER_PROFILE)
        reference = native_reference(output, commands, compiler, source, work)
        component, bindings = compiler.compile(work / 'src', work / 'wit', document['world'],
            output / 'build', runtime_profile=INITIALIZER_PROFILE)
        observed.check_unchanged()
        closure.check_unchanged()
        compiler.check_unchanged()
        (output / 'src').mkdir()
        (output / 'src/main.go').write_bytes(source)
        stage(output / 'wit', original)
        record = {'formatVersion': 1, 'profile': INITIALIZER_PROFILE, 'fixture': 'published',
            'sourceDigest': digest(source), 'componentDigest': digest(component.read_bytes()),
            'bindingDigest': digest(inventory({name: json.dumps(value, sort_keys=True).encode()
                                               for name, value in bindings.items()})),
            'tools': compiler.materials, 'sourceUnchanged': source == (original / 'main.go').read_bytes(),
            'sourceSnapshotDigest': digest(inventory(observed.files)), 'ordinarySource': True,
            'dependencyClosure': {**evidence, 'inputIdentity': closure.identity,
                                  'lockDigest': digest(closure.lock_bytes)},
            'containment': compiler.isolation.receipt, 'nativeReference': reference,
            'signedExecution': 'not-run', 'qualification': 'compile-and-native-reference-only'}
        if not record['sourceUnchanged']:
            raise ValueError('Go-published-source-changed')
        write_json(output / 'GO-ACTIVATION-COMPILE.json', record)
        return record
    except BaseException as error:
        write_json(output / 'GO-ACTIVATION-FAILED.json', {'status': 'failed', 'reason': str(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(qualify(parser.parse_args().output)))
