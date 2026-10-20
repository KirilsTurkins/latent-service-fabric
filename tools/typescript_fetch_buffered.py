"""Zero-contact emitted tests of the advertised already-buffered body profile."""
import json
from tools import qualify_typescript_fetch_runtime as base
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file
from tools.standard_http.observations import validate

SOURCE='sdk/typescript-guest/probes/fetch-buffered-limits/main.ts'


def project(directory):
    app=base.project(directory)
    source=read_file(ROOT/SOURCE)
    (app/'src/main.ts').write_bytes(source)
    lock=json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest']=digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
    return app


def vectors():
    return [('buffered-three-windows',0,'domain-json','windows:65536,65536,1:copied:no-prefetch',0),
        ('buffered-cancel-remainder',1,'domain-json','cancelled:one-window:remainder-unread',0),
        ('buffered-unsupported-stream-members',2,'domain-json','tee:pipeTo:pipeThrough:values:unsupported',0),
        ('buffered-body-api-limit',3,'domain-json','body-limit:1048576',0),
        ('buffered-null-versus-empty',4,'domain-json','null:absent:empty:disturbed',0)]


def peer_evidence(value):
    validate(value)
    require(value['state']=='stopped' and all(value[name]==0 for name in
        ('startedRequests','acceptedConnections','committedMutations','rejectedRequests'))
        and value['requests']==[], 'fetch-buffered-no-network-effects')
    return value
