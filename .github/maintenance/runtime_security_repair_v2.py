#!/usr/bin/env python3
"""Correct the reviewed manifest precondition; keep all validation commands."""
from pathlib import Path
source=Path('.github/maintenance/runtime_security_repair.py').read_text()
def change(before,after):
    global source
    assert source.count(before)==1, before
    source=source.replace(before,after)
change("    before={p:(WORK/p).read_bytes() for p in locks}","""    before={p:(WORK/p).read_bytes() for p in locks}
    manifests=run(['git','ls-files','*Cargo.toml'],capture=True).splitlines()
    explicit=[]
    for name in manifests:
        if name.startswith('crates/vendor/'): continue
        path=WORK/name;text=path.read_text()
        updated,count=re.subn(r'(?m)^(rustix\\s*=\\s*\\{[^\\n]*version\\s*=\\s*\\")=1\\.1\\.5(\\"[^\\n]*)$',r'\\g<1>=1.1.6\\2',text)
        if count:path.write_text(updated);explicit.append(name)
    assert 'apps/latentd/Cargo.toml' in explicit
    write_json(OUT/'explicit-rustix-manifests.json',explicit)""")
change("    write_json(inventory,data)","""    for row in data['manifests']:
        name=row['path'];path=WORK/name
        if row.get('manifest_sha256') and path.exists():
            old=subprocess.check_output(['git','show',BASE+':'+name],cwd=WORK)
            if sha(old)==row['manifest_sha256']:row['manifest_sha256']=sha(path.read_bytes())
    write_json(inventory,data)""")
exec(compile(source,'runtime_security_repair_v2.py','exec'))
