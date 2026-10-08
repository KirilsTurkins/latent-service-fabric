from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
prior=coord/'portable-v2-pr811-buf-golden-source-20261008-v312'
raw=(prior/'receipt.json').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='b7764c8e2b3788f1a7b4648806d19c15ad5716915279e02f3b1f1e185bd0722c'
receipt=json.loads(raw)
assert receipt['head']=='f149bb009952e823c6d6f3877af80b298c5c7258'
assert all(receipt[k] for k in ['passed','sourceClean','sourceHeadUnchanged','originalProcessReaped'])
assert len(receipt['steps'])==9
for row in receipt['steps']:
    data=(prior/row['log']).read_bytes()
    assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
base=(coord/'integration-v12-current823-java-bridge-reused-source-controller-v21.py').read_text(encoding='utf8')
text=base.replace("'integration-v12-unavailable-observer-source-v20'","'portable-v2-pr811-buf-golden-source-20261008-v312'")
text=text.replace("'6d09d6095e8ada217a51b5f878e48aba62e03abf'","'f149bb009952e823c6d6f3877af80b298c5c7258'")
text=text.replace("'2e7d216746b29a9225d8ab7ccd68f6b8472a5a29f55b1110b78c00d1d4c03e50'","'b7764c8e2b3788f1a7b4648806d19c15ad5716915279e02f3b1f1e185bd0722c'")
text=text.replace("assert len(previous['steps']) == 7","assert len(previous['steps']) == 9")
text=text.replace("source = base / 'source-dca5d7737ef2ae37'","source = base / 'source-6ab38845e5a266f3'")
text=text.replace("assert mode == 'source', 'released Source-only checkout reuse'","assert mode == 'source' and head == '1417e360a96954ce8abcc845024e7b7ff0eccb99', 'released Source-only checkout reuse'")
compile(text,'current823-witness-reuse','exec')
out=coord/'integration-v12-current823-witness-reused-source-controller-v35.py'
out.write_text(text,encoding='utf8',newline='\n')
proof=dict(head='1417e360a96954ce8abcc845024e7b7ff0eccb99',priorHead=receipt['head'],
    priorReceiptSha256=hashlib.sha256(raw).hexdigest(),allNinePriorLogsAuthenticated=True,
    priorSourceCleanAndProcessesReaped=True,controllerSha256=hashlib.sha256(out.read_bytes()).hexdigest(),
    sourceLaunched=False,explicitOwnerReleaseReceived=True)
(coord/'integration-v12-union-review/current823-witness-reuse-preflight-v35.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
