from pathlib import Path
import hashlib
import json
import re
import subprocess

coord=Path(__file__).resolve().parent
root=Path(r'C:\Users\turkins\Desktop\lf-p4-pr828-current-java-union-v12')
head='6f0a8e82299aa0a1224dee293aaa8a4db7f3a7d9'
job=coord/'integration-v12-http-current-java-native-v3'
receipt=json.loads((job/'receipt.json').read_text())
assert receipt['head']==head and receipt['passed'] and receipt['sourceClean']
assert receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
registry=json.loads(subprocess.check_output(['git','-C',str(root),'show',f'{head}:tools/ci/suites.json']))
rows={row['id']:row for row in registry['suites']}
raw=(job/'step-8.log').read_bytes(); text=raw.decode('utf8',errors='replace')
groups={};current=None;pending=None
for line in text.splitlines():
    match=re.search(r'Running unittests .*\(.*[/\\]deps[/\\](latent_node|latent_wire|latentd)-',line)
    if match:
        current=match.group(1);groups[current]=dict(passed=[],ignored=[],failed=[])
    case=re.fullmatch(r'test (.+?) \.\.\. (ok|FAILED|ignored)?(?:,.*)?\s*',line)
    if current and case:
        pending=case.group(1)
        if case.group(2):
            key={'ok':'passed','FAILED':'failed','ignored':'ignored'}[case.group(2)]
            groups[current][key].append(pending);pending=None
    elif current and pending and line in {'ok','FAILED','ignored'}:
        key={'ok':'passed','FAILED':'failed','ignored':'ignored'}[line]
        groups[current][key].append(pending);pending=None
result=[]
for binary,package in [('latent_node','latent-node'),('latent_wire','latent-wire'),('latentd','latentd')]:
    group=groups[binary]
    suite=next(row for row in rows.values() if row['package']==package and row['kind']=='lib')
    expected=set(suite['expectedCases']);actual=set(group['passed'])|set(group['ignored'])
    assert actual==expected,(binary,len(actual),len(expected),sorted(expected-actual),sorted(actual-expected))
    assert not group['failed']
    assert {name.rsplit('::',1)[-1] for name in group['ignored']}==set(suite['ignoredLeaves'])
    result.append(dict(package=package,passed=len(group['passed']),ignored=len(group['ignored']),
                       allRegisteredCasesExecuted=True,minimumCases=suite['minimumCases']))
value=dict(head=head,steps=len(receipt['steps']),runtimeGroups=result,
           fullRuntimeRawSha256=hashlib.sha256(raw).hexdigest(),fullCi=False)
(coord/'integration-v12-union-review/pr828-current-java-actual-runtime-native-review.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value))
