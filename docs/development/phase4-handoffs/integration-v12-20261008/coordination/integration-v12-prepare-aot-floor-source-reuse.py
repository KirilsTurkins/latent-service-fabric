from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old="    source = base / ('source-' + head[:16])"
new="""    prior = base / 'jobs' / 'entity-pr808-preserved-floor-source-20261008-v1'
    raw_receipt = (prior / 'receipt.json').read_bytes()
    assert hashlib.sha256(raw_receipt).hexdigest() == '82cbb5d0397299e51ab89b92347e25f15581bacd93244bbdf94d45a8cb8fa0cb'
    previous = json.loads(raw_receipt)
    assert previous['head'] == '1f12ebede3ca71b6f3ea908720fa4ccaa76d9878'
    assert previous['passed'] and previous['sourceClean'] and previous['sourceHeadUnchanged'] and previous['originalProcessReaped']
    assert len(previous['steps']) == 7
    for step in previous['steps']:
        raw = (prior / step['log']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == step['sha256'] and len(raw) == step['bytes']
    source = base / 'source-dca5d7737ef2ae37'
    assert source.resolve().parent == base.resolve() and not source.is_symlink()
    assert call(['git','rev-parse','HEAD'], source) == previous['head']
    assert not call(['git','status','--porcelain'], source)
"""
assert source.count(old)==1
source=source.replace(old,new)
path=coord/'integration-v12-aot-floor-source-reuse-controller-v9.py'
path.write_text(source,encoding='utf8')
print(json.dumps({'explicitEntitySourceOwnershipReleased':True,'receiptAndAll7LogsAuthenticated':True,
                  'newClone':False,'candidate':'44754a7b9de0b41c456bcbbf31797b0cd47b0814'}))
