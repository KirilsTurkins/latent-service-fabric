"""Actual signed publications, independent HEAD routes and controlled source damage."""
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, '/source/tools/container_runtime')
import qualification_inside as native

state = Path('/var/cache/lsf/compression-qualification.json')
work = Path(native.document(native.files.read(Path('/work/current.json'), 4096))['work'])
mode = sys.argv[1]
if mode == 'publish':
    records = {}
    for name in ['alpha', 'beta']:
        value = native.call('web', 'publish', work / name / 'package', '--evidence', work / (name + '-evidence/index.json'),
                            '--operation-id', 'compression-' + name, '--expected-generation', '0')
        publication = value['data']['operation']['publication']['id']
        for method in ['GET', 'HEAD']:
            native.route('compress-' + name + '-' + method.lower(), publication, '/' + name, method,
                         scheme='https', authority='frontend.example.test:18443')
        records[name] = publication
    native.files.create(state, native.encode(records))
    print(json.dumps({'passed': True, 'actualPublications': records}))
elif mode in ('split-head', 'restore-head'):
    records = native.document(native.files.read(state, 4096))
    native.route('compress-alpha-head', records['beta' if mode == 'split-head' else 'alpha'], '/alpha', 'HEAD',
                 prefix=mode, scheme='https', authority='frontend.example.test:18443')
    print(json.dumps({'passed': True, 'mode': mode}))
elif mode == 'revoke-and-corrupt':
    records = native.document(native.files.read(state, 4096))
    native.call('web', 'revoke', '--publication', records['alpha'], '--operation-id', 'compression-revoke',
                '--expected-generation', '1')
    original = native.files.read(work / 'beta-build/unread.js', 4096)
    digest = hashlib.sha256(original).hexdigest()
    matches, count = [], 0
    for parent, directories, files in os.walk('/var/lib/lsf'):
        count += len(directories) + len(files)
        assert count <= 8192, 'compression-damage-inventory-bound'
        if Path(parent).name == 'blobs' and digest in files:
            path = Path(parent) / digest
            assert not path.is_symlink() and path.read_bytes() == original
            matches.append(path)
    assert 1 <= len(matches) <= 8, 'compression-source-blob-required'
    for path in matches:
        os.chmod(path, 0o600)
        with path.open('r+b') as stream:
            stream.write(b'!' + original[1:]); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({'passed': True, 'revokedPublication': True, 'actualUncachedSourceDamage': True}))
else:
    raise AssertionError('unknown compression mode')
