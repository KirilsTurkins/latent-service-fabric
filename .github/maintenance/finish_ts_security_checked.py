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
change("    assert not run(['git','status','--porcelain','--untracked-files=normal'])", "    assert not run(['git','status','--porcelain','--untracked-files=normal'],capture=True)")
change("elif sys.argv[1]=='validate':\n", "elif sys.argv[1]=='validate':\n    log_test('source-identity-review',['python3',str(ROOT/'.github/maintenance/review_new_security_findings.py')],cwd=ROOT)\n")
change("    driver=TMP/'reviewed-action-integration.py';driver.write_text(script)", """    # A repository may supply distinct entrypoints (cache/save and restore).
    begin=script.index("    before=repo+'@'+base;after=repo+'@'+commit;references[before]=after")
    end=script.index('    if name in PROFILES:',begin)
    old=script[begin:end].splitlines(True)
    assert old[1].startswith("    row=actions['actions'].pop(before)")
    header="    selected=[key for key,value in actions['actions'].items() if value['repository']==repo and value['revision']==base]\\n    assert selected,(name,'selected-action-references')\\n    for before in selected:\\n        after=before.rsplit('@',1)[0]+'@'+commit;references[before]=after\\n"
    script=script[:begin]+header+''.join('    '+line if line.strip() else line for line in old[1:])+script[end:]
    # Each verifier owns its selected executable bundle set. Rust-cache uses
    # content-named chunks, so retain every emitted JS chunk after renaming.
    begin=script.index("        if name=='rust-cache':paths=")
    end=script.index('        runtime_maps[name]=',begin)
    bundle_code='''        selected_modules={
            'rust-cache':('security_rust_cache','RUNTIME'),
            'setup-go':('security_setup_go','RUNTIME'),
            'deploy-pages':('security_deploy_pages','RUNTIME'),
            'upload-artifact':('security_upload_artifact','RUNTIME'),
            'download-artifact':('security_download_artifact','RUNTIME'),
            'setup-dotnet':('security_dotnet_minimatch','RUNTIME'),
            'setup-python':('security_npm_sources','MINIMATCH_RUNTIME'),
            'setup-java':('security_npm_sources','JAVA_MINIMATCH_RUNTIME'),
            'setup-node':('security_npm_sources','NODE_MINIMATCH_RUNTIME')}
        module,key=selected_modules[name]
        declaration=next(n for n in ast.parse((WORK/'tools'/f'{module}.py').read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==key for t in n.targets))
        selection=ast.literal_eval(declaration.value)
        paths=sorted(path for path in record['files'] if path.startswith('dist/') and path.endswith('.js')) if name=='rust-cache' else [value.get('source',path) for path,value in selection.items()]
'''
    script=script[:begin]+bundle_code+script[end:]
    transitions={}
    exec(compile((ROOT/'.github/maintenance/action_integration_boundaries.py').read_text(),'reviewed_boundaries.py','exec'),transitions)
    script=transitions['repair'](script)
    constants={}
    exec(compile((ROOT/'.github/maintenance/action_integration_constants.py').read_text(),'reviewed_constants.py','exec'),constants)
    script=constants['repair_constants'](script)
    driver=TMP/'reviewed-action-integration.py';driver.write_text(script)""")
exec(compile(source,'checked_finish_ts_security.py','exec'))
