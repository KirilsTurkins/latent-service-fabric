from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old="    source = base / ('source-' + head[:16])"
new="""    prior = base / 'jobs' / 'entity-native-close-collector-source-20261008-v1'
    original_receipt = (prior / 'receipt.json').read_bytes()
    assert hashlib.sha256(original_receipt).hexdigest() == 'bfbb93f373928dcfcf42a8bbbd3dbfe097b88325082f99c8a38513bb93a0d873'
    previous = json.loads(original_receipt)
    assert previous['head'] == '81ef8ce169528c6dd8ba0de323612dc5f45d0de9'
    assert previous['passed'] and previous['sourceClean'] and previous['sourceHeadUnchanged'] and previous['originalProcessReaped']
    assert len(previous['steps']) == 7
    for original in previous['steps']:
        raw = (prior / original['log']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == original['sha256'] and len(raw) == original['bytes']
    source = base / 'source-dca5d7737ef2ae37'
    assert source.resolve().parent == base.resolve() and not source.is_symlink()
    assert call(['git','rev-parse','HEAD'], source) == previous['head']
    assert not call(['git','status','--porcelain'], source)
"""
assert source.count(old)==1
source=source.replace(old,new)
path=coord/'integration-v12-http-currentmain-source-reuse-controller-v8.py'
path.write_text(source,encoding='utf8')
print(json.dumps({'sourceOwnershipReleasedByEntity':True,'exactOriginalSourceReceiptAndLogsAuthenticated':True,
                  'newHead':'237fb3edc4ee39d17e361d69e88b43be2d5ea4f8','newClone':False}))
