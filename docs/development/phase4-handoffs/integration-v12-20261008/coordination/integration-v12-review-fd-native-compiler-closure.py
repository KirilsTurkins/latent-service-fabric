from pathlib import Path
import hashlib
import json
import subprocess

coord=Path(__file__).resolve().parent/'integration-v12-union-review'
pairs=[(823,Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12'),
 '0a0dc2818946111c8657e6b681ecef1f9f3fafab','0a783d97762f763ca6ab237d4bb36eb306bbddec'),
 (828,Path(r'C:\Users\turkins\Desktop\lf-p4-pr828-current-java-union-v12'),
 '7bc6e42254ef94c2b0248ad174d1e959aefc10e2','0a637ba7844c7fe461873d0fa783bca8166f4971')]
rows=[]
for pr,root,parent,head in pairs:
    names=subprocess.check_output(['git','-C',str(root),'diff','--name-only',parent,head]).decode().splitlines()
    assert names and all(name.startswith('docs/evidence/java-native-aot-6c0e6c1f/') or name=='tools/java_http_composition/qualify.py' for name in names)
    equal={}
    for directory in ('api','apps','crates','sdk','wit','schemas'):
        values=[subprocess.check_output(['git','-C',str(root),'rev-parse',rev+':'+directory]).decode().strip() for rev in (parent,head)]
        assert values[0]==values[1],directory;equal[directory]=values[0]
    for name in ('Cargo.toml','Cargo.lock','rust-toolchain.toml'):
        values=[subprocess.check_output(['git','-C',str(root),'show',rev+':'+name]) for rev in (parent,head)]
        assert values[0]==values[1],name;equal[name]=hashlib.sha256(values[0]).hexdigest()
    for name in ('tools/compile_transaction_guests.py','tools/java_transaction_schema.py','tools/java_transaction_diagnostics.py',
                 'tools/java_guest/compiler.py','tools/java_capsule_build.py','tools/java_capsule_project.py','tools/transaction_guest_variants.py',
                 'tools/java_transaction_qualification/current_inputs.py','tools/java_transaction_qualification/inputs.py'):
        values=[subprocess.check_output(['git','-C',str(root),'show',rev+':'+name]) for rev in (parent,head)]
        assert values[0]==values[1],name;equal[name]=hashlib.sha256(values[0]).hexdigest()
    rows.append(dict(pr=pr,actualQualifiedParent=parent,currentFdHead=head,changedPaths=names,
        nativeSourceAndCompilerSourceUnchanged=equal,qualifierSeparateLaneStillRequired=True,
        oldNativeAndCompilerReceiptsKeepActualParentHead=True,currentMain='fd4623acdc8f94e72291b85716c16d10dcd118cd',fullCi=False))
(coord/'current-fd-native-compiler-byte-closure.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps([dict(pr=row['pr'],head=row['currentFdHead'],nativeCompilerInputsByteIdentical=True) for row in rows]))
