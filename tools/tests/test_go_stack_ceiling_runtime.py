"""Controlled protocol/source inputs; these are NOT actual Go stack outcomes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import go_stack_ceiling_fixture as fixture, go_stack_ceiling_outcomes as oracle
from tools.qualify_go_stack_ceiling_runtime import compile_variant


def controlled_rows():
    budget = {'cpuFuel':1000000000,'memoryBytes':67108864,'wallTimeLimitMillis':120000,
        'childCalls':0,'outboundRequests':0,'stateReadBytes':0,'stateWriteBytes':0,
        'blobReadBytes':0,'blobWriteBytes':0,'logBytes':0,'effectCount':0}
    rows = []
    for variant,initial,d in [('go-stack-ordinary',False,'a'),('go-stack-initializer-cap',True,'b')]:
        names = ['runtime.lsfStackLimitExceeded','runtime.stackalloc','runtime.copystack',
            'runtime.newstack','wit_component_export_tests_caller_api.stackFrame']
        functions = [dict(name=name,index=100+i,start=1000+100*i,end=1100+100*i,
            bodyDigest='sha256:'+'c'*64,callsCapLeaf=int(0<i<4),selfCalls=int(i==4),
            memoryFills=int(i==4),memoryCopies=int(i==4),checksumCopyAfterRecursiveCall=i==4)
            for i,name in enumerate(names)]
        rows.append(('VARIANT',dict(name=variant,initializerCap=initial,sourceDigest='sha256:'+'d'*64,
            sourceInputsDigest='sha256:'+'e'*64,componentDigest='sha256:'+d*64,budget=budget,
            mapping=dict(componentDigest='sha256:'+d*64,coreModuleDigest='sha256:'+'f'*64,
                coreModuleBytes=4096,staticModuleIndex=2,functions=functions,numericCapIdentityUnambiguous=True))))
    scenarios = [
        ('growth',[('below-cap-GC','go-stack-ordinary',0,False),('growth-cap','go-stack-ordinary',1,True),('fresh-after-growth','go-stack-ordinary',0,False)]),
        ('raised-limit',[('raised-limit-cap','go-stack-ordinary',2,True),('fresh-after-raised-limit','go-stack-ordinary',0,False)]),
        ('initializer',[('initializer-cap','go-stack-initializer-cap',0,True),('fresh-after-initializer','go-stack-ordinary',0,False)])]
    for scenario,cases in scenarios:
        init = scenario == 'initializer'
        rows.append(('FACTORY',dict(scenario=scenario,observerReset=False)))
        p = dict(callerPublication='init-pub' if init else 'ordinary-pub',ordinaryPublication='ordinary-pub',
            callerRelease='sha256:'+('b' if init else 'a')*64,ordinaryRelease='sha256:'+'a'*64,
            scopes=[{'services':['caller'],'publications':['init-pub' if init else 'ordinary-pub'],'principalKind':'user','principal':'alice'},
                {'services':['callee'],'publications':['ordinary-pub'],'principalKind':'service','principal':'service:5:tests:6:caller'},
                {'services':['caller'],'publications':['ordinary-pub'],'principalKind':'user','principal':'alice'}],
            grants=[{'capability':cap,'policy':'sdk-runtime-policy-'+str(i),'operations':[],'constraints':{}}
                for i,cap in enumerate(['latent:runtime/activation@0.1.0','latent:clock/monotonic@0.1.0','latent:clock/wall@0.1.0','latent:random/random@0.1.0'])],
            effectivePackageBudget=budget,factoryFuelUpperCeiling=10000000000,factoryMemoryUpperCeiling=67108864,
            runtimeLimits=dict(tasks=16,executors=2,queuedWork=16,waits=4,timers=2,results=2,native=2))
        rows.append(('POLICIES',p))
        for index,(label,variant,mode,cap) in enumerate(cases):
            if init and index == 1:
                rows.append(('REPOINT',dict(oldRelease='sha256:'+'b'*64,oldPublication='init-pub',
                    newRelease='sha256:'+'a'*64,newPublication='ordinary-pub',sameBackend=True,
                    originalOwnersZeroBeforeChange=True,retryFailedInitializer=False)))
            if cap:
                result = dict(code='GuestTrap',attribution='actual-private-v7-cap-frame')
                observation = dict(observedErrors=1,ambiguous=False,trapKind='unreachable-code',
                    missingBacktrace=False,mayBeTruncated=False,observedFrames=1,engineFrameCap=16,
                    frames=[dict(module=0,function=100,moduleOffset=1001,functionOffset=1)]+[None]*15)
            else:
                result = dict(typedResult='stack|fresh=1|init=3133440|checksum=17756160|before=131072|live=524288|beforeGC=0|gc=1',
                    fresh=1,beforeStack=131072,liveStack=524288,beforeGC=0,GC=1,checksum=17756160)
                observation = None
            rows.append(('CASE',dict(case=label,variant=variant,mode=mode,cap=cap,
                resolvedRelease='sha256:'+('b' if variant.endswith('initializer-cap') else 'a')*64,
                resolvedPublication='init-pub' if variant.endswith('initializer-cap') else 'ordinary-pub',
                result=result,numericObservation=observation,cpuFuel=1234,peakMemoryBytes=4000000,
                outboundRequests=0,reportedEffectCount=0,effectiveRequestBudget=budget)))
            rows.append(('OWNER',dict(case=label,stores=0,instances=0,reservations=0,reservedFuel=0,
                reservedMemory=0,newStores=1,kernelRetirementQualified=False)))
    rows.append(('COMPLETE',dict(attempts=7,components=2,factories=3,capFrames=3,freshAfterFailures=3,
        observerReset=False,effectiveFuel=1000000000,effectiveMemory=67108864,queuedWork=16,
        wholeGoCostQualification=False,kernelRetirementQualified=False)))
    return rows


def encoded(rows):
    return (f'test {oracle.CASE} ... ok\n'+'\n'.join('GO_STACK_'+kind+' '+json.dumps(value) for kind,value in rows)+
        '\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.1s\n').encode()


class StackProgramme(unittest.TestCase):
    def test_actual_reader_requires_seven_attempts_and_preserves_bounded_truncation(self):
        rows = controlled_rows();value = oracle.read(encoded(rows))
        self.assertEqual(len(value['cases']),7)
        wrong_tenant = copy.deepcopy(rows)
        [v for k,v in wrong_tenant if k == 'POLICIES'][0]['scopes'][1]['principal'] = 'service:8:tenant-a:6:caller'
        with self.assertRaises(ValueError):oracle.read(encoded(wrong_tenant))
        wrong_name = copy.deepcopy(rows)
        wrong_name[0][1]['mapping']['functions'][4]['name'] = 'wit_component/export_tests_caller_api.stackFrame'
        with self.assertRaises(ValueError):oracle.read(encoded(wrong_name))
        # Recursive callers may be cut after16 frames; a positively retained
        # private cap leaf still proves its own original frame, never the tail.
        for kind,item in rows:
            if kind == 'CASE' and item['cap']:
                observation = item['numericObservation']
                observation.update(mayBeTruncated=True,observedFrames=16)
                observation['frames'][1:] = [dict(module=0,function=104,moduleOffset=1401,functionOffset=1)]*15
        self.assertTrue(oracle.read(encoded(rows))['cases'][1]['numericObservation']['mayBeTruncated'])

    def test_generic_trap_wrong_leaf_grant_budget_and_retirement_are_refused(self):
        mutations = [
            ('CASE',1,lambda v:v.update(numericObservation=None)),
            ('CASE',1,lambda v:v['numericObservation']['frames'][0].update(function=999)),
            ('CASE',1,lambda v:v['numericObservation'].update(observedErrors=2)),
            ('CASE',6,lambda v:v.update(resolvedPublication='stale-init-pub')),
            ('POLICIES',2,lambda v:v['scopes'][2].update(publications=['*'])),
            ('POLICIES',0,lambda v:v['runtimeLimits'].update(queuedWork=2)),
            ('CASE',0,lambda v:v.update(effectiveRequestBudget={**v['effectiveRequestBudget'],'cpuFuel':10000000000})),
            ('OWNER',2,lambda v:v.update(stores=1)),
            ('OWNER',6,lambda v:v.update(newStores=0)),
            ('REPOINT',0,lambda v:v.update(retryFailedInitializer=True)),
        ]
        for kind,index,change in mutations:
            with self.subTest(kind=kind,index=index):
                rows = copy.deepcopy(controlled_rows());change([v for k,v in rows if k==kind][index])
                with self.assertRaises((ValueError,TypeError)):oracle.read(encoded(rows))

    def test_missing_duplicate_unknown_float_and_unexecuted_case_cannot_qualify(self):
        rows = controlled_rows()
        for changed in (rows[:-1],rows+[rows[-1]],rows[:3]+[('UNKNOWN',{})]+rows[3:],rows[:4]+rows[6:]):
            with self.assertRaises(ValueError):oracle.read(encoded(changed))
        for kind,key,value in [('COMPLETE','observerReset',0),('COMPLETE','attempts',7.0),
                ('FACTORY','observerReset',0),('OWNER','stores',False)]:
            changed = copy.deepcopy(rows);[v for k,v in changed if k==kind][0][key] = value
            with self.subTest(kind=kind,key=key),self.assertRaises(ValueError):oracle.read(encoded(changed))
        for raw in (encoded(rows).replace(b'0 ignored',b'1 ignored'),encoded(rows).replace(oracle.CASE.encode(),b'not-the-case'),b'x'*(1024*1024+1)):
            with self.assertRaises(ValueError):oracle.read(raw)

    def test_normal_capture_and_actual_compile_facade_reject_detached_inputs_first(self):
        for variant in ('ordinary','initializer-cap'):
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary);app = fixture.create(root/'app',variant)
                original = (app/'src/main.go').read_bytes()
                self.assertIn(b'initializerDepth uint32 = '+(b'2' if variant=='ordinary' else b'96'),original)
                with patch('tools.go_capsule_build.build') as build:
                    compile_variant(app,variant,root/'not-built',root/'not-a-tool',root/'not-a-packager');build.assert_called_once_with(app,root/'not-built',root/'not-a-tool',root/'not-a-packager',
                        'https://github.com/KirilsTurkins/latent-service-fabric')
                    for path,value in [('src/main.go',original+b'\n'),('src/cheat.go',b'package export_tests_caller_api\n')]:
                        selected=app/path;prior=selected.read_bytes() if selected.exists() else None
                        selected.write_bytes(value);build.reset_mock()
                        with self.assertRaises(ValueError):compile_variant(app,variant,root/'not-built',root/'not-a-tool',root/'not-a-packager')
                        build.assert_not_called()
                        if prior is None:selected.unlink()
                        else:selected.write_bytes(prior)
                    p=app/'capsule-project.json';document=json.loads(p.read_bytes())
                    for value in (10000000000,1000000000.0,True):
                        changed=copy.deepcopy(document);changed['limits']['cpuFuel']=value;p.write_text(json.dumps(changed))
                        build.reset_mock()
                        with self.assertRaises(ValueError):compile_variant(app,variant,root/'not-built',root/'not-a-tool',root/'not-a-packager')
                        build.assert_not_called()
                    changed=copy.deepcopy(document);changed['tenant']='tenant-a';p.write_text(json.dumps(changed))
                    build.reset_mock()
                    with self.assertRaises(ValueError):compile_variant(app,variant,root/'not-built',root/'not-a-tool',root/'not-a-packager')
                    build.assert_not_called()
                    p.write_text(json.dumps(document))
                self.assertEqual(fixture.verify(app,variant)['limits']['cpuFuel'],1000000000)


if __name__ == '__main__':unittest.main()
