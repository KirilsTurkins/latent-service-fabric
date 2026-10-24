"""Unchanged published CJS inputs; fixed qualification identities, never admission policy."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.application_dependencies import verify_inputs
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file, read_json, snapshot
from tools.typescript_application_dependencies import resolve
from tools.typescript_dependency_authoring import edit, review, status
from tools.typescript_guest.project import create, validate
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

FIXTURE = 'sdk/typescript-guest/probes/node-buffer-commonjs'
WORLD = 'examples:typescript-buffer/service@1.0.0'
CASES = ('published-equal-xor', 'published-max-unequal-xor', 'published-empty-xor',
         'published-fresh-output', 'published-codec-inputs', 'published-constructor-identity')
SCOPE = 'captured-published-commonjs-six-case-v1'
PACKAGES = {'@types/buffer-xor': {'integrity': 'sha512-OqdCua7QCTupPnJgmyGJUpxWgbuOi0IMIVslXTSePS2o+qDrDB6f2Pg44zRyqhUA5GbFAf39U8z0+mH4WG0fLQ==',
                       'version': '2.0.2'},
 '@types/node': {'integrity': 'sha512-uMzsv9stDdofIZBx4UGh4Z9ZgXnGC9seRDscilBcTHAeOFk67MZg/k9bWVfO+bk4qZmG+l52hRnLwUiH2LnJTg==',
                 'version': '26.6.5'},
 'buffer-xor': {'integrity': 'sha512-eHslX0bin3GB+Lx2p7lEYRShRewuNZL3fUl4qlVJGGiwoPGftmt8JQgk2Y9Ji5/01TnVDo33E5b5O3vUB1HdqQ==',
                'version': '2.0.2'},
 'safe-buffer': {'integrity': 'sha512-rp3So07KcdmmKbGvgaNxQSJr7bGVSVk5S9Eq1F+ppbRo70+YeaDxkw5Dd8NPN+GD6bjnYm2VuPuCXmpuYvmCXQ==',
                 'version': '5.2.1'},
 'undici-types': {'integrity': 'sha512-KTDyRTYX8sWmKXAikPHHSyc63CRPETMctyjKFupcC6OBLXT3xsN0e9aF7m+mIXutFWpUXuedtowG7iLOzp0kQg==',
                  'version': '8.9.0'}}
SOURCE_FILES = {
    'buffer-xor/index.js': 'sha256:90b18bf55895b87dfd6b697f800b37860e58b5a1ab83b53cc066774bc43a90e5',
    'buffer-xor/inplace.js': 'sha256:95aa853ae1b6d2952b96e8c3425007cbae5b25e50f25228838724f0c5b23700b',
    'safe-buffer/index.js': 'sha256:184d5c4a83512e3f49d4d5b52f7073f601f933bad11f1fbb3ad364ca5e6478e1',
}


def verify_probe(files):
    for source, target in (('main.ts', 'src/main.ts'), ('world.wit', 'wit/world.wit')):
        require(files[target] == read_file(ROOT/FIXTURE/source), 'cjs-closed-probe-source')
    selected = json.loads(files['capsule-project.json'])
    require(selected['world'] == WORLD and selected['runtimeProfile'] == IMPORT_PROFILE
        and selected['service'] == 'examples/my-greeting' and selected['tenant'] == 'examples',
        'cjs-closed-probe-profile')
    limits = selected['limits']
    expected = {'cpuFuel': 1000000000, 'memoryBytes': 134217728, 'wallTimeLimitMillis': 120000,
        'childCalls': 0, 'outboundRequests': 0, 'stateReadBytes': 0, 'stateWriteBytes': 0,
        'blobReadBytes': 0, 'blobWriteBytes': 0, 'logBytes': 0, 'effectCount': 0}
    require(type(limits) is dict and limits == expected and all(type(value) is int for value in limits.values()),
            'cjs-closed-probe-original-limits')


def project(directory):
    app = create(directory, 'greeting', 'my-greeting', runtime_profile=IMPORT_PROFILE)
    config = read_json(app/'capsule-project.json'); config['world'] = WORLD
    (app/'capsule-project.json').write_bytes((json.dumps(config, indent=2)+'\n').encode())
    for source, target in (('main.ts', 'src/main.ts'), ('world.wit', 'wit/world.wit')):
        (app/target).write_bytes(read_file(ROOT/FIXTURE/source))
    lock = read_json(app/'sdk-lock.json')
    lock['template'].update(sourceDigest=digest(read_file(app/'src/main.ts')), witDigest=digest(read_file(app/'wit/world.wit')))
    (app/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    validate(snapshot(app))
    for name, version in (('buffer-xor', '2.0.2'), ('safe-buffer', '5.2.1'), ('@types/buffer-xor', '2.0.2')):
        edit(app, 'add', identity=name, version=version,
             section='devDependencies' if name.startswith('@types/') else 'dependencies')
    # Original normal npm lock, including the exact ordinary declaration closure.
    # Never regenerate wildcard transitive versions during this programme.
    (app/'package-lock.json').write_bytes(read_file(ROOT/FIXTURE/'package-lock.json'))
    return app


def validate_graph(native, graph):
    locations = {'node_modules/'+name for name in PACKAGES}
    require(set(native['packages']) == {''} | locations, 'cjs-exact-native-package-closure')
    nodes = {row['location']: row for row in graph['nodes']}
    require(len(nodes) == len(graph['nodes']) and set(nodes) == {''} | locations,
            'cjs-exact-physical-package-closure')
    for name, expected in PACKAGES.items():
        location = 'node_modules/'+name
        for row in (native['packages'][location], nodes[location]):
            require(row['version'] == expected['version'] and row['integrity'] == expected['integrity'],
                    'cjs-original-native-version-and-integrity')
        require(nodes[location]['selected'] is True and nodes[location]['link'] is False,
                'cjs-real-installed-registry-package')
    expected_edges = {
        '': [('buffer-xor', '2.0.2', 'node_modules/buffer-xor'),
             ('safe-buffer', '5.2.1', 'node_modules/safe-buffer'),
             ('@types/buffer-xor', '2.0.2', 'node_modules/@types/buffer-xor')],
        'node_modules/buffer-xor': [('safe-buffer', '^5.1.1', 'node_modules/safe-buffer')],
        'node_modules/@types/buffer-xor': [('@types/node', '*', 'node_modules/@types/node')],
        'node_modules/@types/node': [('undici-types', '~8.9.0', 'node_modules/undici-types')],
    }
    for location, node in nodes.items():
        edges = [(row['name'], row['specification'], row['selected']) for row in node['dependencies']]
        require(sorted(edges) == sorted(expected_edges.get(location, [])), 'cjs-actual-transitive-edges')
    require(graph['selection'] == {'runtimeProfile': IMPORT_PROFILE, 'conditions': [], 'target': 'wasm32-component'}
        and graph['installScripts'] == 'never-executed' and graph['binLinks'] is False,
        'cjs-original-profile-no-conditions-or-lifecycle')


def provenance(app):
    require(read_file(app/'package-lock.json') == read_file(ROOT/FIXTURE/'package-lock.json'),
            'cjs-frozen-original-native-lock')
    accepted = verify_inputs(app, 'typescript')
    require(accepted is not None and not accepted.lock['transformations'], 'cjs-reviewed-unmodified-closure')
    native, graph = read_json(app/'package-lock.json'), read_json(app/'npm-resolved.lock.json')
    validate_graph(native, graph)
    archives = [row for row in accepted.lock['artifacts'] if row['metadata'].get('assetType') == 'original-package-archive']
    require(len(archives) == len(PACKAGES), 'cjs-original-five-archives')
    for name, expected in PACKAGES.items():
        rows = [row for row in archives if row['metadata'].get('nativeLocation') == 'node_modules/'+name]
        require(len(rows) == 1 and rows[0]['metadata']['integrity'] == expected['integrity'], 'cjs-original-archive-association')
    trees = [row for row in accepted.lock['artifacts'] if row['metadata'].get('assetType') == 'selected-node-modules']
    require(len(trees) == 1, 'cjs-one-normal-module-tree')
    files = {row['path']: row['digest'] for row in trees[0]['files']}
    require(all(files.get(name) == identity for name, identity in SOURCE_FILES.items()), 'cjs-published-source-bytes')
    return {'packages': PACKAGES, 'inputIdentity': accepted.identity,
        'manifestDigest': digest(accepted.manifest_bytes),
        'nativeLock': digest(read_file(app/'package-lock.json')),
        'resolvedGraph': digest(read_file(app/'npm-resolved.lock.json')),
        'acceptedLock': digest(read_file(app/'latent.dependencies.lock.json')),
        'moduleTree': {'mount': trees[0]['mount'], 'digest': trees[0]['treeDigest'],
            'files': len(trees[0]['files']), 'bytes': sum(row['size'] for row in trees[0]['files'])},
        'originalSources': SOURCE_FILES, 'transformations': [], 'conditions': [],
        'publishedInplace': 'source-observed-only; no ordinary published subpath declaration',
        'runtimeGlobalBuffer': 'not-installed', 'runtimeQualification': 'pending'}


def capture(app):
    original = read_file(app/'package-lock.json')
    node = Path(shutil.which('node') or 'missing-node').resolve(strict=True)
    npm = node.parent/'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve(strict=True)
    candidate = app/'target/commonjs-buffer.candidate.json'; candidate.parent.mkdir(exist_ok=True)
    resolve(app, candidate, node=node, npm=npm)
    review(app, candidate, digest(read_file(candidate)))
    require(status(app)['status'] == 'verified' and read_file(app/'package-lock.json') == original,
            'cjs-normal-review-with-original-native-lock')
    return provenance(app)


if __name__ == '__main__':
    import argparse
    from tools.rust_capsule_project import fresh, write_json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.resolve()
    require(directory != ROOT and ROOT not in directory.parents, 'cjs-capture-outside-checkout')
    directory = fresh(directory)
    app = project(directory/'application')
    try:
        captured = capture(app)
        write_json(directory/'capture.json', captured)
    except BaseException:
        write_json(directory/'FAILED.json', {'status': 'failed', 'stage': 'normal-npm-capture',
            'compilerExecuted': False, 'runtimeQualification': 'not-run'})
        raise
