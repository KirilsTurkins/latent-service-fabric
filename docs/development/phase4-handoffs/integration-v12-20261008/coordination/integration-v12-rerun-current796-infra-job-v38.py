from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess

coord=Path(__file__).resolve().parent
env=dict(os.environ,GODEBUG='http2client=0')
repo='KirilsTurkins/latent-service-fabric'
job=113168379343
head='8f85a60021786138a25f75b8fbc22c32f8789844'
def api(endpoint):
    return json.loads(subprocess.check_output(['gh','api',endpoint],env=env))
live=json.loads(subprocess.check_output(['gh','pr','view','796','--repo',repo,'--json','headRefOid,state'],env=env))
detail=api(f'repos/{repo}/actions/jobs/{job}')
run=api(f'repos/{repo}/actions/runs/{detail["run_id"]}')
assert live['state']=='OPEN' and live['headRefOid']==head==detail['head_sha']==run['head_sha']
assert detail['status']=='completed' and detail['conclusion']=='failure'
assert detail['steps'][0]['conclusion']=='success'
assert any(s.get('conclusion')=='failure' and 'dtolnay/rust-toolchain' in s['name'] for s in detail['steps'])
proof=dict(at=datetime.now(timezone.utc).isoformat(),job=job,head=head,run=detail['run_id'],
    runStatus=run['status'],runAttempt=run['run_attempt'],singleInfrastructureInstallerFailure=True,
    actualRuntimeTestExecuted=False,sourceChanged=False,requestAccepted=False)
previous=[json.loads(p.read_bytes()) for p in (coord/'integration-v12-union-review').glob('current796-infra-rerun-guard-v38*.json')]
already_accepted=any(p.get('requestAccepted') is True and p.get('job')==job for p in previous)
if already_accepted:
    proof['rerunPreviouslyAccepted']=True
elif run['status']=='completed':
    result=subprocess.run(['gh','api','--method','POST',f'repos/{repo}/actions/jobs/{job}/rerun'],env=env,capture_output=True)
    proof['requestAccepted']=result.returncode==0
    proof['response']=result.stdout.decode(errors='replace')
    proof['error']=result.stderr.decode(errors='replace')
else:
    proof['rerunHeldUntilOriginalRunComplete']=True
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out=coord/('integration-v12-union-review/current796-infra-rerun-guard-v38-'+stamp+'.json')
out.write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
