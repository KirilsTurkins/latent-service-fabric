"""Strict observation readers; never manufacture allocator or VM observations."""
import json
import re
from tools.typescript_guest.owned_result_controls import BACKING_CORE_CASES

EXPECTED_FREES=(0,0,5,1,0,3,1,None)


def require(value,reason):
    if not value:raise ValueError(reason)


def channel(raw:bytes,schema:str,compile_row:bool)->list[dict]:
    prefix=[];rows=[]
    for line in raw.decode().splitlines():
        if line.startswith('{'):
            row=json.loads(line)
            require(type(row) is dict and row.get('schemaVersion')==schema,'backing-raw-schema')
            rows.append(row)
        elif line:prefix.append(line)
    require(prefix[:1]==['diagnostic compiler optimization: none'],'backing-original-optimization')
    require((len(prefix)==2 and re.fullmatch(r'diagnostic compile millis: [0-9]{1,9}',prefix[1]) is not None)
            if compile_row else len(prefix)==1,'backing-original-prefix')
    require(len(rows)==8,'backing-all-eight-actual-cases-required')
    return rows


def core_rows(raw:bytes,emitted:dict)->list[dict]:
    rows=channel(raw,'latent.typescript.backing-core-case.v1',False)
    require(emitted.get('executed') is False and emitted.get('allocatorEvidence') is False,
            'backing-original-emitted-input')
    for which,(name,row,material) in enumerate(zip(BACKING_CORE_CASES,rows,emitted['modules'],strict=True)):
        require(row.get('case')==material['case']==name and type(row.get('index')) is int
                and row['index']==which and row.get('status')=='passed','backing-core-actual-case-order')
        module_hash=row.get('moduleSha256');manifest_hash=row.get('manifestSha256')
        require(row.get('moduleBytes')==material['bytes']
                and type(module_hash) is str and re.fullmatch(r'[0-9a-f]{64}',module_hash) is not None
                and type(manifest_hash) is str and re.fullmatch(r'[0-9a-f]{64}',manifest_hash) is not None
                and 'sha256:'+module_hash==material['sha256']
                and 'sha256:'+manifest_hash==emitted['manifest']['sha256'],'backing-core-loaded-original-bytes')
        require((row.get('returned') is None if which==7 else
                 type(row.get('returned')) is int and row['returned']==int(which in (4,5)))
                and row.get('trapped') is (which==7)
                and type(row.get('doubleFreeReturns')) is int and row['doubleFreeReturns']==0
                and type(row.get('originalDropCalls')) is int and row['originalDropCalls']==int(which==7),
                'backing-core-actual-control-flow')
        require(type(row.get('fuel')) is int and 0<=row['fuel']<=1_000_000_000
                and row.get('allocatorEvidence') is False and row.get('guestRootReopened') is False,
                'backing-core-counter-double-scope')
    return rows


def backing_rows(raw:bytes)->list[dict]:
    rows=channel(raw,'latent.typescript.late-backing-case.v1',True)
    for which,(row,count) in enumerate(zip(rows,EXPECTED_FREES,strict=True)):
        refused=which==7;allocation=int(which in (5,7))
        require(type(row.get('case')) is int and row['case']==which and row.get('status')=='passed'
                and row.get('ordinaryDeliveryOnly') is (which in (0,4)), 'backing-real-case-order')
        require((row.get('backingFreeReturnsBeforeStoreDrop') is None if refused else
                 type(row.get('backingFreeReturnsBeforeStoreDrop')) is int
                 and row['backingFreeReturnsBeforeStoreDrop']==count)
                and row.get('postTrapFreeCountObserved') is False
                and row.get('parentFreeAfterTrapUnreachableByEmittedOrder') is refused
                and row.get('destructorRefused') is refused,'backing-original-allocator-return-or-unobserved-trap')
        counters={'allocations':allocation,'destructorCalls':allocation,
            'payloadDropsBeforeStoreDrop':0 if refused else allocation,'payloadDropsAfterStoreDrop':allocation,
            'futureStarts':1,'futureDrops':1,'observedImports':1,
            'matchedImportNativeOwnersBeforeStoreDrop':2 if refused else 0,
            'matchedImportResultOwnersBeforeStoreDrop':int(refused)}
        require(all(type(row.get(key)) is int and row[key]==value for key,value in counters.items()),
                'backing-real-original-owner-and-payload-retirement')
        owners=row.get('runtimeOwnersBeforeStoreDrop')
        require(type(owners) is list and len(owners)==7
                and all(type(value) is int and 0<=value<=64 for value in owners)
                and (owners[5]>0 and owners[6]>=2 if refused else owners[5]==0),
                'backing-original-ledger-before-store')
        require(type(row.get('peakLinearMemoryBytes')) is int and 0<row['peakLinearMemoryBytes']<=128*1024**2
                and type(row.get('fuel')) is int and 0<=row['fuel']<=1_000_000_000,'backing-original-execution-bounds')
        require(row.get('allocatorBoundaryOnly') is True and all(row.get(key) is False for key in
            ('osOrLinearMemoryReturnQualified','deliveredStorageCleanupQualified','parametersCleanupQualified',
             'partialLowerCleanupQualified','wholeCostQualification','physicalProviderQualified','signedExecution')),
            'backing-no-broader-release-claim')
    return rows
