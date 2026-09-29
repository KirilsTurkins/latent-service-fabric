"""One-time authoring of an already reviewed, exact-tree-bound candidate.

Runs with read-only repository permissions; never installed in the final tree.
The original reviewed inventory is the migration input, not observed final code.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE_TREE = 'da458ba6dec0efd929bd5a8daa0dd4067b72eb08'
EXPECTED_TREE = '65a3bfa45523532437f7953d820392a3b22052a6'
OVERLAY_SHA256 = '742fed9e9e4f5f092327dd721511364324307df2c3d834c28cf01f9d6abd3438'
root, payload, output = map(lambda value: Path(value).resolve(), sys.argv[1:])
def git(*args, **kwargs):
    return subprocess.check_output(['git', *args], cwd=root, **kwargs).decode().strip()
assert git('rev-parse','HEAD^{tree}') == BASE_TREE
assert not git('status','--porcelain')
raw=payload.read_bytes()
assert hashlib.sha256(raw).hexdigest() == OVERLAY_SHA256
data=json.loads(raw)
overlay={}
for entry in data['source']:
    name=entry['path']; path=root/name
    assert not Path(name).is_absolute() and '..' not in Path(name).parts
    assert name.startswith(('tools/','docs/','.github/workflows/')) or name=='CONTRIBUTING.md'
    assert not path.is_symlink()
    if entry['baseBlob'] is None:
        assert not path.exists()
        old=[]
    else:
        original=path.read_bytes()
        assert hashlib.sha1(b'blob '+str(len(original)).encode()+b'\0'+original).hexdigest()==entry['baseBlob']
        old=original.decode().splitlines(keepends=True)
    value=''.join(''.join(old[op[1]:op[2]]) if op[0]=='copy' else op[1] for op in entry['ops'])
    assert hashlib.sha256(value.encode()).hexdigest()==entry['sha256']
    overlay[name]=value
# Bootstrap only storage/structural helpers; legacy owner hashes and workflows
# still match the immutable original snapshot during the lossless migration.
for name in ('tools/ci_contracts.py','tools/ci_lane_inventory.py'):
    (root/name).write_text(overlay[name])
subprocess.run([sys.executable,'tools/ci_contracts.py','migrate','--legacy','tools/ci/commands.json',
                '--output','tools/ci/contracts'],cwd=root,check=True)
legacy=root/'tools/ci/commands.json'
archive=root/'tools/ci/history/commands-v1.json'
archive.parent.mkdir(parents=True,exist_ok=True)
archive.write_bytes(legacy.read_bytes()); legacy.unlink()
for name,value in overlay.items():
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
# This is explicit one-time local authoring, never CI validation/auto-refresh.
# A hardcoded pre-reviewed target tree below makes any unreviewed edit fatal.
sys.path.insert(0,str(root))
from tools import ci_contracts as contracts, ci_coverage as coverage
records=contracts.fragments(root)
models=contracts.observed_workflows(root)
for value in records.values():
    if value['kind']=='workflow':
        model=models[value['workflow']]
        value['policy']={k:v for k,v in model.items() if k!='jobs'}
        assert value['requiredJobs']==sorted(model['jobs'])
    elif value['kind']=='job':
        value['definition']=models[value['workflow']]['jobs'][value['jobId']]
owners=coverage.delegated_owners(root,coverage.commands(root))
assert set(contracts.assemble(records)['delegatedOwners'])<=set(owners)
for name,item in owners.items():
    relative='owners/'+name+'.json'
    if relative in records:
        records[relative]['sha256']=item['sha256']
    else:
        records[relative]=contracts.record('owner',data['reasons'][relative],path=name,
                                          sha256=item['sha256'],reviewBoundary='committed-fingerprint')
for name,item in contracts.python_expectations(root).items():
    relative='python/'+Path(name).name+'.json'
    if relative in records:
        assert set(records[relative]['cases'])<=set(item['cases'])
        records[relative].update(item)
    else:
        records[relative]=contracts.record('python',data['reasons'][relative],module=name,**item)
for relative,reason in data['reasons'].items(): records[relative]['reviewReason']=reason
for relative,value in records.items():
    path=root/contracts.DIRECTORY/relative; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
git('add','-A')
actual_tree=git('write-tree')
assert actual_tree==EXPECTED_TREE, (actual_tree,EXPECTED_TREE)
coverage.validate(root)
# Serialize only reviewed candidate content for the separate non-executing
# publisher; this job has no credential with repository write permissions.
entries=[]
for name in git('diff','--cached','--name-only','--no-renames').splitlines():
    path=root/name
    if name=='tools/ci/history/commands-v1.json':
        entries.append({'path':name,'mode':'100644','type':'blob','sha':git('rev-parse','HEAD:tools/ci/commands.json')})
    elif path.exists():
        mode=git('ls-files','-s','--',name).split()[0]
        entries.append({'path':name,'mode':mode,'type':'blob','content':path.read_text()})
    else: entries.append({'path':name,'mode':'100644','type':'blob','sha':None})
output.mkdir(parents=True,exist_ok=True)
encoded=json.dumps({'base_tree':BASE_TREE,'tree':entries},ensure_ascii=False,separators=(',',':')).encode()
(output/'candidate-tree.json').write_bytes(encoded)
print('Candidate tree:',actual_tree)
print('Candidate transport SHA-256:',hashlib.sha256(encoded).hexdigest())
git('-c','user.name=LSF candidate validation','-c','user.email=validation@example.invalid','commit','-m','Validate exact reviewed issue 732 candidate')
(output/'candidate-identity.txt').write_text('tree '+actual_tree+'\ncommit '+git('rev-parse','HEAD')+'\n')
