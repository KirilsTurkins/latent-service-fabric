"""Vary unknown captured Cargo graphs using only a minimal normal Rust recipe.

Hosted Linux qualification; no new runtime compilation, catalogue registration,
implicit executable approval or release publication. Every stage is bounded.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as dependencies
from tools import rust_dependency_authoring as review
from tools import rust_dependency_matrix as matrix
from tools.application_dependency_store import DependencyError, Store
from tools.build_observation import build_environment, resolve_tools
from tools.build_snapshot import canonical, digest
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.qualify_rust_git_components import COMPANIONS, prepared_inputs
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands, RECIPE
from tools.rust_capsule_project import ROOT, create, fresh, inventory, read_file, read_json, snapshot, write_json

MATERIALS = ('tools/qualify_rust_dependency_matrix.py', 'tools/rust_dependency_matrix.py',
             'tools/run_rust_capsule_workflow.py', 'tools/qualify_rust_git_components.py')
SEEDS = ('examples/echo-contract/capsule.json', 'examples/echo-contract/deployment.json')


def stage_recipe(output: Path) -> dict:
    """Copy the exact maintained compile recipe, excluding optional references.

    The SDK/compiler lock remains mandatory inside each ordinary application.
    No production package-eligibility catalogue is invented or substituted.
    """
    names = sorted({*RECIPE, *SEEDS})
    require(len(names) <= 256, 'matrix-recipe-file-bound')
    files = {name: read_file(ROOT / name, 1024 * 1024) for name in names}
    require(sum(map(len, files.values())) <= 16 * 1024 * 1024, 'matrix-recipe-byte-bound')
    output = fresh(output)
    files['tools/__init__.py'] = b''
    for name, raw in files.items():
        destination = output / name
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.write_bytes(raw)
    observed = snapshot(output)
    require(observed == files and not {'Cargo.lock', 'Cargo.toml'} & observed.keys()
            and all(name in {'tools/__init__.py', *RECIPE, *SEEDS} for name in observed),
            'matrix-minimal-recipe-unexpected-input')
    return {'files': json.loads(inventory(files)), 'identity': digest(inventory(files)),
            'scope': 'exact maintained compiler recipe and seeds only; no optional fixture/reference/catalogue inputs',
            'sdkAndCompilerLocks': 'retained-in-normal-application'}


def check_recipe(root: Path, recorded: dict):
    require(json.loads(inventory(snapshot(root))) == recorded['files'], 'matrix-minimal-recipe-mutated')
    for name in recorded['files']:
        if name != 'tools/__init__.py':
            raw = read_file(ROOT / name, 1024 * 1024)
            require({'digest': digest(raw), 'size': len(raw)} == recorded['files'][name], 'matrix-original-recipe-mutated')


class Frontend:
    def __init__(self, root, observed, commands):
        self.root, self.observed, self.commands = root, observed, commands

    def call(self, label, *arguments):
        check_recipe(self.root, self.observed)
        result = self.commands.run(label, sys.executable, '-I', '-B', self.root / 'tools/rust_capsule.py', *arguments)
        check_recipe(self.root, self.observed)
        return result


def refuse_stale(project: Path, candidate: Path) -> str:
    try:
        review.review(project, candidate, digest(read_file(candidate)))
    except DependencyError as error:
        code = str(error)
        require(code in {'dependency-lock-drift-resolve-and-review', 'dependency-native-lock-drift',
                        'cargo-root-manifest-drift-resolve-and-review'}, 'matrix-unexpected-stale-review-error')
        return code
    raise ValueError('matrix-stale-candidate-was-accepted')


def integrity_controls(project: Path, lock: dict, value: dict) -> list[dict]:
    core = next(row for row in lock['artifacts'] if row.get('metadata', {}).get('package') == value['packages']['core'])
    marker = next(row for row in core['files'] if row['path'] == 'src/marker.bin')
    store = Store(project / 'dependency-inputs/objects', create=False)
    original = store.get(marker['digest'], marker['size'])
    path = store.path(marker['digest'])
    require(path.resolve(strict=True).is_relative_to((project / 'dependency-inputs/objects').resolve(strict=True)),
            'matrix-integrity-object-owner')
    observed = []
    try:
        for mode, expected_code in (('missing', 'dependency-artifact-missing-resolve-explicitly'),
                                    ('tampered', 'dependency-artifact-integrity')):
            if mode == 'missing':
                path.unlink()
            else:
                path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            try:
                dependencies.verify_inputs(project, 'rust')
            except DependencyError as error:
                require(str(error) == expected_code, 'matrix-unexpected-integrity-refusal')
                observed.append({'case': mode, 'reason': expected_code, 'compilerExecution': False})
            else:
                raise ValueError('matrix-broken-transitive-was-accepted')
            finally:
                path.write_bytes(original)
    finally:
        path.write_bytes(original)
    require(store.get(marker['digest'], marker['size']) == original
            and dependencies.verify_inputs(project, 'rust') is not None, 'matrix-integrity-control-did-not-restore')
    return observed


def capture(frontend, project, outside, candidate, cargo, value, previous):
    matrix.edit(project, outside, value)
    name = value['packages']['facade']
    arguments = ['update' if value['phase'] else 'add', project, name, '--version', value['version'],
                 '--path', outside / 'facade', '--cargo', cargo]
    if value['phase']:
        arguments += ['--no-default-features', '--feature', 'alternate']
    frontend.call('native-declaration', *arguments)
    selection = ['--features', 'switched', '--no-default-features'] if value['phase'] else []
    frontend.call('capture', 'resolve', project, '--candidate', candidate, '--cargo', cargo, *selection)
    lock, graph = read_json(candidate), read_json(project / 'cargo-resolved.lock.json')
    selected = matrix.captured(lock, graph, value)
    refusal = refuse_stale(project, previous) if previous is not None else None
    frontend.call('exact-lock-review', 'review-lock', project, '--candidate', candidate, '--expect', digest(read_file(candidate)))
    require(review.status(project)['status'] == 'verified'
            and read_file(project / dependencies.LOCK) == read_file(candidate), 'matrix-reviewed-lock-required')
    controls = integrity_controls(project, lock, value)
    result = {'specification': value, 'libraries': selected, 'candidateDigest': digest(read_file(candidate)),
        'graphDigest': digest(read_file(project / 'cargo-resolved.lock.json')),
        'manifestDigest': digest(read_file(project / 'Cargo.toml')), 'staleCandidateRefusal': refusal,
        'transitiveIntegrityControls': controls, 'executableInputs': [], 'catalogueRegistration': False}
    matrix.remove(outside, value)
    result['originalOutsideSources'] = 'removed-before-ordinary-offline-compilation'
    return result


def signed_probe(frontend, project, output, prepared, products, commands, value):
    source = inventory(snapshot(project))
    built = output / 'build'
    frontend.call('offline-component', 'build', project, '--output', built, '--offline',
        '--repository', 'https://github.com/KirilsTurkins/latent-service-fabric',
        '--contracts-tool', products['examples/capsule_contracts'], '--packager', products['examples/package'])
    require(inventory(snapshot(project)) == source and read_json(built / 'cargo-inputs.json')['networkResolution'] is False,
            'matrix-offline-build-mutated-source-or-used-network')
    actual_recipe = read_json(built / 'recipe-inputs.json')
    require(all(name in frontend.observed['files'] and frontend.observed['files'][name] == row
                for name, row in actual_recipe.items()), 'matrix-build-used-unselected-recipe')
    commands.run('sign-matrix-fixture', products['examples/capsule_authoring'], 'demo-sign', output / 'signed',
                 built, *(prepared / 'builds' / name for name in COMPANIONS))
    write_json(output / 'signed/matrix-probe.json', value)
    node = run(products['latent'], products['latentd'], output / 'signed', output / 'node',
               language='rust', captured_rust_matrix=True)
    require(node['status'] == 'passed' and node.get('rustDependencyMatrix', {}).get('status') == 'passed'
            and node['rustDependencyMatrix']['specificationDigest'] == digest(canonical(value))
            and len(node['rustDependencyMatrix']['cases']) == 3,
            'matrix-signed-node-not-qualified')
    marker = read_json(built / 'BUILD-COMPLETE.json')
    releases = [row for row in node['releaseSet']['releases'] if row['name'] == 'my-greeting']
    require(len(releases) == 1 and releases[0]['componentDigest'] == marker['componentDigest']
            and read_json(output / 'signed/matrix-probe.json') == value,
            'matrix-signed-component-or-probe-changed')
    return {'build': marker, 'recipeIdentity': digest(read_file(built / 'recipe-inputs.json')),
            'nodeReceipt': file_identity(output / 'node/workflow.json'), 'probe': node['rustDependencyMatrix']}


def qualify(prepared: Path, output: Path):
    output = fresh(output)
    require(output != ROOT and ROOT not in output.parents, 'matrix-output-must-be-outside-runtime')
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1700, command_seconds=600)
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    stage, observations = 'prepared-inputs', []
    try:
        before, qualified, products = prepared_inputs(prepared)
        if os.name == 'posix':
            for binary in products.values():
                binary.chmod(0o700)
        paths, tools = resolve_tools(tomllib.loads((ROOT / 'tools/toolchain.toml').read_text()), ROOT, commands.environment)
        require(next(row for row in tools if row['name'] == 'cargo')
                == next(row for row in qualified['tools'] if row['name'] == 'cargo'), 'matrix-prepared-compiler-mismatch')
        stage = 'minimal-compiler-recipe'
        recipe_root = output / 'minimal-recipe'
        recipe = stage_recipe(recipe_root)
        frontend = Frontend(recipe_root, recipe, commands)
        nonce = secrets.token_hex(12)
        require(all(nonce.encode() not in read_file(recipe_root / name) for name in recipe['files']),
                'matrix-coordinate-already-in-recipe')
        for graph in (0, 1):
            application = create(output / f'application-{graph}', 'greeting')
            original_sdk = read_file(application / 'sdk-lock.json')
            require(nonce.encode() not in original_sdk and all(nonce.encode() not in raw
                    for raw in snapshot(application / 'vendor').values()), 'matrix-coordinate-already-in-SDK')
            previous, prior_capture = None, None
            for phase in (0, 1):
                stage = f'graph-{graph}-phase-{phase}-capture'
                value = matrix.specification(nonce, graph, phase)
                outside = output / f'originals-{graph}'
                matrix.restore(outside, value)
                phase_output = fresh(output / f'graph-{graph}-phase-{phase}')
                candidate = phase_output / 'candidate.json'
                captured = capture(frontend, application, outside, candidate, paths['cargo'], value, previous)
                if prior_capture is not None:
                    require(captured['candidateDigest'] != prior_capture['candidateDigest']
                            and captured['graphDigest'] != prior_capture['graphDigest']
                            and captured['libraries']['core']['treeDigest'] != prior_capture['libraries']['core']['treeDigest'],
                            'matrix-changed-patch-or-selection-not-bound')
                write_json(phase_output / 'capture.json', captured)
                stage = f'graph-{graph}-phase-{phase}-signed-offline-component'
                require(prepared_inputs(prepared)[:2] == (before, qualified), 'matrix-prepared-inputs-changed')
                execution = signed_probe(frontend, application, phase_output, prepared, products, commands, value)
                require(read_file(application / 'sdk-lock.json') == original_sdk
                        and not outside.exists(), 'matrix-build-restored-originals-or-changed-SDK')
                observations.append({'graph': graph, 'phase': phase, 'capture': captured, **execution})
                previous, prior_capture = candidate, captured
        stage = 'final-integrity'
        check_recipe(recipe_root, recipe)
        require(len(observations) == 4 and len({row['build']['componentDigest'] for row in observations}) == 4
                and inputs('rust') == before and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
                and all(file_identity(binary, 512 * 1024 * 1024) == qualified['binaries'][name]
                        for name, binary in products.items()) and time.monotonic() < commands.deadline,
                'matrix-qualification-inputs-changed')
        result = {'formatVersion': 1, 'status': 'passed', 'scope': 'varied unknown Cargo coordinates and selected offline signed components',
            'materials': materials, 'minimalRecipe': recipe, 'preparedSourceIdentityDigest': qualified['sourceIdentityDigest'],
            'nativeBinaries': qualified['binaries'], 'observations': observations, 'commands': commands.records,
            'publisherAuthenticated': False, 'cleanHost': False, 'releasePublication': 'not-performed',
            'privateGit': 'not-tested', 'networkLibraryPort': 'not-claimed',
            'noStdScope': 'ordinary no_std and alloc dependency crates inside the maintained std component envelope'}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'stage': stage, 'errorCategory': type(error).__name__,
                       'commands': commands.records, 'completedObservations': len(observations), 'materials': materials})
        except Exception:
            pass  # Diagnostic failure cannot replace cancellation or the original qualification error.
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps({'status': qualify(args.prepared_qualification, args.output)['status']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
