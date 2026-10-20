"""Ordinary JavaScript scheduling outcomes, with no application task pumping."""
import json
from tools import qualify_typescript_fetch_runtime as base
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file

SOURCE='sdk/typescript-guest/probes/runtime-semantics/main.ts'
VECTORS=(('thenable',1,'thenable:pending:once|fresh=1'),
 ('microtasks',2,'microtasks:nested:run-to-completion|fresh=1'),
 ('rejection',3,'rejection:pending:exact-object|fresh=1'),
 ('finally',4,'finally:values:reason:order|fresh=1'),
 ('interval',5,'interval:three:clear:no-overlap|fresh=1'),
 ('timer-nesting',6,'timer:arguments:nesting:microtask|fresh=1'),
 ('timer-clear',7,'timer:clear-before-fire:idempotent|fresh=1'))
NEGATIVE=(('callback-exception',8,'guest-trap'),('unhandled-rejection',9,'guest-trap'),
 ('synchronous-fuel',10,'resource-exhausted'))
FUEL=50000000


def project(directory):
    app=base.project(directory)
    source=read_file(ROOT/SOURCE);(app/'src/main.ts').write_bytes(source)
    lock=json.loads(read_file(app/'sdk-lock.json'));lock['template']['sourceDigest']=digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
    return app


def require_negative(row, code):
    require(code in ('guest-trap','resource-exhausted') and row['exitCode']==4
        and row['decoded'] is None and row['processReaped'] and row['response']['outcomeKnown'] is True
        and row['response']['error']['code']==code,'typescript-semantics-negative-terminal')
    usage=row['response']['data']['consumption']
    require(int(usage['cpuFuel'])>0 and int(usage['peakMemoryBytes'])>0
        and all(type(usage[k]) is int and usage[k]==0 for k in ('outboundRequests','childCalls','effectCount')),
        'typescript-semantics-negative-execution-effects')
    if code=='resource-exhausted':
        require(int(usage['cpuFuel'])==FUEL,'typescript-semantics-exact-fuel-containment')
    return {'terminal':code,'callbackOriginProven':False}
