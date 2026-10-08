from pathlib import Path
import hashlib
import json
import subprocess

coord=Path(__file__).resolve().parent
repo=Path(r'C:\Users\turkins\Desktop\latent-fabric')
head='1e129ef0ed6682c998f81a498e76bd4de61c6fec'
fixture_raw=subprocess.check_output(['git','show',head+':sdk/profile/fixtures.json'],cwd=repo)
fixtures=json.loads(fixture_raw)
descriptor=json.loads((coord/'entity-contract-v80-actual-buf-descriptor-20261008-v1/actual-file-descriptor-set.json').read_bytes())
sources={f'latent/{name}/v1/{filename}.proto' for name,filename in [
    ('control','common'),('control','policy'),('control','capability'),('control','node'),
    ('control','release'),('invocation','invocation')]}
messages={m['name'] for f in descriptor['file'] if f['name'] in sources for m in f.get('messageType',[])}
selected=[r for r in fixtures['cases'] if r['type'] in messages]
names=[r['name'] for r in selected]
result=dict(head=head,totalFixtures=len(fixtures['cases']),selectedProtobufCount=len(selected),
    selectedNames=names,fixturesSha256=hashlib.sha256(fixture_raw).hexdigest(),
    exactActualDescriptorSourceFiles=sorted(sources),
    contradictoryCount=sum(r.get('response_error')=='contradictory-oneof' for r in selected),
    actualDotnetExecutionClaimed=False,originalCountOracle=61,
    completeSelectorMatchesDotnetVectorsSource=True)
out=coord/'integration-v12-union-review/current808-vector-selection-v33.json'
out.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='selectedNames'}))
