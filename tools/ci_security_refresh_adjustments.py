#!/usr/bin/env python3
"""Apply narrowly reviewed preparation fixes to immutable maintenance drivers."""
import hashlib,pathlib,sys
kind,path=sys.argv[1],pathlib.Path(sys.argv[2])
source=path.read_text()
expected={'action':'f925f337ee6847e35647b9a11273f5809c74aec82747ea0b680a7c2441ebdd45','native':'74a00ed959ea2aeedd52bd33a6de72528e176fbe67678ee0acbce5f95d7ce667'}
assert hashlib.sha256(path.read_bytes()).hexdigest()==expected[kind]
if kind=='native':
    old="if name.startswith('crates/') and '/vendor/' not in name and p.name=='Cargo.toml':"
    new="if '/vendor/' not in name and p.name=='Cargo.toml':"
    assert source.count(old)==1;source=source.replace(old,new)
else:
    start=source.index("    if role=='rust-cache':\n        old=before['package-lock.json']")
    end=source.index("    checks.append(logrun('fixed-ci'",start)
    replacement='''    guard_paths = {
        'rust-cache': ['.lsf-source/verify-rust-cache-lock.mjs', '.lsf-source/rust-cache-lock.test.mjs'],
        'deploy-pages': ['.lsf-source/apply-verified-sources.cjs'],
        'download-artifact': ['.lsf-source/verify-download-sources.mjs'],
        'upload-artifact': ['.lsf-source/verify-upload-sources.mjs'],
    }.get(role, [])
    for guard_path in guard_paths:
        p=ROOT/guard_path;text=p.read_text();changed=False
        for name in ('package.json','package-lock.json'):
            old=before[name]['sha256'];new=ident((ROOT/name).read_bytes())['sha256']
            if old in text:
                assert text.count(old)==1,(guard_path,name)
                text=text.replace(old,new);changed=True
        assert changed,guard_path
        p.write_text(text)
'''
    source=source[:start]+replacement+source[end:]
    old="    if role=='rust-cache': allowed+=['.lsf-source/verify-rust-cache-lock.mjs','.lsf-source/rust-cache-lock.test.mjs']"
    assert source.count(old)==1;source=source.replace(old,'    allowed+=guard_paths')
    source=source.replace("'node':run('node','--version'),'npm':run('npm','--version'),", "'node':run('node','--version'),'npm':run('npm','--version'),'driverSha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),")
path.write_text(source)
print('Reviewed driver',kind,hashlib.sha256(path.read_bytes()).hexdigest())
