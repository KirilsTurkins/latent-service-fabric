"""Finite ordinary timer/AbortSignal races, keeping original owner limits."""
import json
from tools import qualify_typescript_fetch_runtime as base
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT,digest,read_file

SOURCE='sdk/typescript-guest/probes/timer-races/main.ts'
VECTORS=(('abort-timeout',1,'timeout:once:exact-reason|fresh=1'),
 ('manual-before-timeout',2,'any:manual-first:late-timeout-fenced|fresh=1'),
 ('already-aborted',3,'any:already-aborted:no-replay|fresh=1'),
 ('shared-clear',4,'clear:shared-ids:idempotent|fresh=1'),
 ('ready-clear',5,'clear:ready-sibling:microtask-fence|fresh=1'),
 ('checked-conversion',6,'timeout:checked-conversion:valid-after-refusal|fresh=1'),
 ('coalescing',7,'interval:blocked-turn:bounded-coalescing|fresh=1'))
WALL_MILLIS=1000

def project(directory):
    app=base.project(directory)
    source=read_file(ROOT/SOURCE);(app/'src/main.ts').write_bytes(source)
    lock=json.loads(read_file(app/'sdk-lock.json'));lock['template']['sourceDigest']=digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf8',newline='\n')
    return app

def require_deadline(row):
    response=row['response'];usage=response['data']['consumption']
    require(row['exitCode']==4 and row['decoded'] is None and row['processReaped'] is True
        and response['outcomeKnown'] is True and response['error']['code']=='deadline-exceeded'
        and response['data']['terminalState']=='deadline_exceeded'
        and int(usage['cpuFuel'])>0 and int(usage['peakMemoryBytes'])>0
        and all(type(usage[key]) is int and usage[key]==0 for key in ('outboundRequests','childCalls','effectCount')),
        'typescript-timer-root-deadline-is-not-elapsed-timer')
