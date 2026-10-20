"""Finite late accepted-provider completion after ordinary public Fetch rejection."""
import json
from tools import qualify_typescript_fetch_runtime as base
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file
from tools.standard_http.observations import validate

SOURCE='sdk/typescript-guest/probes/fetch-late-completion/main.ts'


def project(directory):
    app=base.project(directory)
    source=read_file(ROOT/SOURCE)
    (app/'src/main.ts').write_bytes(source)
    lock=json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest']=digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
    return app


EXPECTED='late:aborted:one-rejection:zero-resolution|fresh=1'
VECTORS=('pending-headers','partial-body')


def peer_evidence(value):
    validate(value)
    require(value['state']=='stopped' and value['startedRequests']==value['acceptedConnections']==2
        and value['completedResponseWrites']==2 and value['committedMutations']==value['rejectedRequests']==0
        and [row['vector'] for row in value['requests']]==list(VECTORS)
        and all(row['role']=='primary' and row['state']=='closed'
            and row['authorizationPresent'] is True and row['closeReason']=='response-write-complete'
            for row in value['requests']), 'fetch-late-exact-completed-provider-responses')
    released=[row for row in value['events'] if row['kind']=='gate-released']
    require(len(released)==2,'fetch-late-real-provider-gates')
    return value
