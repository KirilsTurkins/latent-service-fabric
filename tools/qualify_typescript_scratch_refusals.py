"""Actual reachable node:fs refusal under the captured public ECMAScript profile."""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.application_dependencies import verify_inputs
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, write_json
from tools.sdk_scratch_fixture import typescript_project
from tools.typescript_guest.build import RECIPE
from tools.typescript_guest.compiler import Compiler
from tools.typescript_dependency_authoring import source_files

CASES = ('open', 'create', 'temp')
MARKER = b'standard-runtime-module-not-installed:node:fs:spidermonkey-public-sync-v1'
MAX_OUTPUT = 4*1024*1024
MAX_SECONDS = 1100


def observed(output, completed):
    require(completed.returncode == 1 and type(completed.stdout) is bytes and type(completed.stderr) is bytes
            and len(completed.stdout)+len(completed.stderr) <= MAX_OUTPUT, 'scratch-typescript-completed-refusal-required')
    require(not any(os.path.lexists(output/name) for name in ('BUILD-COMPLETE.json', 'component.wasm', 'package')),
            'scratch-typescript-no-success-artifact')
    failure = read_json(output/'BUILD-FAILED.json')
    rows = failure.get('commands')
    require(type(failure.get('formatVersion')) is int and failure['formatVersion'] == 1
            and failure.get('stage') == 'compile' and type(rows) is list and 1 <= len(rows) <= 128,
            'scratch-typescript-actual-compiler-phase')
    require(all(type(row) is dict and set(row) == {'stage', 'exitCode', 'seconds'}
            and type(row['stage']) is str and type(row['exitCode']) is int
            and type(row['seconds']) in (int, float) and math.isfinite(row['seconds'])
            and 0 <= row['seconds'] <= 300 for row in rows), 'scratch-typescript-command-record-shape')
    require(rows[-1]['stage'] == 'bundle' and rows[-1]['exitCode'] != 0
            and all(row['exitCode'] == 0 and row['stage'] not in {'bundle', 'componentize', 'compose', 'package'}
                    for row in rows[:-1]), 'scratch-typescript-reachable-bundle-refusal-required')
    stderr = read_file(output/'logs'/f'{len(rows)-1:02d}-bundle.stderr.txt', MAX_OUTPUT)
    require(MARKER in stderr, 'scratch-typescript-exact-uninstalled-module-diagnostic')
    return {'status': 'refused', 'boundary': 'captured-reachable-bundle-import',
        'module': 'node:fs', 'profile': 'spidermonkey-public-sync-v1',
        'reason': 'standard-runtime-module-not-installed', 'runtimeFilesystemExecutionClaimed': False,
        'compilerProcessCompleted': True, 'rawDiagnosticsPublished': False}


def qualify(output, tools, contracts_tool, packager):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'scratch-typescript-unprivileged-linux-python313-required')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'scratch-typescript-output-outside-checkout')
    output = fresh(output)
    started = time.monotonic()
    materials = {name: file_identity(ROOT/name) for name in (*dict.fromkeys(RECIPE),
        'tools/sdk_scratch_fixture.py', 'tools/qualify_typescript_scratch_refusals.py')}
    binaries = {name: file_identity(path, 512*1024*1024) for name, path in
        (('contracts', contracts_tool), ('packager', packager))}
    observer = object.__new__(Compiler)
    original_tools = observer.identity(tools)
    rows = []
    stage = 'captured-source'
    try:
        for case in CASES:
            require(time.monotonic()-started < MAX_SECONDS, 'scratch-typescript-total-deadline')
            work = fresh(output/case)
            stage = case+'-normal-npm-capture'
            app, captured = typescript_project(work/'application', work/'outside', case)
            selected = verify_inputs(app, 'typescript').lock
            source = inventory(source_files(app))
            artifact = work/'build'
            stage = case+'-actual-compiler-refusal'
            completed = run_bounded_result([sys.executable, '-B', str(ROOT/'tools/typescript_capsule.py'),
                'build', str(app), '--tools', str(tools), '--contracts-tool', str(contracts_tool),
                '--packager', str(packager), '--repository', 'https://github.com/KirilsTurkins/latent-service-fabric',
                '--output', str(artifact)], cwd=ROOT, env=build_environment(work),
                timeout_seconds=min(300, MAX_SECONDS-(time.monotonic()-started)), max_output_bytes=MAX_OUTPUT)
            refusal = observed(artifact, completed)
            require(inventory(source_files(app)) == source and verify_inputs(app, 'typescript').lock == selected
                    and read_file(artifact/'source-inputs.json') == source, 'scratch-typescript-source-changed')
            require(read_json(artifact/'recipe-inputs.json') == {name: {'digest': materials[name]['sha256'],
                'size': materials[name]['bytes']} for name in dict.fromkeys(RECIPE)},
                'scratch-typescript-actual-recipe-mismatch')
            containment = read_json(artifact/'compiler-containment.json', 32*1024*1024)
            require(containment['network'] == 'denied' and containment['credentials'] == 'not-inherited',
                    'scratch-typescript-compiler-not-contained')
            rows.append({'case': case, 'capture': captured, 'observation': refusal,
                'sourceDigest': digest(source), 'compilerInputs': file_identity(artifact/'compiler-inputs.json', 8*1024*1024)})
        require(time.monotonic()-started < MAX_SECONDS and observer.identity(tools) == original_tools
                and materials == {name: file_identity(ROOT/name) for name in materials}
                and binaries == {name: file_identity(path, 512*1024*1024) for name, path in
                    (('contracts', contracts_tool), ('packager', packager))}, 'scratch-typescript-final-input-drift')
        record = {'schemaVersion': 'latent.typescript.scratch-refusals.v1', 'status': 'passed',
            'cases': rows, 'materials': materials, 'nativeTools': binaries,
            'compilerInstallationUnchanged': True, 'signedRuntimeQualificationPerformed': False,
            'scratchStorageImplemented': False, 'fullTicketQualification': False}
        write_json(output/'qualification.json', record)
        return record
    except BaseException as error:
        write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage, 'completedCases': len(rows),
            'errorCategory': type(error).__name__, 'fullTicketQualification': False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'tools', 'contracts-tool', 'packager'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.output, args.tools, args.contracts_tool, args.packager)['status']}))
