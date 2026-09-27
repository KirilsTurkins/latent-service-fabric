"""Actual one-site update, retained receipt recovery and eligible publication rollback."""
import hashlib
import json
from pathlib import Path
import sys

import qualification_inside as q


def run(mode):
    state = q.document(q.files.read(q.STATE, 8192))
    records = state['records']
    q.inventory()
    documentation = records['documentation']
    q.require(q.served(documentation['path'], documentation['sha256']) == documentation['etag'], 'unrelated-site-changed')
    if mode == 'update':
        work = Path(q.document(q.files.read(Path('/work/current.json'), 4096))['work'])
        result = q.call('web', 'publish', work / 'site-v2/package', '--evidence', work / 'site-v2-evidence/index.json',
                        '--operation-id', 'storage-update-site', '--expected-generation', '0')
        operation = result['data']['operation']
        q.require(result['data']['auditAck'] is not None, 'storage-update-audit')
        q.require(q.call('web', 'operation', 'storage-update-site')['data']['operation'] == dict(operation, replayed=True),
                  'storage-update-receipt')
        state['previousSite'] = records['site']
        publication = operation['publication']['id']
        for method in ('GET', 'HEAD'):
            q.route('site-' + method.lower(), publication, '/', method, prefix='update')
        expected = hashlib.sha256(q.files.read(work / 'site-v2-build/index.html', 65536)).hexdigest()
        records['site'] = {'publication': publication, 'path': '/', 'sha256': expected, 'etag': q.served('/', expected)}
        state['updateOperation'] = operation
        q.files.replace(q.STATE, q.encode(state))
    elif mode == 'rollback':
        previous = state['previousSite']
        # Trigger admission checks CURRENT eligibility. Historical receipts alone do not authorize reuse.
        for method in ('GET', 'HEAD'):
            q.route('site-' + method.lower(), previous['publication'], '/', method, prefix='rollback')
        q.require(q.served('/', previous['sha256']) == previous['etag'], 'restored-rollback-content')
        records['site'] = previous
        q.files.replace(q.STATE, q.encode(state))
    elif mode == 'recovered':
        q.require(q.call('web', 'operation', 'storage-update-site')['data']['operation'] == dict(state['updateOperation'], replayed=True),
                  'restored-operation-receipt')
        q.require(q.served('/', records['site']['sha256']) == records['site']['etag'], 'restored-current-site')
    else:
        raise ValueError('mode')
    q.inventory()
    return {'schemaVersion': 'latent.container-storage-operation.v1', 'passed': True, 'mode': mode,
            'unrelatedPublicationUnchanged': True, 'actualNativeOperations': q.CALLS, 'cloudQualified': False}


if __name__ == '__main__':
    print(json.dumps(run(sys.argv[1])))
