"""Unmodified published connectivity client through the normal npm capture path."""
from __future__ import annotations
import json
from tools.application_dependencies import verify_inputs
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file
from tools.typescript_application_dependencies import resolve
from tools.typescript_dependency_authoring import edit, review, status
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

LOCK = 'sdk/typescript-guest/probes/node-net/application-native-lock.json'
PACKAGE = 'is-port-reachable'
VERSION = '4.0.0'
INTEGRITY = 'sha512-9UoipoxYmSk6Xy7QFgRv2HDyaysmgSG75TFQs6S+3pDM7ZhKTF/bskZV+0UlABHzKjNVhPjYCLfeZUEg1wXxig=='
ARCHIVE = {'digest': 'sha256:3459a0a985749ad7a8c61876704285c4364cacc8f6909062a3b79a2739513d14', 'size': 2025}
SOURCE_FILES = {
    'is-port-reachable/index.js': 'sha256:f1fa49fa502c39c23001e3bfe0dcc3341e0a3e437fd11b8401a7070da6933854',
    'is-port-reachable/index.d.ts': 'sha256:685cfa0bb3e44b39040dc05913af6868b8e917947fbea5692d721ab961743d30',
    'is-port-reachable/package.json': 'sha256:9498f436472333ca29fc7611df5596aec4b18b08896e6ccf121054486c7d7268',
    'is-port-reachable/license': 'sha256:5c932d88256b4ab958f64a856fa48e8bd1f55bc1d96b8149c65689e0c61789d3',
    'is-port-reachable/readme.md': 'sha256:860a45ce33c0ea37001f17ade76f52758608f6314831a83efbb581ee61d70963',
}


def validate_graph(native, graph):
    location = 'node_modules/' + PACKAGE
    require(set(native['packages']) == {'', location}, 'net-client-exact-native-closure')
    nodes = {row['location']: row for row in graph['nodes']}
    require(len(nodes) == len(graph['nodes']) == 2 and set(nodes) == {'', location},
            'net-client-exact-installed-closure')
    for row in (native['packages'][location], nodes[location]):
        require(row['version'] == VERSION and row['integrity'] == INTEGRITY,
                'net-client-original-version-and-integrity')
    package = nodes[location]
    require(package['selected'] is True and package['link'] is False
            and package['dependencies'] == [] and package['exports'] == './index.js'
            and package['type'] == 'module' and package['imports'] is None,
            'net-client-original-published-entrypoint')
    require(nodes['']['dependencies'] == [{'name': PACKAGE, 'kind': 'dependencies',
            'specification': VERSION, 'selected': location, 'optional': False}],
            'net-client-original-application-edge')
    require(graph['selection'] == {'runtimeProfile': IMPORT_PROFILE, 'conditions': [], 'target': 'wasm32-component'}
            and graph['installScripts'] == 'never-executed' and graph['binLinks'] is False,
            'net-client-normal-profile-without-hooks')


def provenance(app):
    require(read_file(app/'package-lock.json') == read_file(ROOT/LOCK), 'net-client-frozen-native-lock')
    accepted = verify_inputs(app, 'typescript')
    require(accepted is not None and accepted.lock['transformations'] == [], 'net-client-unchanged-reviewed-closure')
    validate_graph(json.loads(read_file(app/'package-lock.json')), json.loads(read_file(app/'npm-resolved.lock.json')))
    archives = [row for row in accepted.lock['artifacts'] if row['metadata'].get('assetType') == 'original-package-archive']
    require(len(archives) == 1 and archives[0]['original'] == ARCHIVE
            and archives[0]['metadata']['nativeLocation'] == 'node_modules/' + PACKAGE
            and archives[0]['metadata']['integrity'] == INTEGRITY, 'net-client-original-archive')
    trees = [row for row in accepted.lock['artifacts'] if row['metadata'].get('assetType') == 'selected-node-modules']
    require(len(trees) == 1, 'net-client-one-normal-module-tree')
    tree = trees[0]
    files = {row['path']: row['digest'] for row in tree['files']}
    require(len(files) == len(tree['files']) == 6 and set(files) == {'.package-lock.json', *SOURCE_FILES}
            and all(files.get(name) == identity for name, identity in SOURCE_FILES.items()),
            'net-client-all-unchanged-published-file-bytes')
    return {'package': PACKAGE, 'version': VERSION, 'integrity': INTEGRITY, 'archive': ARCHIVE,
            'inputIdentity': accepted.identity, 'manifestDigest': digest(accepted.manifest_bytes),
            'nativeLock': digest(read_file(app/'package-lock.json')),
            'resolvedGraph': digest(read_file(app/'npm-resolved.lock.json')),
            'acceptedLock': digest(read_file(app/'latent.dependencies.lock.json')),
            'moduleTree': {'mount': tree['mount'], 'digest': tree['treeDigest'],
                           'files': len(tree['files']), 'bytes': sum(row['size'] for row in tree['files'])},
            'originalSources': SOURCE_FILES, 'transformations': [], 'conditions': [],
            'runtimeQualification': 'pending'}


def capture(app):
    edit(app, 'add', identity=PACKAGE, version=VERSION)
    (app/'package-lock.json').write_bytes(read_file(ROOT/LOCK))
    candidate = app/'target/node-net-client.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    resolve(app, candidate)
    review(app, candidate, digest(read_file(candidate)))
    require(status(app)['status'] == 'verified', 'net-client-normal-reviewed-inputs')
    return provenance(app)


def build_evidence(artifact, expected):
    dependencies = json.loads(read_file(artifact/'application-dependencies.json'))
    require(dependencies['inputIdentity'] == expected['inputIdentity']
            and dependencies['manifestDigest'] == expected['manifestDigest']
            and dependencies['lockDigest'] == expected['acceptedLock']
            and dependencies['transformations'] == [] and dependencies['networkResolution'] is False,
            'net-client-normal-offline-build-closure')
    selected = json.loads(read_file(artifact/'bundle-selected-inputs.json'))
    linked = [row for row in selected['capturedInputs'] if row['path'] ==
              'dependencies/npm/node_modules/is-port-reachable/index.js']
    require(len(linked) == 1 and linked[0]['digest'] == SOURCE_FILES['is-port-reachable/index.js']
            and 'lsf-owned-node-net:node:net' in selected['inputs']
            and selected['selection']['inputIdentity'] == expected['inputIdentity']
            and selected['selection']['conditions'] == [], 'net-client-real-published-entrypoint-linked')
    tree = expected['moduleTree']
    layout = json.loads(read_file(artifact/'compiler-containment.json'))['typeScriptNodeModulesAlias']
    require(layout == {'phase': 'typecheck', 'access': 'read-only', 'source': 'project/' + tree['mount'],
            'destination': 'project/node_modules', 'inputIdentity': expected['inputIdentity'],
            'treeDigest': tree['digest'], 'files': tree['files'], 'bytes': tree['bytes']},
            'net-client-original-readonly-declaration-closure')
    return {'selectedEntrypoint': linked[0], 'sourceClosure': expected,
            'typecheckLayout': layout,
            'runtimeQualification': 'pending'}
