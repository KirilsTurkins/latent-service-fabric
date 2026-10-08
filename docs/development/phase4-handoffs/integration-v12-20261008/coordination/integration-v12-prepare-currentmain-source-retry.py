from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
prior=coord/'integration-v12-current823-development0cd-source-v7/receipt.json'
raw=prior.read_bytes();receipt=json.loads(raw)
assert receipt['head']=='6b272f45da25f229756c829287e4ee9dab087eca'
assert receipt['sourceClean'] and receipt['sourceHeadUnchanged'] and receipt['originalProcessReaped']
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old="    source = base / ('source-' + head[:16])"
new="""    prior = base / 'jobs' / 'integration-v12-current823-development0cd-source-v7'
    original_receipt = (prior / 'receipt.json').read_bytes()
    assert hashlib.sha256(original_receipt).hexdigest() == RECEIPT_HASH
    previous = json.loads(original_receipt)
    assert previous['head'] == '6b272f45da25f229756c829287e4ee9dab087eca'
    assert previous['sourceClean'] and previous['sourceHeadUnchanged'] and previous['originalProcessReaped']
    assert not previous['passed'] and previous['steps'][0]['exitCode'] == 1
    for original in previous['steps']:
        raw = (prior / original['log']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == original['sha256'] and len(raw) == original['bytes']
    source = base / 'source-6ab38845e5a266f3'
    assert source.resolve().parent == base.resolve() and not source.is_symlink()
    assert call(['git','rev-parse','HEAD'], source) == previous['head']
    assert not call(['git','status','--porcelain'], source)
""".replace('RECEIPT_HASH',repr(hashlib.sha256(raw).hexdigest()))
assert source.count(old)==1
source=source.replace(old,new)
path=coord/'integration-v12-currentmain-source-retry-controller-v8.py'
path.write_text(source,encoding='utf8')
print(json.dumps({'preservedOriginalFailedReceipt':str(prior),'newHead':'eafeb0f3046ddd5756258a37940a1d6cfd69f04a',
    'caseCountContractCorrectedByAdditiveActualFloor':True,'noOldQualificationClaim':True}))
