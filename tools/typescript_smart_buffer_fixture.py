"""Normal unchanged SmartBuffer capture; fixed evidence inputs, never policy."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.application_dependencies import verify_inputs
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file, read_json, snapshot, write_json
from tools.typescript_application_dependencies import resolve
from tools.typescript_dependency_authoring import edit, review, status
from tools.typescript_guest.project import create, validate, validate_sdk_inputs
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE
from tools.typescript_buffer_globals_fixture import LIMITS, REFERENCE

FIXTURE = 'sdk/typescript-guest/probes/smart-buffer'
WORLD = 'examples:typescript-smart-buffer/service@1.0.0'
SOURCES = ('main.ts', 'dependency.ts')
CASES = ('initialization', 'growth-insert-view', 'string-timer', 'managed-read-refusal',
         'buffer-ceiling', 'fresh-after-refusal')
PACKAGES = {
    'smart-buffer': {'version':'4.2.0',
        'integrity':'sha512-94hK0Hh8rPqQl2xXc3HsaBoOXKV20MToPkcXvwbISWLEs+64sBq5kFgn2kJDHb1Pry9yrP0dxrCI9RRci7RXKg=='},
    '@types/node': {'version':'24.19.2',
        'integrity':'sha512-93d49wCWJkCyN87MxLpNN6KXPCwFw7bVUg79mGUV1OS40JGWwVCr8n61DXCSqz7CV6/VfPkb7xec7uP2M+QHWQ=='},
    'undici-types': {'version':'7.24.6',
        'integrity':'sha512-WRNW+sJgj5OBN4/0JpHFqtqzhpbnV0GuB+OozA9gCL7a993SmU+1JBZCzLNxYsbMfIeDL+lTsphD5jN5N+n0zg=='},
}
SOURCE_FILES = {
    'smart-buffer/build/smartbuffer.js':'sha256:6a73858a0aa6f7ac078d8156187ef97a713e44d52afccf6679a0a032539be0cc',
    'smart-buffer/build/utils.js':'sha256:451b2e82d359f3d8782be4830bd5d9df895434adbbbd911fbeb27e64fc59167d',
    'smart-buffer/typings/smartbuffer.d.ts':'sha256:8e30a475b47adfbe1a79ad3f72d48f38d1df3d4be0808176fccb4dd2c02dac18',
}


def verify_probe(files):
    validate_sdk_inputs(files)
    config = json.loads(files['capsule-project.json'])
    require(config['world'] == WORLD and config['runtimeProfile'] == IMPORT_PROFILE
        and config['tenant'] == 'examples' and config['service'] == 'examples/my-greeting'
        and config['name'] == 'my-greeting' and config['limits'] == LIMITS
        and all(type(value) is int for value in config['limits'].values()), 'smart-buffer-closed-project')
    require({n for n in files if n.startswith('src/')} == {'src/'+n for n in SOURCES}
        and {n for n in files if n.startswith('wit/')} == {'wit/world.wit'},
        'smart-buffer-closed-source-graph')
    for name in SOURCES:
        require(files['src/'+name] == read_file(ROOT/FIXTURE/name), 'smart-buffer-probe-drift')
    require(files['wit/world.wit'] == read_file(ROOT/FIXTURE/'world.wit'), 'smart-buffer-world-drift')


def project(directory):
    app = create(directory, 'greeting', 'my-greeting', runtime_profile=IMPORT_PROFILE)
    config = read_json(app/'capsule-project.json');config.update(world=WORLD,limits=dict(LIMITS))
    (app/'capsule-project.json').write_bytes((json.dumps(config,indent=2)+'\n').encode())
    for name in SOURCES:(app/'src'/name).write_bytes(read_file(ROOT/FIXTURE/name))
    world = read_file(ROOT/FIXTURE/'world.wit');(app/'wit/world.wit').write_bytes(world)
    lock = read_json(app/'sdk-lock.json')
    lock['template'].update(sourceDigest=digest(read_file(app/'src/main.ts')),witDigest=digest(world))
    (app/'sdk-lock.json').write_bytes((json.dumps(lock,indent=2)+'\n').encode())
    validate(snapshot(app))
    edit(app,'add',identity='smart-buffer',version=PACKAGES['smart-buffer']['version'])
    edit(app,'add',identity='@types/node',version=PACKAGES['@types/node']['version'],section='devDependencies')
    (app/'package-lock.json').write_bytes(read_file(ROOT/FIXTURE/'application-native-lock.json'))
    verify_probe(snapshot(app))
    return app


def validate_graph(native, graph):
    locations = {'node_modules/'+name for name in PACKAGES}
    require(set(native['packages']) == {''}|locations, 'smart-buffer-native-closure')
    nodes = {row['location']:row for row in graph['nodes']}
    require(len(nodes) == len(graph['nodes']) and set(nodes) == {''}|locations,
        'smart-buffer-physical-closure')
    for name, expected in PACKAGES.items():
        location = 'node_modules/'+name
        for row in (native['packages'][location],nodes[location]):
            require(row['version'] == expected['version'] and row['integrity'] == expected['integrity'],
                'smart-buffer-version-integrity')
        require(nodes[location]['selected'] is True and nodes[location]['link'] is False,
            'smart-buffer-original-installed-package')
    expected = {
        '':[('smart-buffer','4.2.0','node_modules/smart-buffer','dependencies'),
            ('@types/node','24.19.2','node_modules/@types/node','devDependencies')],
        'node_modules/@types/node':[('undici-types','>=7.24.0 <7.24.7','node_modules/undici-types','dependencies')],
    }
    for location,row in nodes.items():
        edges = row['dependencies']
        require(all(edge['optional'] is False for edge in edges)
            and sorted((edge['name'],edge['specification'],edge['selected'],edge['kind']) for edge in edges)
                == sorted(expected.get(location,[])), 'smart-buffer-original-edges')
    require(graph['selection'] == {'runtimeProfile':IMPORT_PROFILE,'conditions':[],'target':'wasm32-component'}
        and graph['installScripts'] == 'never-executed' and graph['binLinks'] is False,
        'smart-buffer-normal-selection')


def provenance(app):
    files = snapshot(app);verify_probe(files);validate(files)
    require(read_file(app/'package-lock.json') == read_file(ROOT/FIXTURE/'application-native-lock.json'),
        'smart-buffer-frozen-native-lock')
    accepted = verify_inputs(app,'typescript')
    require(accepted is not None and accepted.lock['transformations'] == [], 'smart-buffer-unmodified-inputs')
    native, graph = read_json(app/'package-lock.json'), read_json(app/'npm-resolved.lock.json')
    validate_graph(native,graph)
    archives = [row for row in accepted.lock['artifacts']
        if row['metadata'].get('assetType') == 'original-package-archive']
    require(len(archives) == 3, 'smart-buffer-original-three-archives')
    originals = {}
    for name, expected in PACKAGES.items():
        matches = [row for row in archives if row['metadata'].get('nativeLocation') == 'node_modules/'+name]
        require(len(matches) == 1 and matches[0]['metadata']['integrity'] == expected['integrity'],
            'smart-buffer-original-archive-association')
        row = matches[0]['original'];raw = accepted.store.get(row['digest'],row['size'])
        require('sha512-'+base64.b64encode(hashlib.sha512(raw).digest()).decode() == expected['integrity'],
            'smart-buffer-original-archive-SRI')
        originals[name] = row
    trees = [row for row in accepted.lock['artifacts']
        if row['metadata'].get('assetType') == 'selected-node-modules']
    require(len(trees) == 1, 'smart-buffer-one-normal-tree')
    tree = trees[0];identities = {row['path']:row['digest'] for row in tree['files']}
    require(all(identities.get(name) == identity for name,identity in SOURCE_FILES.items()),
        'smart-buffer-original-published-source')
    return {'packages':PACKAGES,'inputIdentity':accepted.identity,
        'manifestDigest':digest(accepted.manifest_bytes),'acceptedLock':digest(accepted.lock_bytes),
        'nativeLock':digest(read_file(app/'package-lock.json')),
        'resolvedGraph':digest(read_file(app/'npm-resolved.lock.json')),
        'moduleTree':{'mount':tree['mount'],'digest':tree['treeDigest'],'files':len(tree['files']),
            'bytes':sum(row['size'] for row in tree['files'])},
        'originalArchives':originals,'originalSources':SOURCE_FILES,'transformations':[],
        'conditions':[],'runtimeQualification':'pending-selected-paths',
        'scope':'integer-string-growth-selected-paths; not complete package/HTTP/network qualification'}


def verify(app):
    files = snapshot(app);verify_probe(files);validate(files)
    return files


def capture(app):
    original = read_file(app/'package-lock.json')
    node = Path(shutil.which('node') or 'missing-node').resolve(strict=True)
    npm = node.parent/'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve(strict=True)
    candidate = app/'target/smart-buffer.candidate.json';candidate.parent.mkdir(exist_ok=True)
    resolve(app,candidate,node=node,npm=npm)
    review(app,candidate,digest(read_file(candidate)))
    require(status(app)['status'] == 'verified' and read_file(app/'package-lock.json') == original,
        'smart-buffer-normal-exact-review')
    return provenance(app)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args = parser.parse_args()
    write_json(args.receipt,capture(args.project))
