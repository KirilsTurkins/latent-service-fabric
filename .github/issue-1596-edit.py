from pathlib import Path
import ast, json
root = Path.cwd()
for name in ('tools/ci_contracts.py','tools/ci_suite_inventory.py','tools/local_tests.py','tools/test_run.py'):
    tree=ast.parse((root/name).read_text())
    print('FUNCTIONS',name,[(n.name,n.lineno,n.end_lineno) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))])
for path in sorted((root/'tools').glob('qualify_*.py')):
    text=path.read_text(); lines=text.splitlines()
    if 'expectedCases' not in text and 'minimumCases' not in text: continue
    print('\nCONSUMER',path.relative_to(root))
    chosen=set()
    for i,line in enumerate(lines):
        if 'expectedCases' in line or 'minimumCases' in line:
            chosen.update(range(max(0,i-4),min(len(lines),i+5)))
    for i in sorted(chosen): print(f'{i+1}: {lines[i]}')
from tools import ci_suite_inventory as r,ci_contracts as c
s=r.load()
print('SUITES',len(s['suites']), 'RECIPES',json.dumps(s['recipes'],indent=2))
print('CASEFRAGMENTS',[str(p) for p in (root/'tools/ci/suites.cases.d').glob('*')])
print('PYTHON_RECORDS',len(c.python_expectations(root)))
for name,value in c.python_expectations(root).items():
    skips={case:guard for case,guard in value['guards'].items() if guard['skipSites'] or any('skip' in dec.lower() or 'expectedFailure' in dec for dec in guard['decorators']+guard['classDecorators'])}
    if skips: print('SKIP_POLICY',name,json.dumps(skips))
print('CI_ENTRYPOINTS')
for i,line in enumerate((root/'.github/workflows/ci.yml').read_text().splitlines(),1):
    if any(x in line for x in ('unittest','ci_suite_discovery','no-run','cargo test','ci_coverage')): print(i,line)
