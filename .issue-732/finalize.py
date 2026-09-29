"""Apply the final reviewed malformed-aggregate regression to an exact tree."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

BASE = 'da458ba6dec0efd929bd5a8daa0dd4067b72eb08'
INITIAL = '65a3bfa45523532437f7953d820392a3b22052a6'
FINAL = '6cfbcd33b10040114e96e3f4c61268febe8335db'
root, output = (Path(v).resolve() for v in sys.argv[1:])
def git(*args):
    return subprocess.check_output(['git', *args], cwd=root).decode().strip()
assert git('rev-parse', 'HEAD^{tree}') == INITIAL
assert not git('status', '--porcelain')
path = root/'tools/ci_lane_inventory.py'
text = path.read_text()
for old, new in (
    ('            or checks[0].get("if", "success()") not in {"success()", "always()"}',
     '            or not isinstance(checks[0].get("if", "success()"), str)\n            or checks[0].get("if", "success()") not in {"success()", "always()"}'),
    ('            or checks[0].get("env", {}).get("CI_JOB_RESULTS") != "${{ toJSON(needs) }}"):',
     '            or not isinstance(checks[0].get("env", {}), dict)\n            or checks[0].get("env", {}).get("CI_JOB_RESULTS") != "${{ toJSON(needs) }}"):'),
):
    assert text.count(old) == 1
    text = text.replace(old, new)
path.write_text(text)
contract = root/'tools/ci/contracts/owners/tools/ci_lane_inventory.py.json'
data = json.loads(contract.read_text())
data['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
contract.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)+'\n')
path = root/'tools/tests/test_ci_contracts.py'
old = '                    lambda gate: gate["steps"][0]["env"].update({"CI_JOB_RESULTS": "{}"})]'
new = '''                    lambda gate: gate["steps"][0]["env"].update({"CI_JOB_RESULTS": "{}"}),
                    lambda gate: gate["steps"][0].update({"env": None}),
                    lambda gate: gate["steps"][0].update({"env": []}),
                    lambda gate: gate["steps"][0].update({"if": {"unexpected": True}})]'''
text = path.read_text(); assert text.count(old) == 1; path.write_text(text.replace(old, new))
git('add', '-A')
assert git('write-tree') == FINAL
entries = []
for name in git('diff', '--cached', BASE, '--name-only', '--no-renames').splitlines():
    path = root/name
    if name == 'tools/ci/history/commands-v1.json':
        entries.append({'path':name, 'mode':'100644', 'type':'blob', 'sha':git('rev-parse', BASE+':tools/ci/commands.json')})
    elif path.exists():
        mode=git('ls-files','-s','--',name).split()[0]
        entries.append({'path':name, 'mode':mode, 'type':'blob', 'content':path.read_text()})
    else:
        entries.append({'path':name, 'mode':'100644', 'type':'blob', 'sha':None})
assert len(entries) == 480
output.mkdir(parents=True, exist_ok=True)
payload=json.dumps({'base_tree':BASE,'tree':entries},ensure_ascii=False,separators=(',',':')).encode()
(output/'candidate-tree.json').write_bytes(payload)
print('Final candidate tree:', FINAL)
print('Final transport SHA-256:',hashlib.sha256(payload).hexdigest())
git('-c','user.name=LSF candidate validation','-c','user.email=validation@example.invalid','commit','-m','Validate malformed aggregate input regression')
(output/'candidate-identity.txt').write_text('tree '+FINAL+'\ncommit '+git('rev-parse','HEAD')+'\n')
