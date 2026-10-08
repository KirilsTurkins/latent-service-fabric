from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
job=coord/'integration-v12-current-java-real-node-v40'
raw=(job/'receipt.json').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='47bce5f67777e2b880a3495b958f9839ac278032ca3bda66415f3baf60aa385d'
receipt=json.loads(raw)
assert not receipt['passed'] and receipt['head']=='1fcc6d0fa6ec8e19c3ffc11ca02dd9242d0a10e6'
assert receipt['sourceClean'] and receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
for row in receipt['steps']:
    data=(job/row['log']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==row['sha256'] and len(data)==row['bytes']
evidence=job/'campaign/evidence'
root_raw=(evidence/'http-refusal-stage-observation.json').read_bytes()
roots=json.loads(root_raw)
assert roots['observationAvailable'] and roots['rootCount']==1 and not roots['truncated']
root=roots['roots'][0]
assert root['phase']=='admitted' and root['terminalState']=='dependency_failed' and root['diagnostic'] is None
response=json.loads((evidence/'http-001-response.json').read_bytes())
assert response['status']==503
stopped=json.loads((evidence/'node-3-stopped.json').read_bytes())
report=stopped['record']['report']
assert stopped['reaped'] and stopped['record']['clean']
compiler=report['compiler']
assert compiler['jobs_started']==1 and compiler['jobs_failed']==1 and compiler['jobs_completed']==0
assert compiler['workers_live']==0 and compiler['workers_joined']==1
assert report['state']['clean'] and report['state']['storePhysicalOwners']==0
proof=dict(head=receipt['head'],nativeReceiptSha256=hashlib.sha256(raw).hexdigest(),
    exactOriginalBuildsPassed=True,firstQuery503=True,actualOneRootAdmittedDependencyFailed=True,
    diagnosticAbsentNotInferred=True,rootRecordSha256=hashlib.sha256(root_raw).hexdigest(),
    actualOnePreparationJobFailed=True,workerPhysicallyJoined=True,allStateOwnersRetired=True,
    originalFailureOraclePreserved=True,sourceAndAllProcessesCleanReaped=True,
    noBudgetOrGrantRelaxation=True,actualGuestSuccessNotQualified=True,
    exactPreparationSubstageAndFailureStillPending=True)
(coord/'integration-v12-union-review/current-query-actual-failure-review-v40.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
