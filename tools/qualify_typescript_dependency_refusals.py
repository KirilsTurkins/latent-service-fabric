"""Observe five real captured-module compiler refusals, without a runtime claim."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.application_dependencies import verify_inputs
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, write_json
from tools.typescript_dependency_authoring import source_files
from tools.typescript_guest.build import RECIPE
from tools.typescript_guest.compiler import Compiler
from tools.typescript_guest.project import create

CASES = (
    ('dynamic-import', 'bundle', 'dynamic module loading or uncaptured CommonJS is unsupported'),
    ('eval', 'bundle', 'reachable-dynamic-code-or-module-loading-unsupported'),
    ('native-addon', 'bundle', 'bundle-input-outside-captured-source-or-profile'),
    ('snapshot-clock', 'componentize', 'snapshot-time-clock-observation-unsupported'),
    ('snapshot-entropy', 'componentize', 'snapshot-time-entropy-observation-unsupported'),
)
CLI = ROOT / 'tools/typescript_capsule.py'
PACKAGE = 'outside-ingestion-refusal'
MAX_DIAGNOSTICS = 4 * 1024 * 1024
MAX_CASE_SECONDS = 300
MAX_SECONDS = 1800


def fixture_files(case):
    require(case in {row[0] for row in CASES}, 'typescript-refusal-case-unknown')
    sources = {
        'dynamic-import': "export function negative(text) { return import('./loaded.mjs').then(row => row.value + text); }\n",
        'eval': "export function negative(text) { return globalThis.eval('text'); }\n",
        'native-addon': "export { negative } from './addon.node';\n",
        'snapshot-clock': "const observed = Date.now(); export function negative(text) { return String(observed) + text; }\n",
        'snapshot-entropy': "const observed = Math.random(); export function negative(text) { return String(observed) + text; }\n",
    }
    declaration = {'name': PACKAGE, 'version': '1.0.0', 'type': 'module',
        'exports': {'types': './index.d.ts', 'import': './index.mjs'},
        'scripts': {'prepare': 'node forbidden.cjs'}}
    files = {'package.json': json.dumps(declaration, sort_keys=True).encode(),
        'index.d.ts': b'export function negative(text: string): string;\n',
        'index.mjs': sources[case].encode(),
        'forbidden.cjs': b'throw new Error("implicit package scripts are forbidden");\n'}
    if case == 'dynamic-import':
        files['loaded.mjs'] = b'export const value = "reachable";\n'
    if case == 'native-addon':
        files['addon.node'] = b'not a host native executable\n'
    return files


def install_case(project, outside, case, commands):
    files = fixture_files(case)
    outside = fresh(outside)
    for name, raw in files.items():
        with (outside / name).open('xb') as stream:
            stream.write(raw)
    source = project / 'src/main.ts'
    before = read_file(source)
    hook = b'return `Hello, ${clean}!`;'
    require(before.count(hook) == 1, 'typescript-refusal-original-template-required')
    source.write_bytes(b'import { negative } from "outside-ingestion-refusal";\n'
                       + before.replace(hook, b'return negative(clean);'))
    commands.run(case + '-add', sys.executable, '-B', CLI, 'add', project, PACKAGE, '--path', outside)
    commands.run(case + '-lock', sys.executable, '-B', CLI, 'lock', project)
    candidate = project / 'target/refusal.candidate.json'
    commands.run(case + '-resolve', sys.executable, '-B', CLI, 'resolve', project, '--candidate', candidate)
    commands.run(case + '-review', sys.executable, '-B', CLI, 'review-lock', project,
                 '--candidate', candidate, '--expect', digest(read_file(candidate)))
    accepted = verify_inputs(project, 'typescript').lock
    require(accepted['selection']['runtimeProfile'] == 'spidermonkey-public-sync-v1',
            'typescript-refusal-public-sync-profile-required')
    require(outside.resolve(strict=True).parent == project.parent.resolve(strict=True)
            and not outside.is_symlink(), 'typescript-refusal-owned-originals-required')
    shutil.rmtree(outside)
    return {'package': PACKAGE, 'version': '1.0.0', 'caseSourceDigest': digest(inventory(files)),
        'acceptedLockDigest': digest(read_file(project / 'latent.dependencies.lock.json')),
        'sdkLockDigest': digest(read_file(project / 'sdk-lock.json')),
        'originalsRemovedBeforeBuild': not outside.exists(), 'implicitScriptsExecuted': False}


def observed_refusal(output, case, completed):
    require(case in CASES, 'typescript-refusal-case-unknown')
    name, command, marker = case
    require(completed.returncode == 1 and isinstance(completed.stdout, bytes)
            and isinstance(completed.stderr, bytes)
            and len(completed.stdout) + len(completed.stderr) <= MAX_DIAGNOSTICS,
            'typescript-refusal-not-completed-negative')
    require(not any(os.path.lexists(output / item) for item in
                    ('BUILD-COMPLETE.json', 'component.wasm', 'package')),
            'typescript-refusal-success-artifact-present')
    failure = read_json(output / 'BUILD-FAILED.json', 1024 * 1024)
    records = failure.get('commands')
    require(type(failure.get('formatVersion')) is int and failure.get('formatVersion') == 1
            and failure.get('stage') == 'compile'
            and isinstance(records, list) and 1 <= len(records) <= 128,
            'typescript-refusal-wrong-build-phase')
    require(all(isinstance(row, dict) and set(row) == {'stage', 'exitCode', 'seconds'}
                and isinstance(row['stage'], str) and type(row['exitCode']) is int
                and type(row['seconds']) in (int, float) and math.isfinite(row['seconds'])
                and 0 <= row['seconds'] <= MAX_CASE_SECONDS for row in records),
            'typescript-refusal-invalid-command-record')
    require(records[-1]['stage'] == command and records[-1]['exitCode'] != 0
            and all(row['exitCode'] == 0 for row in records[:-1])
            and not any(row['stage'] in {'strip-projection', 'compose', 'package', 'inspect'} for row in records)
            and (command == 'componentize' or not any(row['stage'] == 'componentize' for row in records)),
            'typescript-refusal-wrong-compiler-command')
    # Only inspect the fixed owned command stream. Never publish raw diagnostics,
    # arbitrary messages, names, paths or their hashes.
    diagnostic = read_file(output / 'logs' / f'{len(records) - 1:02d}-{command}.stderr.txt', MAX_DIAGNOSTICS)
    require(marker.encode() in diagnostic, 'typescript-refusal-expected-diagnostic-missing')
    return {'case': name, 'status': 'refused', 'compilerCommand': command,
        'boundary': 'actual-component-snapshot' if command == 'componentize' else 'actual-bundle-before-componentize',
        'reason': name + '-unsupported', 'successfulComponentProduced': False,
        'completedOwnedProcessCleanup': True}


def qualify(output, tools, contracts_tool, packager):
    require(sys.platform == 'linux', 'typescript-refusal-linux-compiler-required')
    output = fresh(output)
    started = time.monotonic()
    require(output != ROOT and ROOT not in output.parents, 'typescript-refusal-output-outside-source')
    control = fresh(output / 'control')
    commands = Commands(ROOT, control, build_environment(output),
                        deadline_seconds=MAX_SECONDS, command_seconds=120)
    materials = {name: file_identity(ROOT / name) for name in
                 (*dict.fromkeys(RECIPE), 'tools/qualify_typescript_dependency_refusals.py')}
    binaries = {'contracts': file_identity(contracts_tool), 'packager': file_identity(packager)}
    # Reuse the production file/count/byte-bounded observer without constructing
    # or executing a compiler. Failed builds must also preserve its installation.
    compiler_observer = object.__new__(Compiler)
    original_compiler = compiler_observer.identity(tools)
    phase = 'capture'
    rows = []
    try:
        compiler_inputs = None
        for ordinal, case in enumerate(CASES):
            require(time.monotonic() - started < MAX_SECONDS, 'typescript-refusal-overall-deadline')
            owned = fresh(output / f'case-{ordinal}')
            project = create(owned / 'project', 'greeting')
            phase = case[0] + '-capture'
            captured = install_case(project, owned / 'original-package', case[0], commands)
            source = inventory(source_files(project))
            accepted = verify_inputs(project, 'typescript').lock
            artifact = owned / 'build'
            phase = case[0] + '-compile'
            completed = run_bounded_result([sys.executable, '-B', str(CLI), 'build', str(project),
                '--tools', str(tools), '--contracts-tool', str(contracts_tool), '--packager', str(packager),
                '--repository', 'https://github.com/KirilsTurkins/latent-service-fabric', '--output', str(artifact)],
                cwd=ROOT, env=build_environment(owned),
                timeout_seconds=min(MAX_CASE_SECONDS, commands.deadline - time.monotonic()),
                max_output_bytes=MAX_DIAGNOSTICS)
            observed = observed_refusal(artifact, case, completed)
            require(inventory(source_files(project)) == source and verify_inputs(project, 'typescript').lock == accepted,
                    'typescript-refusal-accepted-inputs-changed')
            require(read_file(artifact / 'source-inputs.json') == source
                    and json.loads(read_file(artifact / 'recipe-inputs.json')) == {
                        name: {'digest': identity['sha256'], 'size': identity['bytes']}
                        for name, identity in materials.items() if name in RECIPE},
                    'typescript-refusal-actual-source-or-recipe-drift')
            current_compiler = read_file(artifact / 'compiler-inputs.json', 8 * 1024 * 1024)
            require(compiler_inputs is None or current_compiler == compiler_inputs,
                    'typescript-refusal-compiler-inputs-changed')
            compiler_inputs = current_compiler
            containment = read_json(artifact / 'compiler-containment.json', 32 * 1024 * 1024)
            require(containment['network'] == 'denied' and containment['credentials'] == 'not-inherited',
                    'typescript-refusal-compiler-not-contained')
            rows.append({**observed, 'ordinal': ordinal, 'capture': captured,
                'sourceDigest': digest(source), 'recipeDigest': digest(read_file(artifact / 'recipe-inputs.json')),
                'compilerInputsDigest': digest(current_compiler), 'network': 'denied', 'credentials': 'not-inherited'})
        require(materials == {name: file_identity(ROOT / name) for name in materials}
                and binaries == {'contracts': file_identity(contracts_tool), 'packager': file_identity(packager)}
                and compiler_observer.identity(tools) == original_compiler
                and time.monotonic() - started < MAX_SECONDS, 'typescript-refusal-final-input-drift')
        result = {'schemaVersion': 'latent.typescript.dependency-refusals.v1', 'status': 'passed',
            'cases': rows, 'materials': materials, 'nativeTools': binaries,
            'originalCompilerInstallationDigest': digest(json.dumps(original_compiler,
                sort_keys=True, separators=(',', ':')).encode()),
            'originalCompilerInstallationUnchanged': True,
            'compilerRefusalCases': 3, 'actualSnapshotRefusalCases': 2,
            'successfulComponentCompilationPerformed': False, 'signedRuntimeQualificationPerformed': False,
            'positivePrivateGeneratorWatchProofs': 'separate-source-bound-receipts',
            'hermetic': False, 'publisherAuthenticated': False, 'cleanHost': False,
            'fullTicketQualification': False}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'phase': phase,
                'completedCases': len(rows), 'fullTicketQualification': False})
        except Exception:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--contracts-tool', type=Path, required=True)
    parser.add_argument('--packager', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.output.resolve(), args.tools.resolve(),
        args.contracts_tool.resolve(), args.packager.resolve())['status']}))
