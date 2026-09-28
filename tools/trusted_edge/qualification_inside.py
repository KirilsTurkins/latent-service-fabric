"""Publish actual signed content and inspect private native owners for the TLS edge."""
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, '/source/tools/container_runtime')
import qualification_inside as native

AUTHORITY = 'frontend.example.test:18443'
mode = sys.argv[1]
if mode == 'publish':
    root = Path(native.document(native.files.read(Path('/work/current.json'), 4096))['work'])
    result = {}
    for name, mount, relative in [('site', '/', 'index.html'), ('documentation', '/docs', 'guide/index.html')]:
        value = native.call('web', 'publish', root / name / 'package', '--evidence', root / (name + '-evidence/index.json'),
                            '--operation-id', 'edge-' + name, '--expected-generation', '0')
        publication = value['data']['operation']['publication']['id']
        for method in ('GET', 'HEAD'):
            native.route('edge-' + name + '-' + method.lower(), publication, mount, method,
                         scheme='https', authority=AUTHORITY)
        result[name] = {'publication': publication, 'path': '/' if name == 'site' else '/docs/guide/',
                        'sha256': hashlib.sha256(native.files.read(root / (name + '-build') / relative, 65536)).hexdigest()}
    native.files.create(Path('/var/cache/lsf/edge-qualification.json'), native.encode(result))
    print(json.dumps(result))
elif mode == 'idle':
    until = time.monotonic() + 8
    while True:
        value = native.inventory()
        rows = {row['name']: row for row in value['topology']['entries']}
        if all(rows[name]['activeCount'] == '0' for name in ['http-connections', 'http-exchanges', 'http-buffer-reservations']):
            break
        assert time.monotonic() < until, 'edge-native-owner-not-reclaimed'
        time.sleep(0.05)
    assert value['quotas']['usage']['activeActivations'] == 0
    print(json.dumps({'passed': True, 'actualNativeOwnersIdle': True, 'zeroPreparedCapsules': True}))
else:
    raise AssertionError('unknown edge native qualification mode')
