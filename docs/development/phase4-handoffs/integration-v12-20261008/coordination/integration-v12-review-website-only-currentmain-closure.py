from pathlib import Path
import hashlib
import json
import subprocess

coord=Path(__file__).resolve().parent/'integration-v12-union-review'
pairs=[(823,Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12'),
        'eafeb0f3046ddd5756258a37940a1d6cfd69f04a','511d5687f360258d05469cd2593de4d6f2556cf1'),
       (828,Path(r'C:\Users\turkins\Desktop\lf-p4-pr828-current-java-union-v12'),
        '237fb3edc4ee39d17e361d69e88b43be2d5ea4f8','f0322bb74085cc452cc7c9885a08b89ab218d290')]
records=[]
for pr,root,parent,head in pairs:
    names=subprocess.check_output(['git','-C',str(root),'diff','--name-only',parent,head]).decode().splitlines()
    assert names==['website/scripts/test-discovery.mjs']
    trees={}
    for name in ('api','apps','crates','sdk','tools','wit','schemas'):
        identities=[subprocess.check_output(['git','-C',str(root),'rev-parse',rev+':'+name]).decode().strip() for rev in (parent,head)]
        assert identities[0]==identities[1],name
        trees[name]=identities[0]
    for name in ('Cargo.toml','Cargo.lock','rust-toolchain.toml'):
        raw=[subprocess.check_output(['git','-C',str(root),'show',rev+':'+name]) for rev in (parent,head)]
        assert raw[0]==raw[1],name
        trees[name]=hashlib.sha256(raw[0]).hexdigest()
    records.append(dict(pr=pr,parentNativeAndSourceHead=parent,currentMainDescendant=head,changedPaths=names,
        sameNativeSourceSdkGeneratorsAndLockTrees=trees,newMain='9f7aab58400d446f451964dc492b34dc46d09f14',
        actualWebsiteBrowserDiscoveryHereExecuted=False,parentReceiptsKeepOriginalHead=True,completeCI=False))
(coord/'current9f-website-only-native-source-closure.json').write_text(json.dumps(records,indent=2)+'\n')
print(json.dumps([dict(pr=row['pr'],parent=row['parentNativeAndSourceHead'],head=row['currentMainDescendant'],nativeClosureByteIdentical=True) for row in records]))
