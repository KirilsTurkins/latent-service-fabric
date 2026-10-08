from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old="    source = base / ('source-' + head[:16])"
new="""    prior = base / 'jobs' / 'entity-native-close-current-source-20261008-v1'
    raw_receipt = (prior / 'receipt.json').read_bytes()
    assert hashlib.sha256(raw_receipt).hexdigest() == '47302a77e40ccf161901ec356453ca7c5abcca7c93638dfccf155a6d9475777f'
    previous = json.loads(raw_receipt)
    assert previous['head'] == '656f3a71355a3cf3f3b09a2d6720f2b231044d36'
    assert previous['passed'] and previous['sourceClean'] and previous['sourceHeadUnchanged'] and previous['originalProcessReaped']
    for step in previous['steps']:
        raw = (prior / step['log']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == step['sha256'] and len(raw) == step['bytes']
    source = base / 'source-dca5d7737ef2ae37'
    assert source.resolve().parent == base.resolve() and not source.is_symlink()
    assert call(['git','rev-parse','HEAD'], source) == previous['head']
    assert not call(['git','status','--porcelain'], source)
"""
assert source.count(old)==1;source=source.replace(old,new)
(coord/'integration-v12-fd-source-reuse-controller-v12.py').write_text(source,encoding='utf8')
print(json.dumps({'explicitEntitySourceRelease':True,'all7PreviousLogsAuthenticated':True,'noClone':True}))
