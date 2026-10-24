"""Strict finite reader of the actual seven-attempt native signed programme."""
import json
import re

from tools.go_stack_ceiling_fixture import LIMITS

CASE = 'signed_go_v7_stack_cap_gc_initializer_and_fresh_state_keep_original_budgets'
EXPECTED = (
    ('below-cap-GC','go-stack-ordinary',0,False),
    ('growth-cap','go-stack-ordinary',1,True),
    ('fresh-after-growth','go-stack-ordinary',0,False),
    ('raised-limit-cap','go-stack-ordinary',2,True),
    ('fresh-after-raised-limit','go-stack-ordinary',0,False),
    ('initializer-cap','go-stack-initializer-cap',0,True),
    ('fresh-after-initializer','go-stack-ordinary',0,False),
)
RUNTIME = {'tasks':16,'executors':2,'queuedWork':16,'waits':4,'timers':2,'results':2,'native':2}
FUNCTIONS = ('runtime.lsfStackLimitExceeded','runtime.stackalloc','runtime.copystack',
    'runtime.newstack','wit_component/export_tests_caller_api.stackFrame')


def require(condition, reason):
    if not condition: raise ValueError('Go-stack-'+reason)


def exact(actual, expected):
    return json.dumps(actual,sort_keys=True,separators=(',',':'),allow_nan=False) == json.dumps(expected,sort_keys=True,separators=(',',':'),allow_nan=False)


def integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def sha(value):
    return type(value) is str and re.fullmatch(r'sha256:[0-9a-f]{64}',value) is not None


