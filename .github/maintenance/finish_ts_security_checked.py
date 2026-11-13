#!/usr/bin/env python3
"""Fail closed on non-conflict Git failures during reviewed stack preparation."""
from pathlib import Path
source=Path('.github/maintenance/finish_ts_security.py').read_text()
def change(before,after):
    global source
    assert source.count(before)==1,before
    source=source.replace(before,after)
change("    run(['git','apply','--3way','--index',str(p)],check=False)","    applied=run(['git','apply','--3way','--index',str(p)],check=False)\n    assert applied.returncode==0 or applied.returncode==1 and conflicts(WORK), 'Go patch did not apply'")
change("    commit('fix(security): select authenticated Go 1.27.4 compiler')", "    assert 'go 1.27.4' in (WORK/'sdk/go/go.mod').read_text()\n    assert '8.0.428' in (WORK/'sdk/dotnet/global.json').read_text()\n    assert 'go1.27.4' in (WORK/'tools/dev_go_distribution.py').read_text()\n    commit('fix(security): select authenticated Go 1.27.4 compiler')")
change("        run(['git','merge','--no-ff','--no-commit',run(['git','rev-parse','HEAD'],capture=True)],cwd=child,check=False)","        merged=run(['git','merge','--no-ff','--no-commit',run(['git','rev-parse','HEAD'],capture=True)],cwd=child,check=False)\n        assert merged.returncode==0 or merged.returncode==1 and conflicts(child), 'Stack merge did not complete'")
change("    driver=TMP/'reviewed-action-integration.py';driver.write_text(script)", """    # A repository may supply distinct entrypoints (cache/save and restore).
    # Rotate each selected reference without collapsing those identities.
    begin=script.index("    before=repo+'@'+base;after=repo+'@'+commit;references[before]=after")
    end=script.index('    if name in PROFILES:',begin)
    old=script[begin:end].splitlines(True)
    assert old[1].startswith("    row=actions['actions'].pop(before)")
    header="    selected=[key for key,value in actions['actions'].items() if value['repository']==repo and value['revision']==base]\\n    assert selected,(name,'selected-action-references')\\n    for before in selected:\\n        after=before.rsplit('@',1)[0]+'@'+commit;references[before]=after\\n"
    script=script[:begin]+header+''.join('    '+line if line.strip() else line for line in old[1:])+script[end:]
    driver=TMP/'reviewed-action-integration.py';driver.write_text(script)""")
exec(compile(source,'checked_finish_ts_security.py','exec'))
