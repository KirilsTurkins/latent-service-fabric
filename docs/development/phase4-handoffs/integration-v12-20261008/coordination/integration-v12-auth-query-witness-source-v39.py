from pathlib import Path
import hashlib
import json
import subprocess

coord=Path(__file__).resolve().parent
folder=coord/'integration-v12-current-query-witness-source-v39'
raw=(folder/'receipt.json').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='fe25613a81e8f4eba226313b40b72730aea2614363400064fac7f777bbd28e6a'
receipt=json.loads(raw)
head='1fcc6d0fa6ec8e19c3ffc11ca02dd9242d0a10e6'
assert receipt['head']==head and len(receipt['steps'])==7
assert all(receipt[k] for k in ['passed','sourceClean','sourceHeadUnchanged','originalProcessReaped'])
for row in receipt['steps']:
    data=(folder/row['log']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==row['sha256'] and len(data)==row['bytes']
assert 'Ran 397 tests' in (folder/'step-1.log').read_text()
assert 'Ran 12 tests' in (folder/'step-7.log').read_text()
repo=Path(r'C:\Users\turkins\Desktop\lf-p4-current-query-witness-union-v39')
production=['crates','apps','api','wit','Cargo.lock','Cargo.toml','sdk/java-guest','tools/java_guest',
    'tools/transaction_guest_project.py','examples/rust-capsules/transactional-aggregate']
delta=subprocess.check_output(['git','diff','--name-only','98281c17e28f9dd1dd6e9f0058069d71422df11e',head,'--',*production],cwd=repo,text=True)
assert not delta
proof=dict(head=head,receiptSha256=hashlib.sha256(raw).hexdigest(),allSevenRawLogsAuthenticated=True,
    actual397Discovered396Pass1OriginalSkip=True,actual12ProfilePass=True,
    oldFrozenNativeRecipeUnchanged=True,productionAndCompilerClosureUnchanged=True,
    currentWitnessFixturesRetained=True,currentActualNativePending=True)
(coord/'integration-v12-union-review/current-query-witness-source-qualified-v39.json').write_text(json.dumps(proof,indent=2)+'\n')
subprocess.run(['git','push','origin',head+':refs/heads/test/phase4-current-query-witness-union-v39'],cwd=repo,check=True)
assert subprocess.check_output(['git','ls-remote','origin','refs/heads/test/phase4-current-query-witness-union-v39'],cwd=repo,text=True).split()[0]==head
print(json.dumps(proof))