def read(raw):
    require(type(raw) is bytes and len(raw) <= 1024*1024,'output-bound')
    def pairs(rows):
        result = {}
        for key,value in rows:
            require(key not in result,'duplicate-JSON-key');result[key] = value
        return result
    def constant(_): raise ValueError('Go-stack-nonfinite-JSON')
    rows = []
    for line in raw.splitlines():
        if line.startswith(b'GO_STACK_'):
            match = re.fullmatch(rb'GO_STACK_([A-Z]+) (.+)',line)
            require(match is not None and len(match[2]) <= 64*1024,'marker-shape')
            rows.append((match[1].decode(),json.loads(match[2],object_pairs_hook=pairs,parse_constant=constant)))
    expected = ['VARIANT','VARIANT','FACTORY','POLICIES'] + ['CASE','OWNER']*3 + ['FACTORY','POLICIES'] + ['CASE','OWNER']*2 + ['FACTORY','POLICIES','CASE','OWNER','REPOINT','CASE','OWNER','COMPLETE']
    require([kind for kind,_ in rows] == expected,'ordered-complete-protocol')
    require(raw.count(('test '+CASE+' ... ok').encode()) == 1,'actual-case-required')
    require(len(re.findall(rb'^test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;',raw,re.M)) == 1,'exact-libtest-totals')
    variants = [value for kind,value in rows if kind == 'VARIANT']
    mappings = {}
    for value,name,initial in zip(variants,('go-stack-ordinary','go-stack-initializer-cap'),(False,True)):
        require(set(value) == {'name','initializerCap','sourceDigest','componentDigest','sourceInputsDigest','budget','mapping'},'variant-shape')
        require(exact({k:value[k] for k in ('name','initializerCap','budget')}, {'name':name,'initializerCap':initial,'budget':LIMITS}),'variant-selection')
        require(all(sha(value[k]) for k in ('sourceDigest','componentDigest','sourceInputsDigest')),'variant-digests')
        m = value['mapping']; mappings[name] = m
        require(set(m) == {'componentDigest','coreModuleDigest','coreModuleBytes','staticModuleIndex','functions','numericCapIdentityUnambiguous'},'mapping-shape')
        require(m['componentDigest'] == value['componentDigest'] and sha(m['coreModuleDigest']) and
            integer(m['coreModuleBytes'],8,16*1024*1024) and integer(m['staticModuleIndex'],0,15)
            and m['numericCapIdentityUnambiguous'] is True,'actual-mapping-binding')
        require(type(m['functions']) is list and len(m['functions']) == 5,'mapping-function-count')
        for f,name in zip(m['functions'],FUNCTIONS):
            require(set(f) == {'name','index','start','end','bodyDigest','callsCapLeaf','selfCalls','memoryFills','memoryCopies','checksumCopyAfterRecursiveCall'},'function-shape')
            require(f['name'] == name and integer(f['index'],0,16383) and integer(f['start'],8,m['coreModuleBytes'])
                and integer(f['end'],f['start']+1,m['coreModuleBytes']) and sha(f['bodyDigest']),'function-identity')
            for k in ('callsCapLeaf','selfCalls','memoryFills','memoryCopies'): require(integer(f[k],0,1_000_000),'operator-count')
            require(type(f['checksumCopyAfterRecursiveCall']) is bool,'operator-boolean')
            if name == FUNCTIONS[4]:
                require(f['selfCalls'] > 0 and f['memoryFills'] > 0 and f['memoryCopies'] > 0
                    and f['checksumCopyAfterRecursiveCall'],'actual-live-nontail-array')
            elif name != FUNCTIONS[0]: require(f['callsCapLeaf'] == 1,'all-three-guard-calls')
    require(variants[0]['componentDigest'] != variants[1]['componentDigest'],'two-components-required')
    policies = [v for k,v in rows if k == 'POLICIES']
    for i,p in enumerate(policies):
        require(set(p) == {'callerPublication','ordinaryPublication','callerRelease','ordinaryRelease','scopes','grants','effectivePackageBudget','factoryFuelUpperCeiling','factoryMemoryUpperCeiling','runtimeLimits'},'policy-shape')
        require(exact(p['effectivePackageBudget'],LIMITS) and exact(p['runtimeLimits'],RUNTIME)
            and integer(p['factoryFuelUpperCeiling'],10_000_000_000,10_000_000_000)
            and integer(p['factoryMemoryUpperCeiling'],64*1024*1024,64*1024*1024),'effective-versus-upper-limits')
        for key in ('callerPublication','ordinaryPublication'):
            require(type(p[key]) is str and 1 <= len(p[key]) <= 256,'publication-identity')
        require(p['ordinaryRelease'] == variants[0]['componentDigest']
            and p['callerRelease'] == variants[1 if i == 2 else 0]['componentDigest'],'actual-admitted-releases')
        expected_scopes = [{'services':['caller'],'publications':[p['callerPublication']],'principalKind':'user','principal':'alice'},
            {'services':['callee'],'publications':[p['ordinaryPublication']],'principalKind':'service','principal':'service:5:tests:6:caller'},
            {'services':['caller'],'publications':[p['ordinaryPublication']],'principalKind':'user','principal':'alice'}]
        require(exact(p['scopes'],expected_scopes),'closed-preauthorized-scopes')
        capabilities = ['latent:runtime/activation@0.1.0','latent:clock/monotonic@0.1.0','latent:clock/wall@0.1.0','latent:random/random@0.1.0']
        require(exact(p['grants'],[{'capability':cap,'policy':'sdk-runtime-policy-'+str(j),'operations':[],'constraints':{}} for j,cap in enumerate(capabilities)]),'original-grants-only')
    factories = [v for k,v in rows if k == 'FACTORY']
    require(exact(factories,[{'scenario':name,'observerReset':False} for name in ('growth','raised-limit','initializer')]),'fresh-one-arm-factories')
    cases = [v for k,v in rows if k == 'CASE']; owners = [v for k,v in rows if k == 'OWNER']
    for index,(actual,owner,(label,variant,mode,cap)) in enumerate(zip(cases,owners,EXPECTED)):
        require(set(actual) == {'case','variant','mode','cap','resolvedRelease','resolvedPublication','result','numericObservation','cpuFuel','peakMemoryBytes','outboundRequests','reportedEffectCount','effectiveRequestBudget'},'case-shape')
        require(exact({k:actual[k] for k in ('case','variant','mode','cap')},{'case':label,'variant':variant,'mode':mode,'cap':cap})
            and exact(actual['effectiveRequestBudget'],LIMITS),'case-selection-and-request-budget')
        p = policies[0 if index < 3 else 1 if index < 5 else 2]
        require(actual['resolvedRelease'] == mappings[variant]['componentDigest']
            and actual['resolvedPublication'] == p['callerPublication' if index == 5 else 'ordinaryPublication'],'actual-resolved-publication')
        require(integer(actual['cpuFuel'],1,LIMITS['cpuFuel']) and integer(actual['peakMemoryBytes'],1,LIMITS['memoryBytes'])
            and exact([actual['outboundRequests'],actual['reportedEffectCount']],[0,0]),'actual-consumption')
        if cap:
            require(exact(actual['result'],{'code':'GuestTrap','attribution':'actual-private-v7-cap-frame'}),'negative-classification')
            n = actual['numericObservation']
            require(type(n) is dict and set(n) == {'observedErrors','ambiguous','trapKind','missingBacktrace','mayBeTruncated','observedFrames','engineFrameCap','frames'},'numeric-shape')
            require(exact({k:n[k] for k in ('observedErrors','ambiguous','trapKind','missingBacktrace','engineFrameCap')},
                {'observedErrors':1,'ambiguous':False,'trapKind':'unreachable-code','missingBacktrace':False,'engineFrameCap':16})
                and integer(n['observedFrames'],1,16) and type(n['mayBeTruncated']) is bool,'original-single-error')
            require(type(n['frames']) is list and len(n['frames']) == 16 and len([f for f in n['frames'] if f is not None]) == n['observedFrames'],'numeric-bounds')
            leaf = mappings[variant]['functions'][0]; matched = 0
            for f in n['frames']:
                if f is None: continue
                require(set(f) == {'module','function','moduleOffset','functionOffset'} and integer(f['module'],0,15)
                    and integer(f['function'],0,16383),'numeric-frame-fields')
                for key in ('moduleOffset','functionOffset'):
                    require(f[key] is None or integer(f[key],0,16*1024*1024),'numeric-offset')
                if f['function'] == leaf['index'] and type(f['moduleOffset']) is int and leaf['start'] <= f['moduleOffset'] < leaf['end']: matched += 1
            require(matched == 1,'dedicated-cap-frame-required')
        else:
            require(actual['numericObservation'] is None,'success-is-not-a-trap')
            result = actual['result']; require(set(result) == {'typedResult','fresh','beforeStack','liveStack','beforeGC','GC','checksum'},'positive-shape')
            for key in ('beforeStack','liveStack','beforeGC','GC'): require(integer(result[key],0,64*1024*1024),'guest-memory-observation')
            require(integer(result['fresh'],1,1) and integer(result['checksum'],17756160,17756160)
                and result['liveStack'] >= result['beforeStack']+17*8192 and result['GC'] > result['beforeGC'],'actual-stack-GC-checksum')
            require(result['typedResult'] == 'stack|fresh=1|init=3133440|checksum=17756160|before='+str(result['beforeStack'])+'|live='+str(result['liveStack'])+'|beforeGC='+str(result['beforeGC'])+'|gc='+str(result['GC']),'actual-typed-output')
        require(exact(owner,{'case':label,'stores':0,'instances':0,'reservations':0,'reservedFuel':0,'reservedMemory':0,'newStores':1,'kernelRetirementQualified':False}),'original-owner-retirement')
    repoint = [v for k,v in rows if k == 'REPOINT'][0]; p = policies[2]
    require(exact(repoint,{'oldRelease':p['callerRelease'],'oldPublication':p['callerPublication'],
        'newRelease':p['ordinaryRelease'],'newPublication':p['ordinaryPublication'],'sameBackend':True,
        'originalOwnersZeroBeforeChange':True,'retryFailedInitializer':False}),'normal-fresh-repoint')
    complete = rows[-1][1]
    require(exact(complete,{'attempts':7,'components':2,'factories':3,'capFrames':3,'freshAfterFailures':3,
        'observerReset':False,'effectiveFuel':LIMITS['cpuFuel'],'effectiveMemory':LIMITS['memoryBytes'],
        'queuedWork':16,'wholeGoCostQualification':False,'kernelRetirementQualified':False}),'completion-scope')
    return {'variants':variants,'policies':policies,'factories':factories,'cases':cases,'owners':owners,'repoint':repoint,'completion':complete}
