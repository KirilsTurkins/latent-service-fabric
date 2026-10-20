"""Ordinary accepted work and opaque-work outcomes after root settlement."""
import json
from tools import qualify_typescript_fetch_runtime as base
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file

SOURCE='sdk/typescript-guest/probes/root-lifecycle/main.ts'
LOG='latent:log/log@0.1.0'
# name, mode, final value or error, whether accepted structured logging is required, wall limit.
CASES=(('accepted-timer',1,'accepted-timer|fresh=1',len('accepted-after-root'),None),
 ('accepted-microtask',2,'accepted-microtask|fresh=1',len('microtask-after-root'),None),
 ('accepted-chain',3,'accepted-chain|fresh=1',len('accepted-parentaccepted-child'),None),
 ('unreachable-promise',4,'unreachable-promise|fresh=1',0,None),
 ('opaque-promise',5,'guest-trap',0,None),
 ('callback-control',10,'callback-control|fresh=1',len('callback-throw-reached'),None),
 ('callback-throw',6,'guest-trap',len('callback-throw-reached'),None),
 ('rejection-control',11,'rejection-control|fresh=1',len('rejection-reached'),None),
 ('unhandled-rejection',7,'guest-trap',len('rejection-reached'),None),
 ('live-interval',8,'deadline-exceeded',0,1000),
 ('root-rejection',9,'guest-trap',len('root-rejection-reached'),None))

def project(directory):
    app=base.project(directory)
    source=read_file(ROOT/SOURCE);(app/'src/main.ts').write_bytes(source)
    world=app/'wit/world.wit';wit=read_file(world).decode()
    require(wit.count('world service {')==1 and LOG not in wit,'root-lifecycle-original-world')
    wit=wit.replace('world service {','world service {\n    import '+LOG+';')
    world.write_text(wit,encoding='utf-8',newline='\n')
    dependency=app/'wit/deps/log';dependency.mkdir(parents=True)
    (dependency/'package.wit').write_bytes(read_file(ROOT/'wit/platform/log/package.wit'))
    configuration=json.loads(read_file(app/'capsule-project.json'))
    configuration['limits']['logBytes']=1024
    (app/'capsule-project.json').write_text(json.dumps(configuration,indent=2)+'\n',encoding='utf-8',newline='\n')
    lock=json.loads(read_file(app/'sdk-lock.json'))
    lock['template'].update(sourceDigest=digest(source),witDigest=digest(wit.encode()))
    (app/'sdk-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8',newline='\n')
    return app

def require_outcome(row,expected,log_bytes):
    require(type(log_bytes) is int and 0<=log_bytes<=1024,'root-lifecycle-log-bound')
    response=row['response'];usage=response['data']['consumption']
    require(response['outcomeKnown'] is True and row['processReaped'] is True
        and int(usage['cpuFuel'])>0 and int(usage['peakMemoryBytes'])>0
        and ((log_bytes==0 and int(usage['logBytes'])==0)
             or (log_bytes>0 and log_bytes<=int(usage['logBytes'])<=1024))
        and all(type(usage[k]) is int and usage[k]==0 for k in ('outboundRequests','childCalls','effectCount')),
        'root-lifecycle-real-execution-and-accepted-log-charge')
    if expected in ('guest-trap','deadline-exceeded'):
        require(row['exitCode']==4 and row['decoded'] is None
            and response['error']['code']==expected,'root-lifecycle-required-terminal')
    else:
        base.require_result(row,expected,0)
    return {'terminal':(response.get('error') or {}).get('code'),'logBytes':usage['logBytes'],
            'callbackReached':log_bytes>0,'preciseExceptionMessageExposed':False}
