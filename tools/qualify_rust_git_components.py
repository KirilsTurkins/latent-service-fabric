"""Actual isolated Git-dependency compilation and signed node; no release publication."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment, resolve_tools
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.qualify_rust_git_dependencies import PACKAGE, REVISIONS, offline, require
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands, build
from tools.rust_capsule_project import ROOT, create, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.rust_git_component_fixture import install
from tools.native_runtime.verify import relative

PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
COMPANIONS = ('word-count', 'shipping', 'http-status', 'recovery')
SIGNER_FILES = ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json',
                'package-source.json', 'deployment.json')
MATERIALS = ('tools/qualify_rust_git_components.py', 'tools/rust_git_component_fixture.py',
             'tools/qualify_rust_git_dependencies.py', 'tools/rust_dependency_fixture.py')


def prepared_inputs(prepared: Path) -> tuple[dict, dict, dict]:
    qualified = read_json(prepared / 'qualification.json')
    before = inputs('rust')
    require(qualified['status'] == 'passed' and 'applicationDependencies' in qualified
            and read_json(prepared / 'source-inputs.json') == before
            and (prepared / 'source-inputs.json').read_bytes() == (prepared / 'source-inputs-after.json').read_bytes()
            and digest((prepared / 'source-inputs.json').read_bytes()) == qualified['sourceIdentityDigest'],
            'Git-component-exact-prepared-source-required')
    require(set(qualified['binaries']) == set(PRODUCTS), 'Git-component-exact-five-native-products-required')
    products = {}
    for name in PRODUCTS:
        binary = prepared / 'native-binaries' / name.replace('/', '-')
        require(file_identity(binary, 512 * 1024 * 1024) == qualified['binaries'][name],
                'Git-component-prepared-native-mismatch')
        products[name] = binary
    require(all(read_json(prepared / 'builds' / name / 'BUILD-COMPLETE.json') == qualified['builds'][name]
                for name in COMPANIONS), 'Git-component-prepared-companion-build-changed')
    return before, qualified, products


def bundle(prepared: Path, output: Path) -> dict:
    """Export only public signer materials, not compiler caches, sources or keys."""
    before, qualified, products = prepared_inputs(prepared)
    output = fresh(output)
    selected = {'qualification.json', 'source-inputs.json', 'source-inputs-after.json'}
    selected.update('native-binaries/' + name.replace('/', '-') for name in products)
    for name in COMPANIONS:
        source = read_json(prepared / 'builds' / name / 'package-source.json')
        layers = source['layers']
        require(0 < len(layers) <= 128, 'Git-component-prepared-layer-bound')
        selected.update('builds/' + name + '/' + filename for filename in SIGNER_FILES)
        for row in layers:
            selected.add('builds/' + name + '/' + relative(row['source']))
    require(len(selected) <= 1024, 'Git-component-prepared-file-bound')
    total = 0
    for name in sorted(selected):
        raw = read_file(prepared / name, 512 * 1024 * 1024)
        total += len(raw)
        require(total <= 1024 * 1024 * 1024, 'Git-component-prepared-byte-bound')
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    require(prepared_inputs(output)[:2] == (before, qualified), 'Git-component-bundle-copy-changed')
    result = {'formatVersion': 1, 'status': 'passed', 'files': len(selected), 'bytes': total,
              'scope': 'public native binaries and exact observed companion signer inputs; no keys, caches or original sources'}
    write_json(output / 'bundle.json', result)
    return result


def qualify(prepared: Path, output: Path) -> dict:
    output = fresh(output)
    require(output != ROOT and ROOT not in output.parents, 'Git-component-output-must-be-outside-runtime')
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    stage = 'prepared-inputs'
    try:
        before, qualified, products = prepared_inputs(prepared)
        # Artifact extraction does not retain executable modes. Only the five
        # already identity-checked owned files become executable here.
        if os.name == 'posix':
            for binary in products.values():
                binary.chmod(0o700)
        stage = 'compiler-identity'
        paths, tools = resolve_tools(tomllib.loads((ROOT / 'tools/toolchain.toml').read_text()), ROOT, commands.environment)
        require(next(row for row in tools if row['name'] == 'cargo')
                == next(row for row in qualified['tools'] if row['name'] == 'cargo'),
                'Git-component-prepared-compiler-mismatch')
        stage = 'normal-Git-authoring-and-capture'
        app = create(output / 'application', 'greeting')
        captured = install(app, output / 'outside', paths['cargo'])
        write_json(output / 'capture.json', captured)
        stage = 'fresh-home-locked-offline-metadata'
        observed = offline(app, output / 'offline-metadata', paths['cargo'], *REVISIONS[-1])
        write_json(output / 'offline.json', observed)
        stage = 'isolated-offline-component-builds'
        source = inventory(snapshot(app))
        built = []
        for name in ('first', 'offline-rebuild'):
            artifact = build(app, output / name, products['examples/capsule_contracts'], products['examples/package'],
                             'https://github.com/KirilsTurkins/latent-service-fabric', offline=True)
            require(inventory(snapshot(app)) == source, 'Git-component-build-mutated-source')
            require(read_json(artifact / 'cargo-inputs.json')['networkResolution'] is False,
                    'Git-component-build-performed-network-resolution')
            built.append(artifact)
        stage = 'signing'
        # Recheck companion markers and native identities immediately before
        # the existing strict signer; no compiler ever sees the later demo keys.
        require(prepared_inputs(prepared)[:2] == (before, qualified), 'Git-component-prepared-inputs-changed')
        commands.run('sign-Git-fixture', products['examples/capsule_authoring'], 'demo-sign', output / 'signed',
                     built[0], *(prepared / 'builds' / name for name in COMPANIONS))
        stage = 'signed-node'
        node = node_workflow(products['latent'], products['latentd'], output / 'signed', output / 'node',
                             language='rust', captured_git_component=True)
        require(node['status'] == 'passed' and node.get('capturedGitComponent', {}).get('status') == 'passed'
                and len(node['capturedGitComponent']['cases']) == 3, 'Git-component-node-not-qualified')
        stage = 'final-integrity'
        require(inputs('rust') == before and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
                and all(file_identity(binary, 512 * 1024 * 1024) == qualified['binaries'][name]
                        for name, binary in products.items()), 'Git-component-qualification-inputs-changed')
        require(time.monotonic() < commands.deadline, 'Git-component-qualification-deadline')
        result = {'formatVersion': 1, 'status': 'passed', 'scope': 'actual captured Git source, isolated offline builds and signed/admitted node',
                  'package': PACKAGE, 'capture': captured, 'offline': observed, 'materials': materials,
                  'preparedSourceIdentityDigest': qualified['sourceIdentityDigest'], 'nativeBinaries': qualified['binaries'],
                  'builds': [read_json(path / 'BUILD-COMPLETE.json') for path in built],
                  'nodeReceipt': file_identity(output / 'node/workflow.json'), 'commands': commands.records,
                  'hermetic': False, 'reproducibility': 'not-claimed', 'releasePublication': 'not-performed',
                  'privateGit': 'not-tested', 'catalogueRemoval': 'not-tested'}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        write_json(output / 'FAILED.json', {'status': 'failed', 'stage': stage, 'commands': commands.records,
                   'errorCategory': type(error).__name__, 'materials': materials})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('bundle', 'run'))
    parser.add_argument('--prepared-qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = (bundle if args.operation == 'bundle' else qualify)(args.prepared_qualification, args.output)
    print(json.dumps({'status': result['status'], 'operation': args.operation}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
