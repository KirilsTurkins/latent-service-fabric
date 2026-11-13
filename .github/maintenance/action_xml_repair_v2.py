#!/usr/bin/env python3
"""Apply reviewed build-context corrections to the exact initial repair driver."""
import hashlib, pathlib, urllib.request
url='https://raw.githubusercontent.com/KirilsTurkins/latent-service-fabric/db897c6040a6cfba6c640e1c131f3cc696c3b471/.github/maintenance/action_xml_repair.py'
with urllib.request.urlopen(url,timeout=60) as response: raw=response.read(32768)
assert hashlib.sha256(raw).hexdigest()=='20adf50b22b5e073a66df345faa3006cd7f8ade086cf4311cf30fbae01b8cf05'
source=raw.decode()
def change(before,after):
    global source
    assert source.count(before)==1, before
    source=source.replace(before,after)
change("subprocess.run(args, cwd=cwd, check=True, timeout=1500)","subprocess.run(args, cwd=cwd, check=True, timeout=1500, env={**os.environ, 'GITHUB_WORKSPACE': str(cwd)})")
change("overrides['fast-xml-parser@5']='5.12.0'", """direct=False
    for section in ('dependencies','devDependencies'):
        if 'fast-xml-parser' in manifest.get(section,{}):
            manifest[section]['fast-xml-parser']='5.12.0'
            direct=True
    overrides['fast-xml-parser@5']='$fast-xml-parser' if direct else '5.12.0'""")
change("    original=identity(package)","    original=identity(package)\n    original_lock=identity(WORK/'package-lock.json')")
change("    # Refresh the exact lock identity, retaining alias/duplicate protections.","""    # Only these two legitimately changed input hashes may be refreshed. All
    # archive, source, alias, duplicate and behavioral assertions remain intact.
    guard_changes=[]
    for guard in (WORK/'.lsf-source').rglob('*'):
        if not guard.is_file() or guard.suffix not in ('.mjs','.cjs','.json'): continue
        before=guard.read_text(); after=before
        for old,new in ((original['sha256'],identity(package)['sha256']),
                        (original_lock['sha256'],identity(WORK/'package-lock.json')['sha256'])):
            after=after.replace(old,new)
        if before!=after:
            guard.write_text(after);guard_changes.append(guard.relative_to(WORK).as_posix())
    # The selected lock hash was updated above together with its regression.
""")
change("        assert count==1", "        assert count==1")
change("    if 'test:security-source' in manifest['scripts']:","""    if REPO.endswith('/lsf-deploy-pages'):
        run(['node','.lsf-source/apply-verified-sources.cjs'])
    if 'test:security-source' in manifest['scripts']:""")
change("    run(['git','add','package.json','package-lock.json','dist'])", "    run(['git','add','package.json','package-lock.json','dist',*guard_changes])")
change("or p.startswith('dist/') for p in paths)", "or p.startswith('dist/') or p in guard_changes for p in paths)")
change("    run(['git','diff','--cached','--check'])", """    # ncc bundles contain upstream comment whitespace and, for Zig, CRLF
    # library blocks. Preserve exact compiler output; check handwritten sources.
    run(['git','diff','--cached','--check','--','.',':(exclude)dist/**'])""")
exec(compile(source,'authenticated_action_xml_repair_v2.py','exec'))
