"""Inspect real serving and create finite competing operations for CI recovery tests."""
import hashlib
import json
from pathlib import Path
import sys

import qualification_inside as q

mode = sys.argv[1]
work = Path(q.document(q.files.read(Path('/work/current.json'), 4096))['work'])
if mode == 'inputs':
    print(json.dumps({'work': str(work)}))
elif mode == 'record':
    records = {}
    for name, path, file in [('site', '/', 'index.html'), ('documentation', '/docs/guide/', 'guide/index.html')]:
        operation = q.call('web', 'operation', 'container-' + name)['data']['operation']
        expected = hashlib.sha256(q.files.read(work / (name + '-build') / file, 65536)).hexdigest()
        records[name] = {'publication': operation['publication']['id'], 'path': path,
                         'sha256': expected, 'etag': q.served(path, expected)}
    q.files.create(q.STATE, q.encode({'records': records}))
    print(json.dumps({'passed': True, 'actualGetHeadAndSignedBytes': True}))
elif mode == 'evict':
    # Competing operators exercise the actual native 64-entry receipt window;
    # this is not a mocked UNKNOWN response.
    q.DEADLINE = q.time.monotonic() + 90
    q.MAXIMUM_CALLS = 196
    publication = q.call('web', 'operation', 'container-site')['data']['operation']['publication']['id']
    for index in range(65):
        q.route('ci-churn', publication, '/ci-churn', 'GET', prefix='churn-' + str(index))
    assert q.CALLS == 196
    print(json.dumps({'passed': True, 'actualCompetingCommits': 65, 'actualNativeCalls': q.CALLS}))
elif mode == 'remove-cut-marker':
    marker = Path('/var/cache/lsf/ci-cut-complete.json')
    value = q.document(q.files.read(marker, 4096))
    assert value == {'actualNativeCommit': True}
    marker.unlink()
    print(json.dumps(value))
elif mode == 'cancel-marker':
    marker = Path('/var/cache/lsf/ci-cancel-complete.json')
    print(json.dumps(q.document(q.files.read(marker, 4096)) if marker.exists() else {}))
elif mode == 'permission-marker':
    print(json.dumps(q.document(q.files.read(Path('/var/cache/lsf/ci-permission-denied.json'), 4096))))
else:
    raise AssertionError('unknown private operator test')
