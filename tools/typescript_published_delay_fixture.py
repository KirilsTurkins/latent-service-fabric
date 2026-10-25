"""Normal unchanged published delay capture; fixed evidence inputs, never policy."""
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

FIXTURE = 'sdk/typescript-guest/probes/published-delay'
WORLD = 'examples:typescript-published-delay/service@1.0.0'
SOURCES = ('main.ts',)
CASES = ('ordinary', 'nested', 'clear', 'pre-aborted', 'pending-abort', 'fresh-after-abort')
PACKAGES = {'delay': {'version': '7.0.0',
           'integrity': 'sha512-C3vaGs818qzZjCvVJ98GQUMVyWeg7dr5w2Nwwb2t5K8G98jOyyVO2ti2bKYk5yoYElqH3F2yA53ykuEnwD6MCg=='},
 'unlimited-timeout': {'version': '0.1.0',
                       'integrity': 'sha512-D4g+mxFeQGQHzCfnvij+R35ukJ0658Zzudw7j16p4tBBbNasKkKM4SocYxqhwT5xA7a9JYWDzKkEFyMlRi5sng=='},
 'random-int': {'version': '3.1.0',
                'integrity': 'sha512-h8CRz8cpvzj0hC/iH/1Gapgcl2TQ6xtnCpyOI5WvWfXf/yrDx2DOU+tD9rX23j36IF11xg1KqB9W11Z18JPMdw=='}}
SOURCE_FILES = {'delay/index.js': 'sha256:af014a1d46b17f50558c1b63b0d1ee21f6434d69528792c01bd17dfadd8de3d2',
 'delay/index.d.ts': 'sha256:dbd9097eda5396820e411dd5981ca8ab55003cc0128741e0153615a7b46db7f2',
 'unlimited-timeout/index.js': 'sha256:a3cedb7518e113e8556ab81b049235287ddf6860e9ed4af48b02f13b53806591',
 'unlimited-timeout/index.d.ts': 'sha256:99d27684faad2572fad334603aa2c5ddccfef3e599457d3cec49670b16b8c872',
 'random-int/index.js': 'sha256:b3b2ee6cb5523456ac942a4ea06e8bdcfdb34060c68d3860c5c7cab614e4d8b8',
 'random-int/index.d.ts': 'sha256:ad33272d8e2ba8f0e900c5bceb6ef8e742996e064e0c92bb878f6e4ded6ff4c4'}


def verify_probe(files):
    validate_sdk_inputs(files)
    config = json.loads(files['capsule-project.json'])
    require(config['world'] == WORLD and config['runtimeProfile'] == IMPORT_PROFILE
        and config['tenant'] == 'examples' and config['service'] == 'examples/my-greeting'
        and config['name'] == 'my-greeting' and config['limits'] == LIMITS
        and all(type(value) is int for value in config['limits'].values()), 'published-delay-closed-project')
    require({n for n in files if n.startswith('src/')} == {'src/'+n for n in SOURCES}
        and {n for n in files if n.startswith('wit/')} == {'wit/world.wit'},
        'published-delay-closed-source-graph')
    for name in SOURCES:
        require(files['src/'+name] == read_file(ROOT/FIXTURE/name), 'published-delay-probe-drift')
    require(files['wit/world.wit'] == read_file(ROOT/FIXTURE/'world.wit'), 'published-delay-world-drift')


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
    edit(app,'add',identity='delay',version=PACKAGES['delay']['version'])
    (app/'package-lock.json').write_bytes(read_file(ROOT/FIXTURE/'application-native-lock.json'))
    verify_probe(snapshot(app))
    return app


