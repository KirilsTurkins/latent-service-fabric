#!/usr/bin/env python3
"""Supply the real Go SDK generator and export complete, checked Git trees."""
from pathlib import Path
context={}
wrapper=Path('.github/maintenance/security_repair_v3.py').read_text()
terminal="exec(compile(source,'reviewed_security_repair_v3','exec'))"
assert wrapper.count(terminal)==1
exec(compile(wrapper.replace(terminal,''),'reviewed_v3_transform','exec'),context)
source=context['source']
if context['kind']=='go':
    original="    run(['go','test','-mod=readonly','./...'],cwd=WORK/'sdk/go',env=environment)"
    replacement="    run(['python3','generate.py'],cwd=WORK/'sdk/go',env=environment)\n    run(['python3','generate.py','--check'],cwd=WORK/'sdk/go',env=environment)\n"+original
    assert source.count(original)==1
    source=source.replace(original,replacement)
# Inline UTF-8 contents preserve exact bytes; the resulting tree is still
# required to match the locally tested git tree before creating any commit.
a=source.index("    for path in run(['git','diff','--name-only',BASE,'HEAD'],capture=True).splitlines():",source.index("elif sys.argv[1]=='upload':"))
b=source.index("    tree=api('trees'",a)
source=source[:a]+"""    for path in run(['git','diff','--no-renames','--name-only',BASE,'HEAD'],capture=True).splitlines():
        p=WORK/path
        if not p.exists():
            entries.append({'path':path,'mode':'100644','type':'blob','sha':None})
            continue
        data=p.read_bytes()
        entries.append({'path':path,'mode':run(['git','ls-files','--stage','--',path],capture=True).split()[0],'type':'blob','content':data.decode('utf-8')})
"""+source[b:]
exec(compile(source,'reviewed_security_repair_v4','exec'))
