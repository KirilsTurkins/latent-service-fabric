#!/usr/bin/env python3
"""Capture a fixed local dependency and compile the paired Go checkpoint fixtures."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.application_dependencies import prepare
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded
from tools.go_application_dependencies import configure, resolve
from tools.go_capsule_project import create, validate
from tools.go_dependency_authoring import review
from tools.go_guest.compiler import Compiler
from tools.guest_dependency_inputs import capture_source
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, inventory, write_json
from tools.stage_runtime_wit import stage

MODULE = 'example.invalid/worker'
VERSION = 'v0.0.0'
PROFILES = {'go-component-activation-v1', 'go-component-activation-v2'}
TRANSFORM = 'go-compiler-checkpoints/vendor/example.invalid/worker/worker.go'
GO_IDENTITY = {'name': 'go', 'digest': 'sha256:de0ae3e082ce7599eae4fb69fa2ef1e43b8f31ffd3fce62cdf81930aa9005050',
               'size': 17256487}


def authenticate_go(path: Path) -> dict:
    identity = file_identity(path, 'go')
    if identity != GO_IDENTITY:
        raise ValueError('Go-captured-goto-reference-compiler-drift')
    return identity


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Go-captured-goto-duplicate-transformation-field')
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError('Go-captured-goto-nonfinite-transformation-value')


def goto_site(source: bytes) -> dict:
    marker = b'goto again'
    if source.count(marker) != 1:
        raise ValueError('Go-captured-goto-source-ambiguous')
    offset = source.index(marker)
    previous = source.rfind(b'\n', 0, offset)
    return {'line': 1 + source[:offset].count(b'\n'),
            'column': offset + 1 if previous < 0 else offset - previous,
            'suspendable': True}


def selected_dependency(closure, native: dict, files: dict[str, bytes]) -> dict:
    rows = [row for row in closure.lock['artifacts']
            if row['metadata'].get('module') == MODULE]
    nodes = [node for node in native['nodes'] if node.get('path') == MODULE]
    if len(rows) != 1 or len(nodes) != 1:
        raise ValueError('Go-captured-goto-selected-module-ambiguous')
    row, node = rows[0], nodes[0]
    if (row['role'] != 'application' or row['metadata'].get('assetType') != 'local-module'
            or row['metadata'].get('version') != VERSION or node['id'] != row['id']
            or node.get('version') != VERSION or node.get('indirect') is not False
            or node.get('main') or not node.get('replacement')):
        raise ValueError('Go-captured-goto-selected-module-changed')
    edges = [edge for edge in native['edges'] if edge.get('owner') == native['module']
             and edge.get('selected') == row['id']]
    if len(edges) != 1:
        raise ValueError('Go-captured-goto-direct-edge-missing')
    recorded = {item['path']: (item['digest'], item['size']) for item in row['files']}
    expected = {name: (digest(raw), len(raw)) for name, raw in files.items()}
    if len(recorded) != len(row['files']) or recorded != expected:
        raise ValueError('Go-captured-goto-source-inventory-changed')
    for name, raw in files.items():
        if (closure.work / row['mount'] / name).read_bytes() != raw:
            raise ValueError('Go-captured-goto-materialization-changed')
    return {'module': MODULE, 'version': VERSION, 'artifact': row['id'],
            'sourceDigest': digest(files['worker.go']), 'moduleDigest': digest(files['go.mod']),
            'inputIdentity': closure.identity, 'lockDigest': digest(closure.lock_bytes)}


def validate_transformation(raw: bytes, source: bytes, profile: str) -> dict:
    if not isinstance(raw, bytes) or len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-captured-goto-transformation-size')
    parsed = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if parsed.get('profile') != profile or not isinstance(parsed.get('automaticTransformations'), list):
        raise ValueError('Go-captured-goto-transformation-profile')
    rows = [row for row in parsed['automaticTransformations'] if row.get('name') == TRANSFORM]
    site = goto_site(source)
    if profile == 'go-component-activation-v2':
        if (len(rows) != 1 or rows[0].get('upstreamDigest') != digest(source)
                or rows[0].get('sites', []).count(site) != 1
                or not isinstance(rows[0].get('adaptedDigest'), str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', rows[0]['adaptedDigest'])
                or rows[0]['adaptedDigest'] == rows[0]['upstreamDigest']):
            raise ValueError('Go-captured-goto-transformation-missing')
    elif profile == 'go-component-activation-v1':
        if rows:
            raise ValueError('Go-captured-goto-negative-was-checkpointed')
    else:
        raise ValueError('Go-captured-goto-profile')
    return {'sourceSite': site, 'transformationsDigest': digest(raw)}


def native_reference(output, commands, compiler, source, closure):
    reference = output / 'native-reference'
    reference.mkdir()
    configure(closure, reference)
    (reference / 'ordinary.go').write_bytes(source.replace(b'package export_tests_caller_api\n', b'package main\n', 1))
    (reference / 'main.go').write_text('package main\nimport("fmt";"os";"strconv")\n'
        'func main(){n,e:=strconv.ParseUint(os.Args[1],10,32);if e!=nil{panic(e)};fmt.Println(Run(uint32(n)))}\n')
    binary = reference / 'reference'
    previous, previous_root = dict(commands.environment), commands.root
    commands.environment.update(GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOFLAGS='-mod=readonly',
                                 GOPROXY='off', GOSUMDB='off')
    commands.root = reference
    modes = [0, 1, 4, 5, 6, 7, 8]
    try:
        commands.run('captured-checkpoints-native-build', compiler.paths['go'], 'build', '-o', binary, '.')
        for mode in modes:
            if commands.run('captured-checkpoints-native-' + str(mode), binary, str(mode)).strip() != b'42':
                raise ValueError('Go-captured-checkpoints-native-reference-output')
    finally:
        commands.environment.clear()
        commands.environment.update(previous)
        commands.root = previous_root
    return {'qualification': 'reviewed-fixture-only', 'fixture': 'checkpoints-captured', 'modes': modes,
            'output': 42, 'freshProcessPerMode': True, 'sourceDigest': digest(source),
            'binaryDigest': digest(binary.read_bytes()), 'runtimeOverlay': False,
            'dependencies': 'same-reviewed-graph-offline'}


def qualify(output: Path, profile: str) -> dict:
    if profile not in PROFILES:
        raise ValueError('Go-captured-goto-profile')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        original = ROOT / 'sdk/go-guest/runtime/checkpoints-captured-conformance'
        source = (original / 'main.go').read_bytes()
        files = {name: (original / 'module' / name).read_bytes() for name in ('go.mod', 'worker.go')}
        module = output / 'reviewed-local-module'
        module.mkdir()
        for name, raw in files.items():
            (module / name).write_bytes(raw)
        project = create(output / 'project', 'greeting', runtime_profile=profile)
        (project / 'src/main.go').write_bytes(source)
        wit_source = ROOT / 'sdk/go-guest/runtime/checkpoints-conformance'
        (project / 'wit/world.wit').write_bytes((wit_source / 'world.wit').read_bytes())
        document = json.loads((project / 'capsule-project.json').read_bytes())
        document['world'] = 'tests:caller/service@1.0.0'
        (project / 'capsule-project.json').write_bytes(json.dumps(document, indent=2).encode() + b'\n')
        go = shutil.which('go')
        if go is None:
            raise ValueError('missing-pinned-go-compiler-tool:go')
        go = Path(go).resolve(strict=True)
        go_identity = authenticate_go(go)
        environment = output / 'environment'
        environment.mkdir()
        edit_environment = build_environment(environment)
        edit_environment.update(GOTOOLCHAIN='local', GOWORK='off', GOENV='off', GOFLAGS='')
        run_bounded([str(go), 'mod', 'edit', '-require=' + MODULE + '@' + VERSION,
                     '-replace=' + MODULE + '=' + str(module)], project, edit_environment, 10, 16384)
        candidate = project / 'target/captured-checkpoints.candidate.json'
        candidate.parent.mkdir()
        resolve(project, candidate, go=go)
        review(project, candidate, digest(candidate.read_bytes()))
        if authenticate_go(go) != go_identity:
            raise ValueError('Go-captured-goto-reference-compiler-mutated')
        observed = capture_source(project, 'go')
        validate(observed.files)
        work = output / 'work'
        for name, raw in observed.files.items():
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        commands = Commands(work, output, build_environment(environment))
        closure = prepare(project, work, output, 'go')
        if closure is None or closure.lock['selection']['runtimeProfile'] != profile:
            raise ValueError('Go-captured-goto-closure-profile')
        native_bytes = (project / 'go-resolved.lock.json').read_bytes()
        dependency = selected_dependency(closure, json.loads(native_bytes), files)
        compiler = Compiler(output / 'compiler', work / 'vendor/lsf/sdk/go-guest', commands,
                            source_root=project / 'src', application_closure=closure, runtime_profile=profile)
        component, bindings = compiler.compile(work / 'src', work / 'wit', document['world'],
                                                output / 'build', runtime_profile=profile)
        reference = native_reference(output, commands, compiler, source, closure) if profile.endswith('-v2') else None
        observed.check_unchanged()
        closure.check_unchanged()
        compiler.check_unchanged()
        if authenticate_go(go) != go_identity:
            raise ValueError('Go-captured-goto-reference-compiler-mutated')
        if source != (original / 'main.go').read_bytes() or any(
                (module / name).read_bytes() != raw or (original / 'module' / name).read_bytes() != raw
                for name, raw in files.items()):
            raise ValueError('Go-captured-goto-source-changed')
        transformation = validate_transformation((output / 'go-runtime-transformations.json').read_bytes(),
                                                 files['worker.go'], profile)
        dependency.update(transformation, nativeGraphDigest=digest(native_bytes))
        (output / 'src').mkdir()
        (output / 'src/main.go').write_bytes(source)
        (output / 'dependency-source').mkdir()
        for name, raw in files.items():
            (output / 'dependency-source' / name).write_bytes(raw)
        stage(output / 'wit', wit_source)
        overlay = json.loads((output / 'build/runtime-overlay/overlay.json').read_bytes())['Replace']
        transformations = [{'upstreamDigest': digest(Path(before).read_bytes()),
                            'adaptedDigest': digest(Path(after).read_bytes())}
                           for before, after in sorted(overlay.items())]
        record = {'formatVersion': 1, 'profile': profile, 'fixture': 'checkpoints-captured',
                  'sourceDigest': digest(source), 'componentDigest': digest(component.read_bytes()),
                  'bindingDigest': digest(inventory({name: json.dumps(value, sort_keys=True).encode()
                                                     for name, value in bindings.items()})),
                  'tools': compiler.materials, 'transformations': transformations,
                  'sourceUnchanged': True, 'ordinarySource': True, 'capturedDependency': dependency,
                  'containment': compiler.isolation.receipt, 'signedExecution': 'not-run',
                  'qualification': 'compile-and-native-reference-only' if reference else 'compile-only'}
        if reference:
            record['nativeReference'] = reference
        write_json(output / 'GO-ACTIVATION-COMPILE.json', record)
        return record
    except BaseException as error:
        write_json(output / 'GO-ACTIVATION-FAILED.json', {'status': 'failed', 'reason': str(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-profile', choices=sorted(PROFILES), required=True)
    args = parser.parse_args()
    result = qualify(args.output, args.runtime_profile)
    print(json.dumps({key: result[key] for key in ('profile', 'fixture', 'componentDigest',
                                                    'capturedDependency', 'signedExecution', 'qualification')}))
