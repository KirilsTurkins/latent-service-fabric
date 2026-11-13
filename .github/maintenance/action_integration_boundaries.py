"""Use the locally executed verifier transitions at their exact source boundaries."""
def repair(script: str) -> str:
    def change(before, after):
        nonlocal script
        assert script.count(before) == 1, before
        script = script.replace(before, after)
    change('identities={};records={};references={};runtime_maps={};build_urls={}',
           'identities={};records={};references={};runtime_maps={};build_urls={};previous_builds={}')
    change("        assert prior['publishedRevision']==base", "        assert prior['publishedRevision']==base\n        previous_builds[name]=prior")
    begin=script.index('# Byte-authentication and source reconstruction')
    end=script.index('# Active workflow refs',begin)
    script=script[:begin]+'''# Change only the old build-receipt checks; preserve source reconstruction,
# graph restrictions, installed source verification and actual runtime reads.
def replace_block(path,start,end,replacement):
    text=path.read_text();assert text.count(start)==1,(path,start)
    a=text.index(start);b=text.index(end,a);path.write_text(text[:a]+replacement+text[b:])
for name,module in [('setup-go','security_setup_go'),('upload-artifact','security_upload_artifact'),('download-artifact','security_download_artifact'),('deploy-pages','security_deploy_pages'),('rust-cache','security_rust_cache')]:
    path=WORK/'tools'/(module+'.py')
    start={'setup-go':'    build = decode_json(mini["build"])','upload-artifact':'    build = decode_json(material["fork-build.json"])','download-artifact':'    build = decode_json(material["fork-build.json"])','deploy-pages':'    build = decode_json(_read_bound(repo, BUILD))','rust-cache':'    build = decode_json(build_raw)'}[name]
    end='    deep_material = {' if name=='deploy-pages' else '    return '
    replace_block(path,start,end,start+'\\n    verify_rebuild(repo, build, REFERENCE, RUNTIME)\\n')
    text=path.read_text().replace('from tools.security_common import','from tools.security_action_rebuild import verify_rebuild\\nfrom tools.security_common import',1)
    text=text.replace(previous_builds[name]['publishedTree'],records[name]['tree']).replace(str(previous_builds[name]['run']),str(records[name]['workflowRun']))
    path.write_text(text)
path=WORK/'tools/security_npm_sources.py';text=path.read_text()
for fn,runtime in [('verify_minimatch_action_sources','MINIMATCH_RUNTIME'),('verify_java_minimatch_action_sources','JAVA_MINIMATCH_RUNTIME'),('verify_node_minimatch_action_sources','NODE_MINIMATCH_RUNTIME')]:
    a=text.index('def '+fn+'(');b=text.index('        build = decode_json(material["build"])',a);c=text.index('        receipts.append(',b)
    text=text[:b]+'        build = decode_json(material["build"])\\n        verify_rebuild(repo, build, selected["reference"], '+runtime+')\\n'+text[c:]
text=text.replace('from tools.security_common import','from tools.security_action_rebuild import verify_rebuild\\nfrom tools.security_common import',1)
text=text.replace(previous_builds['setup-go']['publishedTree'],records['setup-go']['tree']).replace(str(previous_builds['setup-go']['run']),str(records['setup-go']['workflowRun']))
path.write_text(text)
path=WORK/'tools/security_dotnet_minimatch.py';text=path.read_text();b=text.index('        build = decode_json(material["build"])');c=text.index('        receipts.append(',b)
text=text[:b]+'        build = decode_json(material["build"])\\n        verify_rebuild(repo, build, REFERENCE, RUNTIME)\\n'+text[c:]
text=text.replace('from tools.security_common import','from tools.security_action_rebuild import verify_rebuild\\nfrom tools.security_common import',1);path.write_text(text)
# Tests may rebind their finite runtime bytes, but cannot rewrite old receipts
# or retain a stale current-input mutation that no longer exercises a refusal.
for p in (WORK/'tools/tests').glob('test_security_*.py'):
    text=p.read_text();updated=text
    if p.stem in ['test_security_setup_go','test_security_upload_artifact','test_security_download_artifact','test_security_deploy_pages']:
        updated=updated.replace('evidence["bundles"] = identities','evidence["outputs"] = identities').replace('evidence["bundles"] = self.identities','evidence["outputs"] = self.identities')
    if p.stem=='test_security_rust_cache':updated=updated.replace('evidence["artifact"]["payloads"].update(identities)','evidence["outputs"].update(identities)')
    if p.stem in ['test_security_minimatch_action','test_security_java_minimatch_action','test_security_node_minimatch_action','test_security_dotnet_minimatch_action']:
        updated=updated.replace("build['artifact']['payloads'][row['source']] = {key: row[key] for key in ('bytes', 'sha256')}","build['outputs'][row['source']] = {key: row[key] for key in ('bytes', 'sha256', 'gitBlob')}")
    for name,prior in previous_builds.items():updated=updated.replace(prior['publishedTree'],records[name]['tree'])
    if updated!=text:p.write_text(updated)
''' + script[end:]
    return script
