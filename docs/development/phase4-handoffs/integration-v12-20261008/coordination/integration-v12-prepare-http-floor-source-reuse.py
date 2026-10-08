from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
receipt=coord/'integration-v12-current823-restored-aot-floor-source-v9/receipt.json'
raw=receipt.read_bytes();value=json.loads(raw)
assert value['head']=='44754a7b9de0b41c456bcbbf31797b0cd47b0814'
assert value['passed'] and value['sourceClean'] and value['sourceHeadUnchanged'] and value['originalProcessReaped']
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old="    source = base / ('source-' + head[:16])"
new="""    prior = base / 'jobs' / 'integration-v12-current823-restored-aot-floor-source-v9'
    raw_receipt = (prior / 'receipt.json').read_bytes()
    assert hashlib.sha256(raw_receipt).hexdigest() == RECEIPT_HASH
    previous = json.loads(raw_receipt)
    assert previous['head'] == '44754a7b9de0b41c456bcbbf31797b0cd47b0814'
    assert previous['passed'] and previous['sourceClean'] and previous['sourceHeadUnchanged'] and previous['originalProcessReaped']
    for step in previous['steps']:
        raw = (prior / step['log']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == step['sha256'] and len(raw) == step['bytes']
    source = base / 'source-dca5d7737ef2ae37'
    assert source.resolve().parent == base.resolve() and not source.is_symlink()
    assert call(['git','rev-parse','HEAD'], source) == previous['head']
    assert not call(['git','status','--porcelain'], source)
""".replace('RECEIPT_HASH',repr(hashlib.sha256(raw).hexdigest()))
assert source.count(old)==1
source=source.replace(old,new)
(coord/'integration-v12-http-aot-floor-source-reuse-controller-v9.py').write_text(source,encoding='utf8')
print(json.dumps({'explicitReapedSourceReuse':True,'nextHttpHead':'6f03062bc9131e477d09639fa9e77e7f84103d57','newClone':False}))
