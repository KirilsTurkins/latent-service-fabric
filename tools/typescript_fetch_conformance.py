"""Ordinary Fetch vectors and owned real-peer supervision, never a mock transport."""
from __future__ import annotations
import base64
import json
from pathlib import Path
import time

from tools import qualify_typescript_fetch_runtime as base
from tools.phase2_operator_process import require
from tools.rust_capsule_node import finish_call, start_call
from tools.rust_capsule_project import ROOT, digest, read_file
from tools.standard_http.vectors import DOMAIN, json_bytes
from tools.standard_http.observations import validate as validate_peer
from tools.static_api.node import policy

SOURCE = 'sdk/typescript-guest/probes/fetch-conformance/main.ts'
PATHS = ['/conformance/json', '/conformance/status/404', '/conformance/status/500',
    '/conformance/echo', '/conformance/hold/headers', '/conformance/body/partial',
    '/conformance/body/truncated', '/conformance/body/malformed', '/conformance/body/malformed-json',
    '/conformance/body/oversized', '/conformance/body/gzip', '/conformance/redirect',
    '/conformance/redirect-target', '/conformance/redirect-denied',
    '/conformance/mutation/close']


def project(directory: Path) -> Path:
    app = base.project(directory)
    source = read_file(ROOT/SOURCE)
    (app/'src/main.ts').write_bytes(source)
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf-8')
    manifest = json.loads(read_file(app/'capsule-project.json'))
    # This separate fixture permits the two independently authorized redirect
    # requests. The original one-request fixture/profile is untouched.
    manifest['limits']['outboundRequests'] = 2
    (app/'capsule-project.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return app


def configuration(directory, releases, startup, credential):
    path = base.configuration(directory, releases, startup, credential)
    value = json.loads(read_file(path))
    value['budgetProfile']['maximumOutboundRequests'] = 2
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    return path


def grants(client, node, publication, origins):
    runtime, authorized = base.grants(client, node, publication, origins['primary'])
    policy(client, 'policy', 'http-allow', {'formatVersion':1, 'tenant':'examples', 'rules':[{
        'id':'fetch-conformance', 'effect':'allow',
        'principals':[{'kind':'administrator','subject':'workflow-operator'}],
        'services':[base.SERVICE], 'publications':[publication], 'capability':base.HTTP,
        'operations':['open','write','finish','read','chunk-bytes','trailers','abort-upload','abort-body'],
        'resources':{'kind':'http', 'origins':[origins['primary'],origins['secondary']],
            'methods':['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'],
            'paths':PATHS, 'pathPrefixes':[]},
        'ceiling':{'operations':64,'inputBytes':65536,'outputBytes':262144,'wallTimeMillis':5000}}]},generation=1)
    return runtime, authorized


def vectors():
    domain = json_bytes(DOMAIN).decode()
    values = [
        ('json-clone',0,'domain-json','200:'+domain+':used:clone',1),
        ('http404-response',0,'http-404','404:'+json_bytes({'status':404,'message':'domain-error'}).decode()+':used:clone',1),
        ('http500-response',0,'http-500','500:'+json_bytes({'status':500,'message':'domain-error'}).decode()+':used:clone',1),
    ]
    for index, method in enumerate(('GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS')):
        body = b'' if method in {'GET','HEAD'} else 'caf\u00e9\u03bb'.encode()
        echoed = '' if method=='HEAD' else json_bytes({'method':method,
            'bodyBase64':base64.b64encode(body).decode(),
            'contentLengthPresent':True,
            'contentTypePresent':method not in {'GET','HEAD'},
            'customHeaderBase64':base64.b64encode(b'ordinary-global').decode()}).decode()
        values.append(('method-'+method.lower(),10+index,'method-bytes','200:'+echoed,1))
    values.extend([
        ('already-aborted',20,'domain-json','already-aborted',0),
        ('reserved-header',21,'domain-json','lsf-fetch-buffered-v1:unsupported:reserved-header:authorization',0),
        ('used-request',22,'method-bytes','body-already-used',1),
        ('buffered-reader',23,'domain-json',domain,1),
        ('buffered-reader-cancel',24,'domain-json','body-already-used',1),
        ('get-body',25,'domain-json','get-body-refused',0),
        ('malformed-json',26,'malformed-json','malformed-json',1),
        ('truncated-body',27,'truncated-body','fetch-transport-failure:unexpected-eof',1),
        ('malformed-framing',27,'malformed-framing','fetch-transport-failure:connection-failed',1),
        ('oversized-body',27,'oversized-body','fetch-transport-failure:response-too-large',1),
        ('encoding-unsupported',27,'gzip-json','fetch-transport-failure:unsupported-encoding',1),
        ('redirect',28,'redirect','200:true:'+json_bytes({'redirected':True}).decode(),2),
        ('redirect-denied',27,'redirect-denied','fetch-transport-failure:permission-denied',1),
        ('denied-target-no-contact',27,'denied-target','fetch-transport-failure:permission-denied',0),
        ('uncertain-post-no-replay',33,'commit-close','uncertain:true',1),
    ])
    return values


def drive(client, process, peer, *, deadline=None, release_after=None):
    """Keep one selector and one real CLI owner live until actual termination."""
    expires = min(client.deadline, deadline or time.monotonic()+client.invocation_timeout_millis/1000+3)
    first_gate = None
    released = False
    while not process.owner.exited():
        require(time.monotonic()<expires, 'fetch-conformance-invocation-deadline')
        peer.poll(.005)
        process.drain()
        gates = peer.gates()
        if gates and first_gate is None: first_gate = time.monotonic()
        if release_after is not None and gates and time.monotonic()-first_gate >= release_after:
            require(len(gates)==1 and not released, 'fetch-conformance-single-gate')
            peer.release(gates[0]);released=True
    row = finish_call(client, process)
    if release_after is not None:
        require(first_gate is not None and released, 'fetch-conformance-pending-gate-required')
    return row


def invoke(client, target, peer, mode, vector, name, *, wall=None, release_after=None):
    process = start_call(client,target,'typescript-fetch','run',[mode,peer.url(vector)],name,wall=wall)
    try:
        return drive(client,process,peer,release_after=release_after)
    finally:
        process.close()


def wait_gate(client, process, peer):
    expires = min(client.deadline,time.monotonic()+5)
    while not peer.gates():
        require(time.monotonic()<expires and not process.owner.exited(),'fetch-conformance-real-pending-required')
        peer.poll(.005);process.drain()
    require(len(peer.gates())==1,'fetch-conformance-one-gate')
    return peer.gates()[0]


def peer_evidence(value):
    validate_peer(value)
    expected=[]
    for _name,_mode,vector,_result,outbound in vectors():
        if outbound:
            expected.append(vector)
            if vector=='redirect': expected.append('redirect-target')
    expected.extend(['pending-headers','partial-body','pending-headers',
        'pending-headers','partial-body','domain-json'])
    require(value['state']=='stopped' and len(expected)==28
        and value['startedRequests']==value['acceptedConnections']==len(expected)
        and value['committedMutations']==1 and value['rejectedRequests']==0
        and [row.get('vector') for row in value['requests']]==expected,
        'fetch-conformance-exact-total-contacts')
    secondary=[row for row in value['requests'] if row['role']=='secondary']
    require(len(secondary)==1 and secondary[0]['vector']=='redirect-target'
        and all(secondary[0][key] is False for key in
            ('authorizationPresent','cookiePresent','proxyAuthorizationPresent'))
        and all(row['authorizationPresent'] is True for row in value['requests'] if row['role']=='primary'),
        'fetch-conformance-redirect-credential-scope')
    return value
