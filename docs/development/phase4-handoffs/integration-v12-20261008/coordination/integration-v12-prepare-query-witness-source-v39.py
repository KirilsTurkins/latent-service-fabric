from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
head='1fcc6d0fa6ec8e19c3ffc11ca02dd9242d0a10e6'
prior=coord/'integration-v12-current823-witness-source-v35'
raw=(prior/'receipt.json').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='02bc45f676d84b8dfcf66ac33980c407bbcbf318d670e3f58dbbc7049bfb7622'
previous=json.loads(raw)
assert previous['head']=='1417e360a96954ce8abcc845024e7b7ff0eccb99' and len(previous['steps'])==7
assert all(previous[k] for k in ['passed','sourceClean','sourceHeadUnchanged','originalProcessReaped'])
for row in previous['steps']:
    data=(prior/row['log']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==row['sha256'] and len(data)==row['bytes']
steps=json.loads((coord/'integration-v12-current-collector-java-source-v22/invocation.json').read_bytes())['steps']
assert len(steps)==7
steps[3][-1]='target/ci/observed-current-query-witness-v39-linux.json'
steps[6][-1]+="; import os; from pathlib import Path; fmt=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/root-private-go127-formatter-20261007-v1/go/bin'); env=dict(os.environ,PATH=str(fmt)+os.pathsep+os.environ['PATH']); subprocess.run(['python3','-X','utf8','-B','-m','unittest','discover','-s','sdk/profile','-p','test_profile.py'],env=env,check=True)"
step_path=coord/'integration-v12-current-query-witness-source-steps-v39.json'
step_path.write_text(json.dumps(steps,indent=2)+'\n')
text=(coord/'integration-v12-current823-witness-reused-source-controller-v35.py').read_text()
text=text.replace("head == '1417e360a96954ce8abcc845024e7b7ff0eccb99'","head == '"+head+"'")
text=text.replace("'portable-v2-pr811-buf-golden-source-20261008-v312'","'integration-v12-current823-witness-source-v35'")
text=text.replace("'f149bb009952e823c6d6f3877af80b298c5c7258'","'1417e360a96954ce8abcc845024e7b7ff0eccb99'")
text=text.replace("'b7764c8e2b3788f1a7b4648806d19c15ad5716915279e02f3b1f1e185bd0722c'","'02bc45f676d84b8dfcf66ac33980c407bbcbf318d670e3f58dbbc7049bfb7622'")
text=text.replace("assert len(previous['steps']) == 9","assert len(previous['steps']) == 7")
compile(text,'query-witness-source','exec')
controller=coord/'integration-v12-current-query-witness-reused-source-controller-v39.py'
controller.write_text(text,encoding='utf8',newline='\n')
proof=dict(head=head,priorReceiptSha256=hashlib.sha256(raw).hexdigest(),allSevenPriorLogsAuthenticated=True,
    originalCurrentCollectorModulesPreserved=True,actual12ProfileCasesAdded=True,noNativeLaunched=True)
(coord/'integration-v12-union-review/current-query-witness-source-preflight-v39.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
