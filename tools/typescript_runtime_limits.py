"""Fixed ordinary-JavaScript resource boundaries; no application broker calls."""
import json
import re
from tools import qualify_typescript_fetch_runtime as base
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file

SOURCE='sdk/typescript-guest/probes/runtime-limits/main.ts'
MEMORY=67108864
PROFILES=(
    ('task',1,{'tasks':16,'queuedWork':64,'nativeOwners':256},'activation-runtime-task-register-denied:2'),
    ('queue',2,{'tasks':64,'queuedWork':16,'nativeOwners':256},'activation-runtime-queue-register-denied:2'),
    ('native',3,{'tasks':64,'queuedWork':64,'nativeOwners':64},'activation-runtime-promise-native-register-denied:2'),
    ('timer',4,{'tasks':64,'queuedWork':64,'nativeOwners':256},'activation-runtime-timer-start-denied:2'),
    ('memory',5,{'tasks':64,'queuedWork':64,'nativeOwners':256},None))


def project(directory):
    app=base.project(directory)
    source=read_file(ROOT/SOURCE);(app/'src/main.ts').write_bytes(source)
    lock=json.loads(read_file(app/'sdk-lock.json'));lock['template']['sourceDigest']=digest(source)
    (app/'sdk-lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
    return app


def limits(profile):
    require(profile in PROFILES,'typescript-limit-closed-profile')
    return {**base.OWNER_LIMITS,**profile[2]}


def require_refusal(row, profile, bootstrap):
    name,_mode,_limits,label=profile
    if label is not None:
        decoded=row.get('decoded')
        require(isinstance(decoded,list) and len(decoded)==1 and isinstance(decoded[0],str),
            'typescript-limit-typed-refusal')
        match=re.fullmatch(re.escape(label)+r'\|count=([1-9][0-9]*)\|fresh=1',decoded[0])
        require(match is not None and 0<int(match[1])<128,'typescript-limit-exact-refusal')
        if name=='timer':require(int(match[1])==8,'typescript-limit-eight-timers')
        base.require_result(row,decoded[0],0)
        return {'kind':name,'label':label,'admitted':int(match[1])}
    require(row['exitCode']==4 and row['decoded'] is None and row['processReaped']
        and row['response']['outcomeKnown'] is True
        and row['response']['error']['code'] in ('resource-exhausted','guest-trap'),
        'typescript-limit-memory-terminal')
    consumption=row['response']['data']['consumption']
    require(all(type(consumption[k]) is int and consumption[k]==0
        for k in ('outboundRequests','childCalls','effectCount')),'typescript-limit-memory-effects')
    peak=int(consumption['peakMemoryBytes'])
    positive=int(bootstrap['response']['data']['consumption']['peakMemoryBytes'])
    require(0<positive and positive+33554432<=peak<=MEMORY,'typescript-limit-memory-growth')
    return {'kind':name,'terminal':row['response']['error']['code'],'memoryBudget':MEMORY,
        'bootstrapPeak':positive,'negativePeak':peak}
