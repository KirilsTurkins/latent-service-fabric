#!/usr/bin/env python3
"""Keep exact dependency comparisons while reconciling reviewed prerequisites."""
from pathlib import Path
import sys
kind=sys.argv.pop(1)
if kind=='runtime':
    wrapper=Path('.github/maintenance/runtime_security_repair_v2.py').read_text()
    end="exec(compile(source,'runtime_security_repair_v2.py','exec'))"
    assert wrapper.count(end)==1
    context={}
    exec(compile(wrapper.replace(end,''),'runtime_v2_transform','exec'),context)
    source=context['source']
    before="        assert without(old)==without(after), 'Unexpected dependency changes: '+p"
    after="""        expected=without(old)
        if p=='tools/native-fixture/Cargo.lock':
            # Its path dependency already requires 0.262.0 at the selected head.
            # Regeneration must repair that stale auxiliary lock, not retain a
            # second parser that no current manifest selects.
            expected=[row.copy() for row in expected if not (row['name']=='wasmparser' and row['version']=='0.259.0')]
            for row in expected:
                if row['name']=='wasm-encoder':
                    assert row['version']=='0.259.0'
                    row['version']='0.262.0'
                    row['checksum']='4495a6f85dd94c411c749303efcbc5defade0b0cbdbc0541495241ab917a9b5a'
                if 'dependencies' in row:
                    row['dependencies']=[v.replace('wasmparser 0.259.0','wasmparser').replace('wasmparser 0.262.0','wasmparser') for v in row['dependencies']]
        assert expected==without(after), 'Unexpected dependency changes: '+p"""
    assert source.count(before)==1;source=source.replace(before,after)
elif kind=='go':
    source=Path('.github/maintenance/go_security_repair.py').read_text()
    before="    compiler=TMP/'go-distribution/go';"
    after="""    inventory=WORK/'.github/security/inventory.json'
    data=json.loads(inventory.read_text())
    for entry in data['manifests']:
        if entry['kind']=='no-external-packages' and entry['path'] in changed:
            old=subprocess.check_output(['git','show',BASE+':'+entry['path']],cwd=WORK)
            assert digest(old.replace(b'\\r\\n',b'\\n'))==entry['sha256']
            entry['sha256']=digest((WORK/entry['path']).read_bytes().replace(b'\\r\\n',b'\\n'))
    write_json(inventory,data)
    compiler=TMP/'go-distribution/go';"""
    assert source.count(before)==1;source=source.replace(before,after)
else:raise SystemExit('expected runtime or go')
exec(compile(source,'reviewed_security_repair_v3','exec'))
