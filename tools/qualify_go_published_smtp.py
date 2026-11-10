#!/usr/bin/env python3
"""Capture one pinned published SMTP graph and build it through Go authoring."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process import run_bounded
from tools.go_application_dependencies import resolve
from tools.go_capsule_build import build
from tools.go_capsule_project import create
from tools.go_dependency_authoring import review
from tools.go_dependency_fixture import direct_libraries
from tools.go_guest.activation import STACK_PROFILE
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot
from tools.stage_runtime_wit import stage

LIBRARIES = {
    'github.com/emersion/go-smtp': ('v0.25.0', 'smtp.Dial/DialStartTLS/Noop/Quit'),
    'github.com/reactivex/rxgo/v2': ('v2.5.0', 'rxgo.Defer/BackOffRetry/Observe'),
    'github.com/cenkalti/backoff/v4': ('v4.0.0', 'backoff.NewConstantBackOff/WithMaxRetries'),
}
SASL = 'github.com/emersion/go-sasl'
SASL_VERSION = 'v0.0.0-20241020182733-b788ff22d5a6'


def graph_evidence(declaration: dict, native: dict, artifacts: list[dict]) -> dict:
    direct = direct_libraries(declaration, native, artifacts, LIBRARIES)
    nodes = {row['path']: row for row in native['nodes']}
    edges = []
    for owner, dependency, path in (
        ('github.com/emersion/go-smtp@v0.25.0', SASL + '@' + SASL_VERSION, SASL),
        ('github.com/reactivex/rxgo/v2@v2.5.0', 'github.com/cenkalti/backoff/v4@v4.0.0',
         'github.com/cenkalti/backoff/v4'),
    ):
        rows = [row for row in native['edges'] if row['owner'] == owner
                and row['dependency'] == dependency and row['selected'] == nodes[path]['id']]
        if len(rows) != 1:
            raise ValueError('Go-published-smtp-transitive-edge-missing')
        edges.append(rows[0])
    sources = []
    for module, version, name in (
        ('github.com/emersion/go-smtp', 'v0.25.0', 'client.go'),
        (SASL, SASL_VERSION, 'sasl.go'),
        ('github.com/reactivex/rxgo/v2', 'v2.5.0', 'observable_operator.go'),
        ('github.com/cenkalti/backoff/v4', 'v4.0.0', 'timer.go'),
    ):
        node = nodes[module]
        selected = [row for row in artifacts if row['id'] == node['id']]
        if (node['version'] != version or node.get('replacement') or len(selected) != 1
                or selected[0]['metadata']['assetType'] != 'selected-module-source'
                or selected[0]['metadata'].get('effectiveModule') != module
                or selected[0]['metadata'].get('effectiveVersion') != version):
            raise ValueError('Go-published-smtp-original-module-required')
        files = [row for row in selected[0]['files'] if row['path'] == name]
        if len(files) != 1:
            raise ValueError('Go-published-smtp-source-not-captured')
        sources.append({'module': module, 'version': version, **files[0]})
    return {'applicationLibraries': direct, 'transitiveEdges': edges, 'moduleSources': sources,
            'smtpRetryPolicy': 'none', 'workerTimer': 'separate RxGo/backoff stage before network',
            'generators': 'never-executed', 'acquisition': 'native-MVS-zip-h1-reviewed-lock'}


def qualify(output: Path, contracts_tool: Path, seconds: int = 1100) -> dict:
    if type(seconds) is not int or not 30 <= seconds <= 1200:
        raise ValueError('Go-published-smtp-deadline-invalid')
    deadline = time.monotonic() + seconds
    output = fresh(output.resolve())
    try:
        fixture = ROOT / 'sdk/go-guest/runtime/published-smtp-conformance'
        source = snapshot(fixture)
        if set(source) != {'main.go', 'world.wit', 'go.mod', 'go.sum'}:
            raise ValueError('Go-published-smtp-fixture-inputs')
        project = create(output / 'project', 'greeting', runtime_profile=STACK_PROFILE)
        (project / 'src/main.go').write_bytes(source['main.go'])
        for name in ('go.mod', 'go.sum'):
            (project / name).write_bytes(source[name])
        stage(project / 'wit', fixture)
        document = json.loads((project / 'capsule-project.json').read_bytes())
        document['world'] = 'examples:go-standard-network/service@1.0.0'
        (project / 'capsule-project.json').write_bytes(json.dumps(document, indent=2).encode() + b'\n')

        go_path = shutil.which('go')
        if go_path is None:
            raise ValueError('missing-pinned-go-compiler-tool:go')
        go = Path(go_path).resolve(strict=True)
        candidate = project / 'target/published-smtp.candidate.json'
        candidate.parent.mkdir()
        captured = resolve(project, candidate, go=go)
        review(project, candidate, digest(candidate.read_bytes()))
        native_bytes = read_file(project / 'go-resolved.lock.json', 16 * 1024 * 1024)
        native = json.loads(native_bytes)
        environment = output / 'declaration-env'
        environment.mkdir()
        env = build_environment(environment)
        env.update(GOTOOLCHAIN='local', GOENV='off', GOWORK='off')
        declaration = json.loads(run_bounded([str(go), 'mod', 'edit', '-json'], project, env,
                                             10, 1024 * 1024).stdout)
        graph = graph_evidence(declaration, native, captured['artifacts'])
        graph['nativeGraphDigest'] = digest(native_bytes)
        graph['lockDigest'] = digest(read_file(project / 'latent.dependencies.lock.json', 16 * 1024 * 1024))

        # The maintained authoring path rechecks the captured graph, builds
        # offline inside its original namespace, and emits its normal receipts.
        authoring = build(project, output / 'authoring', contracts_tool, None,
                          'https://github.com/KirilsTurkins/latent-service-fabric',
                          _deadline=deadline)
        observation = read_file(authoring / 'build-observation.json', 16 * 1024 * 1024)
        completion = json.loads(read_file(authoring / 'BUILD-COMPLETE.json', 1024 * 1024))
        component = read_file(authoring / 'component.wasm', 64 * 1024 * 1024)
        if completion['componentDigest'] != digest(component) or source != snapshot(fixture):
            raise ValueError('Go-published-smtp-source-or-component-changed')
        (output / 'src').mkdir()
        (output / 'src/main.go').write_bytes(source['main.go'])
        stage(output / 'wit', fixture)
        (output / 'build').mkdir()
        (output / 'build/component.wasm').write_bytes(component)
        record = {'profile': STACK_PROFILE, 'sourceUnchanged': True,
                  'sourceDigest': digest(source['main.go']), 'componentDigest': digest(component),
                  'compilerInputsDigest': digest(inventory(source)), 'dependencyClosure': graph,
                  'authoringObservationDigest': digest(observation),
                  'authoringPackageAssembled': completion['packageAssembled']}
        (output / 'GO-SMTP-PUBLISHED-COMPILE.json').write_text(json.dumps(record, indent=2) + '\n')
        return record
    except BaseException:
        (output / 'PUBLISHED-FAILED.json').write_text(json.dumps({'status': 'failed'}) + '\n')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--contracts-tool', required=True, type=Path)
    parser.add_argument('--deadline-seconds', type=int, default=1100)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output, args.contracts_tool, args.deadline_seconds)))
