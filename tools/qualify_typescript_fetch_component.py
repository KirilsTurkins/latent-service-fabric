#!/usr/bin/env python3
"""Compile the real Fetch-selected engine path; do not infer signed execution."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.phase2_operator_process import require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot
from tools.typescript_guest.build import RECIPE
from tools.typescript_guest.compiler import Compiler
from tools.typescript_guest.fetch_profile import PROFILE
from tools.typescript_guest.project import create, validate
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

FIXTURE = 'sdk/typescript-guest/probes/fetch'
WORLD = 'examples:typescript-fetch/service@1.0.0'


def manifest_summary(value: object) -> dict:
    """Bind every JSON field without retaining an oversized fixture document."""
    hasher, size = hashlib.sha256(), 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    for part in encoder.iterencode(value):
        raw = part.encode('utf-8')
        hasher.update(raw)
        size += len(raw)
    return {'formatVersion': 1, 'encoding': 'canonical-json-sorted-keys-ascii',
        'manifestDigest': 'sha256:' + hasher.hexdigest(), 'manifestBytes': size}


def compiler_manifest_summary(value: dict) -> dict:
    # Compiler.identity still owns the full 32,768-file / 1-GiB validation and
    # check_unchanged compares the complete in-memory table, not this summary.
    return {**manifest_summary(value), 'fileCount': len(value['files']), 'contentBytes': value['bytes']}


def project(directory: Path) -> Path:
    """Use the normal outside-checkout project and immutable SDK capture."""
    app = create(directory, 'greeting', 'typescript-fetch', runtime_profile=IMPORT_PROFILE)
    for name in ('main.ts', 'default-client.ts'):
        (app / 'src' / name).write_bytes(read_file(ROOT / FIXTURE / name))
    wit = read_file(ROOT / FIXTURE / 'world.wit')
    (app / 'wit/world.wit').write_bytes(wit)
    for name, raw in snapshot(ROOT / 'wit/platform/http-v3').items():
        path = app / 'wit/deps/http-v3' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as output:
            output.write(raw)
    value = read_json(app / 'capsule-project.json')
    value['world'] = WORLD
    value['limits']['outboundRequests'] = 1
    (app / 'capsule-project.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    lock = read_json(app / 'sdk-lock.json')
    lock['template'] = {'name': 'typescript-fetch',
        'sourceDigest': digest(read_file(app / 'src/main.ts')), 'witDigest': digest(wit)}
    (app / 'sdk-lock.json').write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    validate(snapshot(app))
    return app


def compilation_evidence(output: Path, engine: dict) -> dict:
    """Refuse a public-sync substitute or a metadata-only success claim."""
    selected = read_json(output / 'typescript-runtime-selection.json')
    compiler = read_json(output / 'compiler.json')
    bundled = read_json(output / 'application.mjs.inputs.json')
    expected = {'digest': engine['coreDigest'], 'size': engine['coreBytes'],
        'profile': IMPORT_PROFILE, 'qualification': 'unknown', 'apiSupport': 'not-evaluated'}
    require(selected.get('profile') == IMPORT_PROFILE
        and selected.get('qualification') == 'unknown'
        and selected.get('apiSupport') == 'not-evaluated'
        and selected.get('engineInput') == engine, 'fetch-component-selected-engine-mismatch')
    require(compiler.get('selectedEngine') == expected
        and compiler.get('selectedCompilerSplicer') is True
        and compiler.get('qualification') == 'unknown', 'fetch-component-real-import-compiler-required')
    require(bundled.get('standardFetchProfile') == PROFILE
        and bundled.get('selection', {}).get('runtimeProfile') == IMPORT_PROFILE
        and bundled.get('selection', {}).get('standardFetchProfile') == PROFILE,
        'fetch-component-automatic-backend-required')
    sources = {row['path'] for row in bundled.get('capturedInputs', [])}
    require({'src/main.ts', 'src/default-client.ts'} <= sources,
        'fetch-component-direct-and-transitive-source-required')
    require(all(isinstance(bundled.get(name), str)
        and len(bundled[name]) == 71 and bundled[name].startswith('sha256:')
        and all(c in '0123456789abcdef' for c in bundled[name][7:])
        for name in ('standardFetchBackendDigest', 'snapshotGuardDigest')),
        'fetch-component-bootstrap-identities-required')
    component = read_file(output / 'component.wasm', 64 * 1024 * 1024)
    require(component[:8] == b'\0asm\x0d\0\x01\0', 'fetch-component-real-component-required')
    return {'component': file_identity(output / 'component.wasm', 64 * 1024 * 1024),
        'selectedEngine': expected, 'standardFetchProfile': PROFILE,
        'backendDigest': bundled['standardFetchBackendDigest'],
        'snapshotGuardDigest': bundled['snapshotGuardDigest'],
        'directAndTransitiveInitialization': 'source-selected; execution-not-observed',
        'asyncFunctionRuntimeExecution': 'not-run', 'signedExecution': 'not-run',
        'providerExecution': 'not-run', 'unchangedPublishedClients': 'not-run'}


def qualify(output: Path, tools: Path, engine: Path, splicer: Path) -> dict:
    output, tools, engine, splicer = (path.resolve() for path in (output, tools, engine, splicer))
    require(output != ROOT and ROOT not in output.parents,
        'fetch-component-output-must-stay-outside-checkout')
    require(all(output != path and output not in path.parents and path not in output.parents
        for path in (tools, engine, splicer)), 'fetch-component-separate-inputs-required')
    fresh(output)
    record = {'schemaVersion': 'latent.typescript.fetch-component.v1', 'status': 'in-progress',
        'fullTicketQualification': False, 'commandLimits': {'overallSeconds': 900, 'perCommandSeconds': 600},
        'engineQualification': 'unknown', 'apiSupport': 'not-evaluated',
        'signedExecution': 'not-run', 'providerExecution': 'not-run'}
    stage = 'capture'
    try:
        app = project(output / 'project')
        before = snapshot(app)
        recipe_names = tuple(dict.fromkeys((*RECIPE, 'tools/qualify_typescript_fetch_component.py',
            *(FIXTURE + '/' + name for name in ('main.ts', 'default-client.ts', 'world.wit')))))
        recipe = {name: read_file(ROOT / name) for name in recipe_names}
        (output / 'source-inputs.json').write_bytes(inventory(before))
        (output / 'recipe-inputs.json').write_bytes(inventory(recipe))
        stage = 'source-bound-compiler'
        commands = Commands(app, output, build_environment(output), deadline_seconds=900, command_seconds=600)
        expected = {name: before['vendor/lsf/sdk/typescript-guest/tools/' + name]
            for name in ('package.json', 'package-lock.json')}
        compiler = Compiler(tools, commands, expected, isolated_workspace=output,
            runtime_profile=IMPORT_PROFILE, engine=engine / 'engine.wasm',
            engine_receipt=engine / 'engine-input.json', splicer=splicer / 'splicer',
            splicer_receipt=splicer / 'splicer-input.json')
        compiler_before = compiler_manifest_summary(compiler.before)
        write_json(output / 'compiler-inputs.json', compiler_before)
        write_json(output / 'compiler-containment.json', manifest_summary(compiler.isolation.receipt))
        stage = 'actual-component'
        compiled = output / 'compiled'
        compiler.compile(app, WORLD, compiled)
        stage = 'evidence-and-integrity'
        record['compilation'] = compilation_evidence(compiled, compiler.engine_metadata)
        after = {name: raw for name, raw in snapshot(app).items()
            if not name.startswith('generated/') and name != 'tsconfig.json'}
        (output / 'source-inputs-after.json').write_bytes(inventory(after))
        require(before == after, 'fetch-component-captured-source-changed')
        require(recipe == {name: read_file(ROOT / name) for name in recipe_names},
            'fetch-component-recipe-changed')
        compiler.check_unchanged()
        compiler_after = compiler_manifest_summary(compiler.identity())
        require(compiler_after == compiler_before, 'fetch-component-compiler-manifest-changed')
        write_json(output / 'compiler-inputs-after.json', compiler_after)
        write_json(output / 'runtime-materials.json', compiler.runtime_materials())
        record.update(status='compiled', sourceIdentityDigest=digest(inventory(before)),
            recipeIdentityDigest=digest(inventory(recipe)), commands=commands.records)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException:
        record.update(status='failed', stage=stage)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'tools', 'engine', 'splicer'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output, args.tools, args.engine, args.splicer)))