def validate_graph(native, graph):
    locations = {'node_modules/'+name for name in PACKAGES}
    require(set(native['packages']) == {''}|locations, 'published-delay-native-closure')
    nodes = {row['location']:row for row in graph['nodes']}
    require(len(nodes) == len(graph['nodes']) and set(nodes) == {''}|locations,
        'published-delay-physical-closure')
    for name, expected in PACKAGES.items():
        location = 'node_modules/'+name
        for row in (native['packages'][location],nodes[location]):
            require(row['version'] == expected['version'] and row['integrity'] == expected['integrity'],
                'published-delay-version-integrity')
        require(nodes[location]['selected'] is True and nodes[location]['link'] is False,
            'published-delay-original-installed-package')
    expected = {
        '':[('delay','7.0.0','node_modules/delay','dependencies')],
        'node_modules/delay':[('random-int','^3.1.0','node_modules/random-int','dependencies'),
            ('unlimited-timeout','^0.1.0','node_modules/unlimited-timeout','dependencies')],
    }
    for location,row in nodes.items():
        edges = row['dependencies']
        require(all(edge['optional'] is False for edge in edges)
            and sorted((edge['name'],edge['specification'],edge['selected'],edge['kind']) for edge in edges)
                == sorted(expected.get(location,[])), 'published-delay-original-edges')
    require(graph['selection'] == {'runtimeProfile':IMPORT_PROFILE,'conditions':[],'target':'wasm32-component'}
        and graph['installScripts'] == 'never-executed' and graph['binLinks'] is False,
        'published-delay-normal-selection')


def provenance(app):
    files = snapshot(app);verify_probe(files);validate(files)
    require(read_file(app/'package-lock.json') == read_file(ROOT/FIXTURE/'application-native-lock.json'),
        'published-delay-frozen-native-lock')
    accepted = verify_inputs(app,'typescript')
    require(accepted is not None and accepted.lock['transformations'] == [], 'published-delay-unmodified-inputs')
    native, graph = read_json(app/'package-lock.json'), read_json(app/'npm-resolved.lock.json')
    validate_graph(native,graph)
    archives = [row for row in accepted.lock['artifacts']
        if row['metadata'].get('assetType') == 'original-package-archive']
    require(len(archives) == 3, 'published-delay-original-three-archives')
    originals = {}
    for name, expected in PACKAGES.items():
        matches = [row for row in archives if row['metadata'].get('nativeLocation') == 'node_modules/'+name]
        require(len(matches) == 1 and matches[0]['metadata']['integrity'] == expected['integrity'],
            'published-delay-original-archive-association')
        row = matches[0]['original'];raw = accepted.store.get(row['digest'],row['size'])
        require('sha512-'+base64.b64encode(hashlib.sha512(raw).digest()).decode() == expected['integrity'],
            'published-delay-original-archive-SRI')
        originals[name] = row
    trees = [row for row in accepted.lock['artifacts']
        if row['metadata'].get('assetType') == 'selected-node-modules']
    require(len(trees) == 1, 'published-delay-one-normal-tree')
    tree = trees[0];identities = {row['path']:row['digest'] for row in tree['files']}
    require(all(identities.get(name) == identity for name,identity in SOURCE_FILES.items()),
        'published-delay-original-published-source')
    return {'packages':PACKAGES,'inputIdentity':accepted.identity,
        'manifestDigest':digest(accepted.manifest_bytes),'acceptedLock':digest(accepted.lock_bytes),
        'nativeLock':digest(read_file(app/'package-lock.json')),
        'resolvedGraph':digest(read_file(app/'npm-resolved.lock.json')),
        'moduleTree':{'mount':tree['mount'],'digest':tree['treeDigest'],'files':len(tree['files']),
            'bytes':sum(row['size'] for row in tree['files'])},
        'originalArchives':originals,'originalSources':SOURCE_FILES,'transformations':[],
        'conditions':[],'runtimeQualification':'pending-selected-paths',
        'scope':'finite-default-delay-selected-paths; not rangeDelay/random/long-delay/ref/unref/HTTP qualification'}


def verify(app):
    files = snapshot(app);verify_probe(files);validate(files)
    return files


def capture(app):
    original = read_file(app/'package-lock.json')
    node = Path(shutil.which('node') or 'missing-node').resolve(strict=True)
    npm = node.parent/'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve(strict=True)
    candidate = app/'target/published-delay.candidate.json';candidate.parent.mkdir(exist_ok=True)
    resolve(app,candidate,node=node,npm=npm)
    review(app,candidate,digest(read_file(candidate)))
    require(status(app)['status'] == 'verified' and read_file(app/'package-lock.json') == original,
        'published-delay-normal-exact-review')
    return provenance(app)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args = parser.parse_args()
    write_json(args.receipt,capture(args.project))
